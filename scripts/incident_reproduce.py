"""Standalone offline verifier/replayer; integrity checks precede engine imports."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def _json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON object key")
            value[key] = item
        return value
    def nonfinite(value):
        raise ValueError("Nonfinite JSON number")
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=nonfinite)


def artifact_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_integrity(bundle):
    if bundle.is_symlink():
        raise ValueError("Bundle cannot be a symlink")
    checksum_path = bundle / "checksums.json"
    if checksum_path.is_symlink() or checksum_path.stat().st_size > 100_000:
        raise ValueError("Invalid checksum manifest size/path")
    checksums = _json(checksum_path)
    if not isinstance(checksums, dict) or not 5 <= len(checksums) <= 200:
        raise ValueError("Invalid bundle checksum manifest")
    total = 0
    for name, expected in checksums.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or str(relative) != name:
            raise ValueError("Unsafe bundle path")
        path = bundle / name
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent.is_relative_to(bundle)):
            raise ValueError("Symlink in bundle")
        if not path.is_file() or path.stat().st_size > 35_000_000:
            raise ValueError("Missing or oversized bundle file: " + name)
        total += path.stat().st_size
        if total > 100_000_000:
            raise ValueError("Bundle exceeds bounded test size")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Bundle checksum mismatch: " + name)
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlink in bundle")
        if path.is_file() and str(path.relative_to(bundle)) not in {*checksums, "checksums.json"}:
            raise ValueError("Unmanifested bundle file")
    return checksums


def verify(bundle):
    checksums = file_integrity(bundle)
    def canonical_sha(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    job = _json(bundle / "incident.json")
    config = job["config"]
    if job.get("schema") != "forge.incident/v1" or canonical_sha(config) != job["config_sha"]:
        raise ValueError("Incident config binding mismatch")
    for name in ("scientific_source_lock", "adapter_lock"):
        lock = config[name]
        if not lock["files"] or canonical_sha(lock["files"]) != lock["sha256"] or any(checksums.get(k) != v for k, v in lock["files"].items()):
            raise ValueError("Frozen source lock mismatch before importing bundle code")
    locked_code = set(config["scientific_source_lock"]["files"]) | set(config["adapter_lock"]["files"])
    for name in checksums:
        if (name.endswith(".py") and name not in locked_code) or Path(name).suffix in {".pyc", ".pyo", ".so", ".dylib", ".pyd"}:
            raise ValueError("Executable bundle file is outside the frozen source locks")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(bundle))
    from engine import TASK_SPEC_HASH, content_hash, runtime_lock
    from engine.policy import validate_checkpoint
    from engine.audit import audit_episode
    from engine.simulator import episode_evidence_hash
    from control.incident_validation import (diagnostic_summary, episode_validity, pair_validity,
                                             reproduction_differences, original_scenario, intervention_scenario)
    if job.get("schema") != "forge.incident/v1" or content_hash(config) != job["config_sha"] or config["task_spec_hash"] != TASK_SPEC_HASH:
        raise ValueError("Incident config/task binding mismatch")
    for name in ("scientific_source_lock", "adapter_lock"):
        lock = config[name]
        if content_hash(lock["files"]) != lock["sha256"] or any(checksums.get(k) != v for k, v in lock["files"].items()):
            raise ValueError("Frozen source lock mismatch")
    checkpoint = validate_checkpoint(_json(bundle / "checkpoint.json"), config["checkpoint_hash"])
    if artifact_sha(checkpoint) != config["checkpoint_sha"]:
        raise ValueError("Checkpoint artifact binding mismatch")
    source = _json(bundle / "source.json")
    if artifact_sha(source) != config["source_artifact_sha"] or source["evidence_hash"] != config["source_evidence_hash"] or source["scenario"] != config["source_scenario"] or source["success"] is not False:
        raise ValueError("Exact source evidence binding mismatch")
    episode_validity(source, config["source_scenario"], checkpoint)
    if not audit_episode(source)["valid"]:
        raise ValueError("Source dense oracle reconstruction failed")
    seeds = config["paired_seeds"]
    if len(seeds) != config["nuisance_repeats"] + 1 or len(set(seeds)) != len(seeds) or seeds[0] != config["source_scenario"]["seed"]:
        raise ValueError("Invalid anchored/fresh paired schedule")
    if config["from_value"] != config["source_scenario"]["parameters"][config["factor"]]:
        raise ValueError("Intervention delta does not bind source")
    intervention_scenario(config["source_scenario"], config["factor"], config["value"])
    if config.get("planner_receipt_sha"):
        plan = _json(bundle / "planner-receipt.json")
        bindings = {k: config[k] for k in ("campaign_id", "source_episode_id", "factor", "value", "source_artifact_sha", "source_evidence_hash", "checkpoint_sha", "task_spec_hash")}
        if artifact_sha(plan) != config["planner_receipt_sha"] or plan.get("schema") != "forge.intervention-plan/v1" or plan.get("status") != "validated" or any(plan.get(k) != v for k, v in bindings.items()):
            raise ValueError("Planner receipt does not bind this intervention")
        if artifact_sha(plan.get("context")) != plan.get("context_sha") or any(plan["context"].get(k) != config[k] for k in ("campaign_id", "source_episode_id", "source_artifact_sha", "source_evidence_hash", "checkpoint_sha", "task_spec_hash")):
            raise ValueError("Planner context hash/source binding mismatch")
        review = _json(bundle / "planner-review.json")
        if content_hash(review) != config.get("planner_review_sha") or review.get("schema") != "forge.intervention-plan-review/v1" or review.get("receipt_sha") != config["planner_receipt_sha"] or review.get("decision") != "accept":
            raise ValueError("Planner explicit accepted review binding mismatch")
        derivation = plan.get("derivation")
        if derivation is not None:
            original = _json(bundle / "planner-original-receipt.json")
            original_content = original.get("final_content")
            if artifact_sha(original) != derivation.get("original_receipt_sha") or not isinstance(original_content, str) or hashlib.sha256(original_content.encode()).hexdigest() != derivation.get("original_response_sha256") or plan.get("final_content") != original_content or plan.get("final_content_sha256") != derivation["original_response_sha256"]:
                raise ValueError("Derived planner response/original metered receipt linkage mismatch")
            if plan.get("inference_performed") is not False or plan.get("count_as_provider_call") is not False or plan.get("additional_estimated_cost_usd") != 0:
                raise ValueError("Local planner derivation cannot count as another provider call/cost")
            fields = ("campaign_id", "source_episode_id", "source_artifact_sha", "source_evidence_hash", "checkpoint_sha", "task_spec_hash", "provider", "model", "returned_model", "request_hash", "context_sha")
            if any(plan.get(k) != original.get(k) for k in fields) or derivation.get("original_request_id") != original.get("request_id"):
                raise ValueError("Derived planner receipt changed original provider/source identity")
    episodes, seen, dense_audits = {}, set(), 1
    for attempt in job["attempts"]:
        if attempt["status"] == "launch_failed":
            continue
        trial, branch = attempt["trial_index"], attempt["branch"]
        if type(trial) is not int or not 0 <= trial < len(seeds) or branch not in {"original", "intervention"} or (trial, branch) in seen or attempt["seed"] != seeds[trial]:
            raise ValueError("Invalid or duplicated attempt identity")
        seen.add((trial, branch))
        if not attempt.get("episode_sha"):
            if attempt["status"] == "completed":
                raise ValueError("Completed attempt has no episode")
            continue
        path = bundle / "episodes" / f"episode-{trial}-{branch}.json"
        if hashlib.sha256(path.read_bytes()).hexdigest() != attempt["episode_sha"]:
            raise ValueError("Attempt episode checksum mismatch")
        episode = _json(path)
        if episode_evidence_hash(episode) != episode["evidence_hash"] or attempt["evidence_hash"] != episode["evidence_hash"]:
            raise ValueError("Attempt evidence binding mismatch")
        if any(content_hash(attempt.get(k)) != content_hash(episode.get(k)) for k in ("status", "success", "terminal_reason")):
            raise ValueError("Attempt summary contradicts episode")
        expected_scene = original_scenario(config["source_scenario"], seeds[trial]) if branch == "original" else intervention_scenario(config["source_scenario"], config["factor"], config["value"], seeds[trial])
        if episode["status"] == "completed":
            episode_validity(episode, expected_scene, checkpoint)
            if episode["trace"]["recorded"]:
                if not audit_episode(episode)["valid"]:
                    raise ValueError("Dense oracle reconstruction failed")
                dense_audits += 1
        elif episode["success"] is not None or episode["scenario"] != expected_scene:
            raise ValueError("Interrupted attempt has invalid outcome or scenario")
        episodes[(trial, branch)] = episode
    pair_indices = []
    for pair in job["pairs"]:
        trial = pair["trial_index"]
        if type(trial) is not int or not 0 <= trial < len(seeds) or trial in pair_indices or pair["seed"] != seeds[trial]:
            raise ValueError("Invalid paired outcome identity")
        pair_indices.append(trial)
        original, intervention = episodes[(trial, "original")], episodes[(trial, "intervention")]
        validity = pair_validity(original, intervention, config["source_scenario"], checkpoint, config["factor"], config["value"], seeds[trial])
        if trial == 0:
            differences = reproduction_differences(source, original)
            validity.update(source_reproduction_differences=differences, source_reproduction_verified=not differences)
            if differences:
                raise ValueError("Source anchor does not reproduce original evidence")
        if content_hash(validity) != content_hash(pair["validity"]):
            raise ValueError("Recorded paired validity differs from recomputation")
        for branch, episode in (("original", original), ("intervention", intervention)):
            if any(content_hash(pair[branch].get(k)) != content_hash(episode.get(k)) for k in ("episode_id", "success", "terminal_reason", "evidence_hash")):
                raise ValueError("Paired summary contradicts episode")
    if "summary" in job and content_hash(job["summary"]) != content_hash(diagnostic_summary(job["pairs"])):
        raise ValueError("Diagnostic summary differs from retained pairs")
    if job["status"] == "completed" and (sorted(pair_indices) != list(range(len(seeds))) or len(episodes) != 2 * len(seeds) or job["validity"].get("valid") is not True):
        raise ValueError("Completed incident is missing scheduled paired evidence")
    current = runtime_lock()
    pinned = ("python", "mujoco", "numpy", "controller_revision", "asset_revision", "task_spec_hash")
    differences = {k: {"recorded": config["runtime"][k], "current": current[k]} for k in pinned if config["runtime"][k] != current[k]}
    import scipy
    if config["statistics_runtime"]["scipy"] != scipy.__version__:
        differences["scipy"] = {"recorded": config["statistics_runtime"]["scipy"], "current": scipy.__version__}
    report = {"valid": True, "files": len(checksums), "attempts": len(job["attempts"]), "pairs": len(job["pairs"]), "dense_oracle_audits": dense_audits,
              "status": job["status"], "summary": job.get("summary"), "label": job["label"],
              "runtime_dependencies_match": not differences, "runtime_dependency_differences": differences,
              "replay_absolute_tolerance": 1e-6, "replay_relative_tolerance": 1e-7,
              "platform": {"recorded": {k: config["runtime"][k] for k in ("os", "os_version", "machine")}, "current": {k: current[k] for k in ("os", "os_version", "machine")}}}
    return report, job, checkpoint, episodes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--all-pairs", action="store_true")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.checkpoint and not args.rerun or args.all_pairs and not args.rerun:
        parser.error("--checkpoint and --all-pairs require --rerun")
    bundle = args.bundle.absolute()
    report, job, checkpoint, expected = verify(bundle)
    if args.rerun:
        if not report["runtime_dependencies_match"]:
            raise ValueError("Pinned runtime dependency mismatch; inspect verification report before replay")
        from engine import run_episode
        from control.incident_validation import compatible_checkpoint, original_scenario, intervention_scenario, pair_validity, reproduction_differences
        alternate = bool(args.checkpoint)
        if alternate:
            if args.checkpoint.stat().st_size > 2_000_000:
                raise ValueError("Alternate checkpoint exceeds 2 MB")
            checkpoint = compatible_checkpoint(_json(args.checkpoint))
        config = job["config"]
        trials = range(len(config["paired_seeds"])) if args.all_pairs else [0]
        report["reruns"] = []
        report["alternate_checkpoint"] = {"supplied": alternate, "checkpoint_hash": checkpoint["checkpoint_hash"], "policy_id": checkpoint["policy_id"]}
        for trial in trials:
            seed = config["paired_seeds"][trial]
            scenes = [original_scenario(config["source_scenario"], seed), intervention_scenario(config["source_scenario"], config["factor"], config["value"], seed)]
            episodes = [run_episode(scene, checkpoint, trace=trial == 0) for scene in scenes]
            validity = pair_validity(*episodes, config["source_scenario"], checkpoint, config["factor"], config["value"], seed)
            result = {"trial_index": trial, "seed": seed, "validity": validity}
            for branch, episode in zip(("original", "intervention"), episodes):
                differences = [] if alternate else reproduction_differences(expected[(trial, branch)], episode)
                result[branch] = {"success": episode["success"], "terminal_reason": episode["terminal_reason"], "evidence_hash": episode["evidence_hash"], "differences": differences,
                                  "matches_recorded": None if alternate else not differences, "metrics": episode["metrics"]}
                if differences:
                    report["valid"] = False
            report["reruns"].append(result)
        report["interpretation"] = "Alternate checkpoint diagnostic; original expected outcomes are not imposed." if alternate else "Fresh physics reproduction of the bound original checkpoint."
    text = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        output = args.output.absolute()
        if output.is_relative_to(bundle):
            raise ValueError("Write reports outside the integrity-checked bundle")
        output.write_text(text + "\n")
    print(text)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
