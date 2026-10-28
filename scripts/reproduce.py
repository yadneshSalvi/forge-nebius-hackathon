"""Verify and replay a portable FORGE bundle without services, databases or API keys."""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys

SHA256 = re.compile(r"[a-f0-9]{64}\Z")
NON_OBJECT_SHAS = {"source_sha", "protocol_sha", "task_sha", "config_sha", "request_sha", "evaluation_source_sha"}
EVALUATION_FILES = ("control/final_eval.py","control/final_report.py","control/final_worker.py","control/statistics.py","control/lineage.py","scripts/run_registered_evaluation.py")
MAX_OBJECT_BYTES = 128*1024*1024

class ReproductionError(ValueError):
    pass

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReproductionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result

def _read_json(path, limit=MAX_OBJECT_BYTES):
    if path.stat().st_size > limit:
        raise ReproductionError(f"JSON file exceeds bounded size: {path.name}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=lambda value: (_ for _ in ()).throw(ReproductionError("nonfinite JSON value")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReproductionError(f"invalid JSON: {path.name}") from exc
    return raw, value

def _safe_relative(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name:
        raise ReproductionError("unsafe checksum path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or str(path) != name or name == ".":
        raise ReproductionError(f"unsafe checksum path: {name}")
    return path

def _all_files(root):
    found = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs+files:
            path = Path(directory)/name
            if path.is_symlink():
                raise ReproductionError(f"bundle symlink rejected: {path.relative_to(root)}")
        for name in files:
            found.add((Path(directory)/name).relative_to(root).as_posix())
    return found

def _source_lock(root):
    """Read literal scientific file names without importing server/provider code."""
    try:
        tree = ast.parse((root/"control/lineage.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "source_lock")
        declaration = next(n for n in function.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "scientific" for t in n.targets))
        names = ast.literal_eval(declaration.value)
    except (OSError, SyntaxError, StopIteration, ValueError, TypeError) as exc:
        raise ReproductionError("unsupported bundled source-lock declaration") from exc
    if not isinstance(names, (tuple, list)) or not all(isinstance(n, str) and n.endswith(".py") and "/" not in n and "\\" not in n for n in names):
        raise ReproductionError("unsafe scientific source-lock list")
    paths = sorted((root/"engine").glob("*.py"))+[root/"control"/name for name in names]
    if not (root/"engine/__init__.py").is_file() or any(not p.is_file() for p in paths):
        raise ReproductionError("bundled scientific source file missing")
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if not p.name.startswith("_pilot")}
    return {"files": files, "sha256": hashlib.sha256(canonical(files)).hexdigest()}

def _required_references(value):
    if isinstance(value, dict):
        if value.get("schema") in {"forge.episode/v1", "forge.numpy-waypoint-mlp/v1", "forge.expert/v1", "forge.demonstration/v1"}:
            return set()
        result = set()
        for key, child in value.items():
            if key.endswith("_sha") and key not in NON_OBJECT_SHAS and child is not None:
                if not isinstance(child, str) or not SHA256.fullmatch(child):
                    raise ReproductionError(f"invalid artifact reference: {key}")
                result.add(child)
            elif key.endswith("_shas"):
                if not isinstance(child, list) or not all(isinstance(v, str) and SHA256.fullmatch(v) for v in child):
                    raise ReproductionError(f"invalid artifact reference list: {key}")
                result.update(child)
            else:
                result.update(_required_references(child))
        return result
    if isinstance(value, list):
        result = set()
        for child in value:
            if isinstance(child, (dict, list)):
                result.update(_required_references(child))
        return result
    return set()

class Bundle:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.checksums, self.objects = {}, {}
        self.campaign, self.source_lock, self.engine, self.report = None, None, None, None

    def load_object(self, sha):
        if not isinstance(sha, str) or not SHA256.fullmatch(sha) or sha not in self.objects:
            raise ReproductionError(f"referenced artifact missing: {sha}")
        raw, value = _read_json(self.objects[sha])
        if hashlib.sha256(raw).hexdigest() != sha or raw != canonical(value):
            raise ReproductionError(f"canonical object SHA mismatch: {sha}")
        return value

    def verify_files(self):
        if not self.root.is_dir() or (self.root/"checksums.json").is_symlink():
            raise ReproductionError("bundle directory/checksum file is missing or unsafe")
        try:
            _, checksums = _read_json(self.root/"checksums.json", limit=10*1024*1024)
        except OSError as exc:
            raise ReproductionError("bundle checksums.json is missing") from exc
        if not isinstance(checksums, dict) or not checksums or len(checksums) > 100000:
            raise ReproductionError("invalid checksum manifest")
        for name, digest in checksums.items():
            _safe_relative(name)
            if name == "checksums.json" or not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise ReproductionError("invalid/self-referential checksum entry")
        actual, expected = _all_files(self.root), set(checksums)|{"checksums.json"}
        if actual != expected:
            missing, extra = sorted(expected-actual), sorted(actual-expected)
            raise ReproductionError(f"bundle file set mismatch; missing={missing[:4]}, unexpected={extra[:4]}")
        for name, expected_sha in checksums.items():
            path = self.root.joinpath(*PurePosixPath(name).parts)
            if not path.is_file() or not path.resolve().is_relative_to(self.root):
                raise ReproductionError(f"unsafe/missing bundle file: {name}")
            with path.open("rb") as stream:
                measured = hashlib.file_digest(stream, "sha256").hexdigest()
            if measured != expected_sha:
                raise ReproductionError(f"file checksum mismatch: {name}")
            if name.startswith("objects/"):
                match = re.fullmatch(r"objects/([a-f0-9]{64})\.json", name)
                if not match:
                    raise ReproductionError(f"invalid object filename: {name}")
                self.objects[match[1]] = path
        self.checksums = checksums
        try:
            raw, self.campaign = _read_json(self.root/"campaign.json", limit=64*1024*1024)
        except OSError as exc:
            raise ReproductionError("campaign.json is missing") from exc
        if not isinstance(self.campaign, dict) or raw != canonical(self.campaign):
            raise ReproductionError("campaign.json must be a canonical object")
        self.source_lock = _source_lock(self.root)
        if self.campaign.get("config", {}).get("source_sha") != self.source_lock["sha256"]:
            raise ReproductionError("campaign scientific source lock mismatch")
        for required in ["requirements.txt", "engine/__init__.py", "control/lineage.py"]:
            if required not in checksums:
                raise ReproductionError(f"required portable file missing: {required}")
        return self

    def import_engine(self):
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(self.root))
        engine = importlib.import_module("engine")
        loaded = Path(engine.__file__).resolve().parent
        bundled_names = {p.name for p in (self.root/"engine").glob("*.py")}
        loaded_names = {p.name for p in loaded.glob("*.py")}
        if bundled_names != loaded_names or any((loaded/name).read_bytes() != (self.root/"engine"/name).read_bytes() for name in bundled_names):
            raise ReproductionError("loaded engine differs from bundled source; run the bundled script in a fresh Python process")
        if self.campaign.get("config", {}).get("task_sha") != engine.TASK_SPEC_HASH:
            raise ReproductionError("campaign task hash incompatible with bundled engine")
        self.engine = engine
        return engine

    def verify(self):
        self.verify_files()
        engine = self.import_engine()
        seen_episodes, seen_demos, seen_policies = set(), set(), set()
        demo_payloads, checkpoints, episode_policy_hashes = {}, {}, set()
        evaluation_claims, evaluation_snapshots, evaluation_maps = set(), set(), []
        dense_audits = 0

        def episode_check(value):
            nonlocal dense_audits
            digest = engine.episode_evidence_hash(value)
            if digest != value.get("evidence_hash") or value.get("task_spec_hash") != engine.TASK_SPEC_HASH:
                raise ReproductionError("episode evidence/task hash mismatch")
            components = value.get("oracle", {}).get("components", {})
            expected = {"inside_target", "released", "stable", "lifted", "protected_position", "protected_orientation", "no_forbidden_contact"}
            if set(components) != expected or any(type(v) is not bool for v in components.values()):
                raise ReproductionError("episode oracle component schema mismatch")
            if value.get("status") == "completed":
                if type(value.get("success")) is not bool or value["success"] != all(components.values()) or value["success"] != value.get("oracle", {}).get("success"):
                    raise ReproductionError("completed episode oracle verdict mismatch")
                from engine.oracle import final_verdict, geometry_components
                metrics = value["metrics"]
                geometry = geometry_components(metrics["final_payload_position"], metrics["final_payload_quaternion"], [metrics["final_linear_speed"], 0, 0], [metrics["final_angular_speed"], 0, 0], metrics["final_gripper_opening"], value["scenario"]["parameters"]["tray_offset_y"])
                reconstructed = final_verdict(geometry, metrics["stable_duration"], metrics["max_payload_height"], metrics["protected_max_displacement"], metrics["protected_max_angle"], metrics["forbidden_contact_steps"])
                if reconstructed != value["oracle"] or reconstructed["terminal_reason"] != value.get("terminal_reason"):
                    raise ReproductionError("episode terminal geometry/oracle/metrics mismatch")
                if value.get("trace", {}).get("physics") and digest not in seen_episodes:
                    if not engine.audit_episode(value)["valid"]:
                        raise ReproductionError("dense episode geometry/contact reconstruction mismatch")
                    dense_audits += 1
            elif value.get("status") != "interrupted" or value.get("success") is not None:
                raise ReproductionError("invalid partial episode status/verdict")
            seen_episodes.add(digest)
            episode_policy_hashes.add(value.get("policy", {}).get("checkpoint_hash"))

        def validate(value):
            if isinstance(value, dict):
                if "evaluation_source_sha" in value:
                    claim=value["evaluation_source_sha"]
                    if not isinstance(claim,str) or not SHA256.fullmatch(claim):raise ReproductionError("malformed evaluation source digest")
                    evaluation_claims.add(claim)
                if "evaluation_source_lock_sha" in value:evaluation_snapshots.add(value["evaluation_source_lock_sha"])
                if "evaluation_source_files" in value:evaluation_maps.append(value["evaluation_source_files"])
                schema = value.get("schema")
                if schema in {"forge.numpy-waypoint-mlp/v1", "forge.expert/v1"}:
                    engine.validate_checkpoint(value)
                    seen_policies.add(value["checkpoint_hash"])
                    checkpoints[value["checkpoint_hash"]] = value
                elif schema == "forge.demonstration/v1":
                    engine.validate_demonstration(value)
                    episode_check(value["episode"])
                    seen_demos.add(value["demo_id"])
                    from engine.policy import _demo_payload
                    demo_payloads[value["demo_id"]] = _demo_payload(value)
                elif schema == "forge.episode/v1":
                    episode_check(value)
                elif schema == "forge.invalid-reset/v1":
                    if value.get("success") is not None or value.get("status") != "invalid_scene":
                        raise ReproductionError("invalid-scene record contains a task verdict")
                else:
                    for child in value.values(): validate(child)
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, (dict, list)): validate(child)

        references = _required_references(self.campaign)
        validate(self.campaign)
        for name in self.checksums:
            if name.startswith("related_campaigns/"):
                raw,related=_read_json(self.root/name,limit=64*1024*1024)
                if not re.fullmatch(r"related_campaigns/fg-[a-f0-9]{10}\.json",name) or raw!=canonical(related):raise ReproductionError("invalid related campaign envelope")
                references.update(_required_references(related));validate(related)
        for sha in self.objects:
            value = self.load_object(sha)
            references.update(_required_references(value))
            validate(value)
        evaluation_sha=None
        if evaluation_claims or evaluation_snapshots or evaluation_maps:
            if not all(name in self.checksums for name in EVALUATION_FILES):raise ReproductionError("evaluation source files are missing")
            files={name:self.checksums[name] for name in EVALUATION_FILES}
            evaluation_sha=hashlib.sha256(canonical(files)).hexdigest()
            expected_lock={"files":files,"sha256":evaluation_sha}
            if evaluation_claims!={evaluation_sha}:raise ReproductionError("evaluation source digest does not match bundled files")
            if not evaluation_snapshots and not evaluation_maps:raise ReproductionError("evaluation source digest has no included lock/manifest snapshot")
            if any(value!=files for value in evaluation_maps):raise ReproductionError("evaluation source manifest file map mismatch")
            for sha in evaluation_snapshots:
                if self.load_object(sha)!=expected_lock:raise ReproductionError("evaluation source lock artifact mismatch")
        missing = sorted(references-set(self.objects))
        if missing:
            raise ReproductionError(f"referenced artifacts missing from bundle: {missing[:4]}")
        base = self.load_object(self.campaign.get("config", {}).get("base_checkpoint_sha"))
        engine.validate_checkpoint(base)
        if base.get("kind") != "numpy_waypoint_mlp":
            raise ReproductionError("campaign base must be a learned waypoint checkpoint")
        for location in (self.campaign, self.campaign.get("config", {})):
            if location.get("source_lock_sha") and self.load_object(location["source_lock_sha"]) != self.source_lock:
                raise ReproductionError("source-lock artifact does not match bundled source")
            if location.get("task_artifact_sha") and self.load_object(location["task_artifact_sha"]) != engine.task_spec():
                raise ReproductionError("task artifact does not match bundled engine")
            if location.get("base_index_sha"):
                index = self.load_object(location["base_index_sha"])
                if index.get("checkpoint_sha") != self.campaign["config"]["base_checkpoint_sha"] or index.get("checkpoint_hash") != base["checkpoint_hash"]:
                    raise ReproductionError("base index points to a different checkpoint")
                ordered_ids = [self.load_object(sha).get("demo_id") for sha in index.get("demo_shas", [])]
                if ordered_ids != base.get("training", {}).get("demo_ids"):
                    raise ReproductionError("base index demonstration lineage mismatch")
        known_policies = seen_policies|{engine.expert_policy()["checkpoint_hash"]}
        if episode_policy_hashes-known_policies:
            raise ReproductionError("episode refers to a missing/incompatible checkpoint")
        for checkpoint in checkpoints.values():
            if checkpoint["kind"] != "numpy_waypoint_mlp": continue
            ids = checkpoint.get("training", {}).get("demo_ids", [])
            if not ids or len(ids) != len(set(ids)) or any(i not in demo_payloads for i in ids):
                raise ReproductionError("checkpoint training demonstration lineage is incomplete")
            if engine.content_hash([demo_payloads[i] for i in ids]) != checkpoint["training"].get("manifest_hash"):
                raise ReproductionError("checkpoint training manifest hash mismatch")
            parent = checkpoint.get("parent_checkpoint_hash")
            if parent is not None and parent not in known_policies:
                raise ReproductionError("checkpoint parent is missing from bundle")
        self.report = {"valid": True, "files_verified": len(self.checksums), "canonical_objects_verified": len(self.objects), "checkpoints": len(seen_policies), "demonstrations": len(seen_demos), "episodes": len(seen_episodes), "dense_oracle_audits": dense_audits, "source_sha": self.source_lock["sha256"], "task_sha": engine.TASK_SPEC_HASH, "network_requests": 0}
        if evaluation_sha is not None:self.report["evaluation_source_sha"]=evaluation_sha
        return self.report

    def _rerun(self, stored, policy, mode, artifact_sha):
        runtime = self.engine.runtime_lock()
        recorded_runtime = stored.get("runtime", {})
        for name in ("mujoco", "numpy"):
            if runtime.get(name) != recorded_runtime.get(name):
                raise ReproductionError(f"pinned {name} runtime mismatch: expected {recorded_runtime.get(name)}, got {runtime.get(name)}")
        if runtime["python"].split(".")[:2] != recorded_runtime.get("python", "").split(".")[:2]:
            raise ReproductionError("Python major/minor version differs from recorded runtime")
        if policy["checkpoint_hash"] != stored.get("policy", {}).get("checkpoint_hash"):
            raise ReproductionError("selected policy does not match recorded episode")
        actual = self.engine.run_episode(stored["scenario"], policy, trace=False)
        expected = {k: stored[k] for k in ("status", "success", "terminal_reason", "oracle", "policy_observation", "policy_action", "metrics")}
        measured = {k: actual[k] for k in expected}
        differences = _compare(expected, measured)
        return {"mode": mode, "matches": not differences, "artifact_sha": artifact_sha, "stored_episode_id": stored["episode_id"], "rerun_episode_id": actual["episode_id"], "scenario_id": stored["scenario"]["scenario_id"], "checkpoint_hash": policy["checkpoint_hash"], "success": actual["success"], "terminal_reason": actual["terminal_reason"], "physics_steps": actual["metrics"]["physics_steps"], "physics_wall_seconds": actual["timing"]["wall_seconds"], "absolute_tolerance": 1e-6, "relative_tolerance": 1e-7, "differences": differences, "same_os_and_architecture": all(runtime.get(k) == recorded_runtime.get(k) for k in ("os", "machine")), "runtime": runtime, "simulation_only": True, "network_requests": 0}

    def rerun_sample(self):
        if self.report is None: self.verify()
        base_sha = self.campaign.get("config", {}).get("base_checkpoint_sha")
        base = self.load_object(base_sha)
        rows = self.campaign.get("episodes", [])
        if not isinstance(rows, list): raise ReproductionError("campaign episode list is invalid")
        # Preserve campaign order within each class; rich evidence is easier to inspect.
        ordered = [r for r in rows if r.get("trace_available")]+[r for r in rows if not r.get("trace_available")]
        for row in ordered:
            if row.get("success") is not False or row.get("status") != "completed": continue
            raw = self.load_object(row.get("artifact_sha"))
            if raw.get("schema") != "forge.episode/v1" or raw.get("status") != "completed" or raw.get("success") is not False: continue
            if raw.get("policy", {}).get("checkpoint_hash") != base["checkpoint_hash"]: continue
            return self._rerun(raw, base, "frozen_base_failure", row["artifact_sha"])
        raise ReproductionError("bundle has no completed frozen-base failure to rerun")

    def rerun_demo(self, selector="first"):
        if self.report is None: self.verify()
        if selector == "first":
            rows = self.campaign.get("curriculum", {}).get("demonstrations", [])
            candidates = [r["trajectory_sha"] for r in rows if r.get("arm") not in {None, "all"} and r.get("success") is True and r.get("trajectory_sha")]
            if not candidates: raise ReproductionError("bundle has no corrective demonstration")
            sha = candidates[0]
        else:
            sha = selector
        demo = self.load_object(sha)
        self.engine.validate_demonstration(demo)
        result = self._rerun(demo["episode"], self.engine.expert_policy(), "successful_expert_demonstration", sha)
        result["demo_id"] = demo["demo_id"]
        return result


def _compare(expected, actual, path=""):
    differences = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            return [{"path": path, "reason": "object keys differ"}]
        for key in expected:
            differences.extend(_compare(expected[key], actual[key], f"{path}.{key}" if path else key))
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return [{"path": path, "reason": "array lengths differ"}]
        for i, value in enumerate(expected): differences.extend(_compare(value, actual[i], f"{path}[{i}]"))
    elif type(expected) is bool or expected is None or isinstance(expected, str):
        if type(actual) is not type(expected) or actual != expected:
            differences.append({"path": path, "expected": expected, "actual": actual})
    elif isinstance(expected, (int, float)):
        integer = type(expected) is int and type(actual) is int
        if not isinstance(actual, (int, float)) or type(actual) is bool or not math.isfinite(actual) or (actual != expected if integer else not math.isclose(actual, expected, abs_tol=1e-6, rel_tol=1e-7)):
            differences.append({"path": path, "expected": expected, "actual": actual})
    elif actual != expected:
        differences.append({"path": path, "reason": "value differs"})
    return differences


def verify_bundle(path):
    bundle = Bundle(path)
    bundle.verify()
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="clean extracted bundle directory")
    parser.add_argument("--verify", action="store_true", help="verify files, source lock, objects and engine evidence")
    parser.add_argument("--rerun-sample", action="store_true", help="rerun the first recorded frozen-base failure, preferring full traces")
    parser.add_argument("--rerun-demo", nargs="?", const="first", metavar="SHA", help="rerun the first corrective expert demonstration, or a specified demo artifact SHA")
    args = parser.parse_args(argv)
    if not (args.verify or args.rerun_sample or args.rerun_demo):
        parser.error("choose --verify, --rerun-sample, or --rerun-demo")
    try:
        bundle = verify_bundle(args.bundle)
        output = {"verification": bundle.report}
        if args.rerun_sample: output["rerun_sample"] = bundle.rerun_sample()
        if args.rerun_demo: output["rerun_demo"] = bundle.rerun_demo(args.rerun_demo)
        print(json.dumps(output, sort_keys=True, indent=2, allow_nan=False))
        return 0 if all(output[key]["matches"] for key in ("rerun_sample", "rerun_demo") if key in output) else 1
    except (ReproductionError, OSError, ValueError, ImportError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({"valid": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
