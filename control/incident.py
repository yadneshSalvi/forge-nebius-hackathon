"""Bounded additive incident jobs and small offline regression-test bundles."""
from __future__ import annotations
import contextlib
import copy
import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from engine import FACTOR_SPEC, TASK_SPEC_HASH, content_hash, runtime_lock, run_episode, task_spec
from engine.policy import validate_checkpoint
from engine.simulator import episode_evidence_hash
from .lineage import source_lock
from .store import ROOT, Conflict, canonical, now
from .incident_validation import (LABEL, SCOPE, diagnostic_summary, episode_validity,
                                  intervention_scenario, original_scenario, pair_validity,
                                  reproduction_differences)

MAX_JOBS = 24
MAX_DISK_BYTES = 192 * 1024 * 1024
ID_PATTERN = r"inc-[a-f0-9]{20}"
ACTIVE = {"queued", "running"}


def adapter_lock():
    paths = [ROOT / "control/__init__.py"] + sorted((ROOT / "control").glob("incident*.py")) + sorted((ROOT / "scripts").glob("incident*.py"))
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return {"files": files, "sha256": content_hash(files)}


def _write(path, value):
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def _process_identity(pid):
    if not pid:
        return None
    try:
        result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "pgid=", "-o", "stat=", "-o", "command="], capture_output=True, text=True, timeout=2)
        parts = result.stdout.strip().split(None, 7)
        if result.returncode or len(parts) != 8 or "Z" in parts[6]:
            return None
        command = parts[7]
        # macOS framework Python replaces only argv[0] during startup. Keep
        # complete module/data/id arguments and normalize known interpreter paths.
        executable_paths = {sys.executable, str(Path(sys.executable).resolve()),
                            str(Path(sys.base_prefix) / "Resources/Python.app/Contents/MacOS/Python")}
        for executable in sorted(executable_paths, key=len, reverse=True):
            if command == executable or command.startswith(executable + " "):
                command = "<python>" + command[len(executable):]
                break
        return {"started": " ".join(parts[:5]), "pgid": int(parts[5]), "command": command}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


class Incidents:
    def __init__(self, store):
        self.store = store
        self.path = store.path / "incidents"
        self.path.mkdir(exist_ok=True)

    @contextlib.contextmanager
    def locked(self):
        with (self.path / ".lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def folder(self, iid):
        if not re.fullmatch(ID_PATTERN, iid):
            raise ValueError("Malformed incident id")
        folder = self.path / iid
        if not folder.is_dir():
            raise KeyError(iid)
        return folder

    def get(self, iid):
        job = json.loads((self.folder(iid) / "job.json").read_text())
        if job["status"] in ACTIVE:
            identity = _process_identity(job.get("pid"))
            orphaned = job.get("pid") and (not identity or identity != job.get("process_identity"))
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(job["created_at"])).total_seconds()
            if orphaned or (not job.get("pid") and age > 30):
                job["status"] = "failed"
                job["error"] = "Incident launch/owned process was lost; retained attempts are excluded. Submit a new idempotency key for an explicit new attempt."
        return job

    def list(self):
        return sorted([self.get(p.name) for p in self.path.glob("inc-*") if p.is_dir()], key=lambda j: j["created_at"], reverse=True)

    def planner_review(self, sha):
        path = self.store.path / "intervention-plan-reviews" / f"{sha}.json"
        if not path.is_file() or path.stat().st_size > 20_000:
            raise ValueError("Planner receipt requires an explicit accepted review before physics")
        review = json.loads(path.read_text())
        if review.get("schema") != "forge.intervention-plan-review/v1" or review.get("receipt_sha") != sha or review.get("decision") != "accept":
            raise ValueError("Planner review rejects or does not accept this receipt")
        if not isinstance(review.get("reason"), str) or not review["reason"] or not isinstance(review.get("reviewed_at"), str):
            raise ValueError("Planner accepted review needs recorded reason/time")
        return review

    def original_plan(self, plan):
        derivation = plan.get("derivation")
        if derivation is None:
            return None
        if not isinstance(derivation, dict) or plan.get("inference_performed") is not False or plan.get("count_as_provider_call") is not False or plan.get("additional_estimated_cost_usd") != 0:
            raise ValueError("Derived planner receipt must identify local validation without duplicate inference/cost")
        original = self.store.read_artifact(derivation["original_receipt_sha"])
        content = original.get("final_content")
        if not isinstance(content, str) or hashlib.sha256(content.encode()).hexdigest() != derivation.get("original_response_sha256") or plan.get("final_content") != content or plan.get("final_content_sha256") != derivation["original_response_sha256"]:
            raise ValueError("Derived planner response does not bind the exact original provider output")
        fields = ("campaign_id", "source_episode_id", "source_artifact_sha", "source_evidence_hash", "checkpoint_sha", "task_spec_hash", "provider", "model", "returned_model", "request_hash", "context_sha")
        if any(plan.get(k) != original.get(k) for k in fields) or derivation.get("original_request_id") != original.get("request_id"):
            raise ValueError("Derived planner receipt changed original provider/source identity")
        return original

    def snapshot_files(self, config):
        return {**config["scientific_source_lock"]["files"], **config["adapter_lock"]["files"]}

    def verify_snapshot(self, folder, config):
        for name, expected in self.snapshot_files(config).items():
            path = folder / "sources" / name
            if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Frozen incident source snapshot mismatch: " + name)

    def context(self, cid):
        parent = self.store.get(cid, detail=False)
        if parent["status"] != "completed" or "counterexample" not in parent or parent["config"].get("kind"):
            raise Conflict("Requires a completed development campaign with a measured counterexample")
        if parent["config"]["source_sha"] != source_lock()["sha256"] or parent["config"]["task_sha"] != TASK_SPEC_HASH:
            raise Conflict("Source/task changed since this development incident was recorded")
        counter = parent["counterexample"]
        boundaries = [counter] + counter.get("secondary_boundaries", [])
        sources, seen = [], set()
        for index, boundary in enumerate(boundaries):
            for role in ("minimized", "source"):
                eid = boundary.get(role + "_episode_id")
                if not eid or eid in seen:
                    continue
                seen.add(eid)
                with self.store.connect() as connection:
                    row = connection.execute("SELECT artifact_sha FROM episodes WHERE campaign_id=? AND id=?", (cid, eid)).fetchone()
                if row is None:
                    raise ValueError("Counterexample does not belong to source campaign")
                episode = self.store.read_artifact(row["artifact_sha"])
                if episode["status"] != "completed" or episode["success"] is not False or episode["scenario"]["split"] in {"sealed", "challenge"}:
                    continue
                if episode_evidence_hash(episode) != episode["evidence_hash"] or episode["runtime"] != runtime_lock():
                    raise Conflict("Source evidence/runtime does not match current exact replay runtime")
                checkpoint = validate_checkpoint(self.store.read_artifact(parent["config"]["base_checkpoint_sha"]))
                if episode["policy"]["checkpoint_hash"] != checkpoint["checkpoint_hash"]:
                    raise ValueError("Source checkpoint does not match frozen campaign base")
                sources.append({"source_episode_id": eid, "scenario": episode["scenario"], "success": False,
                                "terminal_reason": episode["terminal_reason"], "checkpoint_hash": checkpoint["checkpoint_hash"],
                                "policy_id": checkpoint["policy_id"], "source_artifact_sha": row["artifact_sha"],
                                "name": f"{'Primary' if index == 0 else 'Secondary'} {role} failure"})
        return {"campaign_id": cid, "factor_spec": FACTOR_SPEC, "sources": sources, "label": LABEL, "scope": SCOPE,
                "nuisance_repeats_semantics": "1–20 fresh paired draws plus one separately reported exact-source-seed anchor"}

    def create(self, request, key):
        request = copy.deepcopy(request)
        repeats = request.setdefault("nuisance_repeats", 1)
        request.setdefault("planner_receipt_sha", None)
        if set(request) != {"campaign_id", "source_episode_id", "factor", "value", "nuisance_repeats", "planner_receipt_sha"}:
            raise ValueError("Unknown incident request fields")
        if not re.fullmatch(r"[a-zA-Z0-9:_-]{8,100}", key or ""):
            raise ValueError("Valid Idempotency-Key required")
        if isinstance(repeats, bool) or not isinstance(repeats, int) or not 1 <= repeats <= 20:
            raise ValueError("nuisance_repeats must be 1..20 fresh draws")
        request_sha, key_sha = content_hash(request), content_hash(key)
        with self.locked():
            for prior in self.list():
                if prior["idempotency_key_sha"] == key_sha:
                    if prior["request_sha"] != request_sha:
                        raise Conflict("Idempotency key has different inputs")
                    return prior, False
            jobs = self.list()
            if any(job["status"] in ACTIVE for job in jobs):
                raise Conflict("Another incident owns the bounded incident worker")
            if any(c["status"] in {"queued", "running", "pause_requested", "cancel_requested"} for c in self.store.list_campaigns()):
                raise Conflict("A campaign currently owns the local worker")
            size = sum(p.stat().st_size for p in self.path.rglob("*") if p.is_file())
            if len(jobs) >= MAX_JOBS or size >= MAX_DISK_BYTES or shutil.disk_usage(self.path).free < 128 * 1024 * 1024:
                raise Conflict("Incident storage/work budget exhausted; retain/export evidence before local maintenance")
            context = self.context(request["campaign_id"])
            source = next((s for s in context["sources"] if s["source_episode_id"] == request["source_episode_id"]), None)
            if source is None:
                raise ValueError("Source must be an exact eligible development counterexample id")
            episode = self.store.read_artifact(source["source_artifact_sha"])
            intervention_scenario(episode["scenario"], request["factor"], request["value"])
            parent = self.store.get(request["campaign_id"], detail=False)
            checkpoint_sha = parent["config"]["base_checkpoint_sha"]
            checkpoint = self.store.read_artifact(checkpoint_sha)
            episode_validity(episode, episode["scenario"], checkpoint)
            plan, review, original_plan = None, None, None
            if request["planner_receipt_sha"] is not None:
                plan = self.store.read_artifact(request["planner_receipt_sha"])
                bindings = {"campaign_id": request["campaign_id"], "source_episode_id": request["source_episode_id"],
                            "factor": request["factor"], "value": request["value"], "status": "validated",
                            "source_artifact_sha": source["source_artifact_sha"], "source_evidence_hash": episode["evidence_hash"],
                            "checkpoint_sha": checkpoint_sha, "task_spec_hash": TASK_SPEC_HASH}
                if plan.get("schema") != "forge.intervention-plan/v1" or any(plan.get(k) != v for k, v in bindings.items()):
                    raise ValueError("Planner receipt does not bind this exact intervention context")
                context = plan.get("context")
                if not isinstance(context, dict) or hashlib.sha256(canonical(context)).hexdigest() != plan.get("context_sha") or any(context.get(k) != bindings[k] for k in ("campaign_id", "source_episode_id", "source_artifact_sha", "source_evidence_hash", "checkpoint_sha", "task_spec_hash")):
                    raise ValueError("Planner context hash/source binding mismatch")
                review = self.planner_review(request["planner_receipt_sha"])
                original_plan = self.original_plan(plan)
            iid = "inc-" + uuid.uuid4().hex[:20]
            config = {**request, "from_value": episode["scenario"]["parameters"][request["factor"]],
                      "source_scenario": episode["scenario"], "source_artifact_sha": source["source_artifact_sha"],
                      "source_evidence_hash": episode["evidence_hash"], "checkpoint_sha": checkpoint_sha,
                      "checkpoint_hash": checkpoint["checkpoint_hash"], "task_spec_hash": TASK_SPEC_HASH,
                      "scientific_source_lock": source_lock(), "adapter_lock": adapter_lock(), "runtime": runtime_lock()}
            config["description"] = f"Recorded {episode['terminal_reason']} under the frozen base policy. Test {request['factor']} from {episode['scenario']['parameters'][request['factor']]} to {request['value']} with all other factors fixed."
            config["expected_failure_family"] = episode["terminal_reason"]
            config["planner_review_sha"] = content_hash(review) if review else None
            import scipy
            config["statistics_runtime"] = {"scipy": scipy.__version__}
            import numpy as np
            config["schedule_nonce"] = iid
            rng = np.random.default_rng(int(content_hash(config)[:16], 16))
            seeds = [episode["scenario"]["seed"]]
            previous = {seed for prior in jobs if prior["config"]["source_scenario"]["parameters"] == episode["scenario"]["parameters"] for seed in prior["config"]["paired_seeds"]}
            while len(seeds) < repeats + 1:
                seed = int(rng.integers(0, 2**32))
                if seed not in seeds and seed not in previous:
                    seeds.append(seed)
            config["paired_seeds"] = seeds
            job = {"schema": "forge.incident/v1", "id": iid, "status": "queued", "created_at": now(), "updated_at": now(),
                   "idempotency_key_sha": key_sha, "request_sha": request_sha, "config": config, "config_sha": content_hash(config),
                   "label": LABEL, "scope": SCOPE, "progress": {"completed": 0, "total": 2 * len(seeds), "message": "Queued for real paired MuJoCo execution"},
                   "attempts": [], "pairs": [], "validity": {"valid": False, "state": "not_executed"}, "pid": None, "error": None}
            folder = self.path / iid
            folder.mkdir()
            for name, expected in self.snapshot_files(config).items():
                raw = (ROOT / name).read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError("Source changed while freezing incident snapshot")
                target = folder / "sources" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            for name in ("control/__init__.py", "LICENSE", "engine/ASSET_LICENSE.txt"):
                target = folder / "sources" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            _write(folder / "task.json", task_spec())
            _write(folder / "job.json", job)
            _write(folder / "checkpoint.json", checkpoint)
            (folder / "source.json.gz").write_bytes(gzip.compress(canonical(episode), mtime=0))
            if plan:
                _write(folder / "planner-receipt.json", plan)
                _write(folder / "planner-review.json", review)
                if original_plan:
                    _write(folder / "planner-original-receipt.json", original_plan)
            return job, True

    def launch(self, iid):
        folder = self.folder(iid)
        with self.locked():
            job = self.get(iid)
            if job["status"] != "queued" or job.get("pid"):
                return
            env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "SYSTEMROOT", "MUJOCO_GL"}}
            env.update(PYTHONUNBUFFERED="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
            try:
                with (folder / "worker.log").open("ab") as log:
                    process = subprocess.Popen([sys.executable, "-m", "control.incident_worker", "--data", str(self.store.path.resolve()), "--id", iid],
                                               cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                job["pid"] = process.pid
                job["process_identity"] = _process_identity(process.pid)
                if not job["process_identity"]:
                    raise RuntimeError("Incident worker exited during launch")
            except (OSError, RuntimeError) as exc:
                job.update(status="failed", error="Incident launch failed: " + str(exc))
                job["attempts"].append({"status": "launch_failed", "started_at": now(), "error": str(exc)})
            _write(folder / "job.json", job)

    def cancel(self, iid, key):
        if not re.fullmatch(r"[a-zA-Z0-9:_-]{8,100}", key or ""):
            raise ValueError("Valid Idempotency-Key required")
        with self.locked():
            job = self.get(iid)
            flag = self.folder(iid) / "cancel.json"
            if job["status"] not in ACTIVE and not flag.exists():
                raise Conflict("Incident has no active compute to cancel")
            if flag.exists():
                if json.loads(flag.read_text())["key_sha"] != content_hash(key):
                    raise Conflict("Cancellation was already requested with another idempotency key")
            else:
                _write(flag, {"key_sha": content_hash(key), "requested_at": now()})
        return {**self.get(iid), "cancel_requested": True}

    def episode(self, iid, trial, branch):
        if branch not in {"original", "intervention"} or not 0 <= trial <= 20:
            raise ValueError("Invalid incident branch/trial")
        folder = self.folder(iid)
        job = self.get(iid)
        attempt = next((a for a in job["attempts"] if a["trial_index"] == trial and a["branch"] == branch and a.get("episode_sha")), None)
        if attempt is None:
            raise KeyError("Episode has not been recorded")
        raw = gzip.decompress((folder / f"episode-{trial}-{branch}.json.gz").read_bytes())
        if hashlib.sha256(raw).hexdigest() != attempt["episode_sha"]:
            raise ValueError("Persisted incident episode integrity mismatch")
        return json.loads(raw)

    def run(self, iid):
        folder = self.folder(iid)
        with self.locked():
            job = self.get(iid)
            if job["status"] != "queued":
                raise Conflict("Only a queued incident can execute; attempts are never overwritten")
            job.update(status="running", pid=os.getpid(), process_identity=_process_identity(os.getpid()))
            _write(folder / "job.json", job)
        config = job["config"]
        def save():
            job["updated_at"] = now()
            _write(folder / "job.json", job)
        def canceled():
            return (folder / "cancel.json").exists()
        try:
            if content_hash(config) != job["config_sha"] or config["scientific_source_lock"] != source_lock() or config["adapter_lock"] != adapter_lock() or config["runtime"] != runtime_lock():
                raise ValueError("Frozen incident source/adapter/runtime changed before execution")
            self.verify_snapshot(folder, config)
            if config.get("planner_receipt_sha") and content_hash(self.planner_review(config["planner_receipt_sha"])) != config.get("planner_review_sha"):
                raise ValueError("Planner accepted review changed before execution")
            checkpoint = validate_checkpoint(json.loads((folder / "checkpoint.json").read_text()), config["checkpoint_hash"])
            source = json.loads(gzip.decompress((folder / "source.json.gz").read_bytes()))
            if hashlib.sha256(canonical(source)).hexdigest() != config["source_artifact_sha"] or source["evidence_hash"] != config["source_evidence_hash"]:
                raise ValueError("Frozen incident source evidence changed")
            for trial, seed in enumerate(config["paired_seeds"]):
                episodes = []
                for branch in ("original", "intervention"):
                    if canceled():
                        job["status"] = "canceled"
                        save()
                        return
                    scene = original_scenario(config["source_scenario"], seed) if branch == "original" else intervention_scenario(config["source_scenario"], config["factor"], config["value"], seed)
                    attempt = {"trial_index": trial, "branch": branch, "seed": seed, "status": "running", "started_at": now(), "trace_recorded": trial == 0}
                    job["attempts"].append(attempt)
                    job["progress"]["message"] = f"Executing {'source-seed anchor' if trial == 0 else 'fresh draw ' + str(trial)} · {branch}"
                    save()
                    episode = run_episode(scene, checkpoint, trace=trial == 0, cancel_callback=canceled)
                    raw = canonical(episode)
                    (folder / f"episode-{trial}-{branch}.json.gz").write_bytes(gzip.compress(raw, mtime=0))
                    attempt.update(status=episode["status"], ended_at=now(), episode_sha=hashlib.sha256(raw).hexdigest(),
                                   evidence_hash=episode["evidence_hash"], success=episode["success"], terminal_reason=episode["terminal_reason"])
                    if episode["status"] != "completed":
                        job["status"] = "canceled" if canceled() else "failed"
                        save()
                        return
                    job["progress"]["completed"] += 1
                    save()
                    episodes.append(episode)
                validity = pair_validity(*episodes, config["source_scenario"], checkpoint, config["factor"], config["value"], seed)
                if trial == 0:
                    differences = reproduction_differences(source, episodes[0])
                    validity["source_reproduction_differences"] = differences
                    if differences:
                        raise ValueError("Exact source-seed replay differs: " + ", ".join(differences))
                    validity["source_reproduction_verified"] = True
                pair = {"trial_index": trial, "seed": seed, "kind": "source_seed_anchor" if trial == 0 else "fresh_paired_draw", "validity": validity}
                for branch, episode in zip(("original", "intervention"), episodes):
                    pair[branch] = {"episode_id": episode["episode_id"], "episode_url": f"/api/incidents/{iid}/episodes/{trial}/{branch}",
                                    "success": episode["success"], "terminal_reason": episode["terminal_reason"], "evidence_hash": episode["evidence_hash"], "trace_recorded": trial == 0}
                job["pairs"].append(pair)
                job["summary"] = diagnostic_summary(job["pairs"])
                save()
            job.update(status="completed", validity={"valid": True, "initial_scene_reset_verified": True, "all_pairs_valid": True,
                                                     "source_reproduction_verified": True, "scope": SCOPE})
            job["progress"]["message"] = "Paired MuJoCo execution complete; source anchor excluded from fresh-draw counts"
            save()
        except BaseException as exc:
            if job["attempts"] and job["attempts"][-1]["status"] == "running":
                job["attempts"][-1].update(status="failed", ended_at=now(), error=str(exc)[:1000])
            job.update(status="failed", error=str(exc)[:1000], validity={"valid": False, "state": "execution_failed"})
            save()
            raise

    def export(self, iid):
        with self.locked():
            return self._export(iid)

    def _export(self, iid):
        job = self.get(iid)
        if job["status"] in ACTIVE:
            raise Conflict("Wait for completion/cancellation before exporting retained attempts")
        folder = self.folder(iid)
        config = job["config"]
        frozen = folder / "frozen-export.json"
        if frozen.exists():
            descriptor = json.loads(frozen.read_text())
            if descriptor.get("filename") != "frozen-export.zip":
                raise ValueError("Invalid frozen incident archive name")
            raw = (folder / "frozen-export.zip").read_bytes()
            if hashlib.sha256(raw).hexdigest() != descriptor["sha256"] or len(raw) != descriptor["bytes"] or hashlib.sha256(canonical(job)).hexdigest() != descriptor["job_sha256"]:
                raise ValueError("Immutable historical incident archive/job integrity mismatch")
            return raw
        self.verify_snapshot(folder, config)
        files = {"incident.json": canonical(job), "checkpoint.json": (folder / "checkpoint.json").read_bytes(),
                 "source.json": gzip.decompress((folder / "source.json.gz").read_bytes()), "task.json": (folder / "task.json").read_bytes()}
        for attempt in job["attempts"]:
            if attempt.get("episode_sha"):
                name = f"episode-{attempt['trial_index']}-{attempt['branch']}.json"
                files["episodes/" + name] = canonical(self.episode(iid, attempt["trial_index"], attempt["branch"]))
        for relative in self.snapshot_files(config):
            files[relative] = (folder / "sources" / relative).read_bytes()
        for name in ("control/__init__.py", "LICENSE", "engine/ASSET_LICENSE.txt"):
            files[name] = (folder / "sources" / name).read_bytes()
        if (folder / "planner-receipt.json").exists():
            files["planner-receipt.json"] = (folder / "planner-receipt.json").read_bytes()
            files["planner-review.json"] = (folder / "planner-review.json").read_bytes()
            if (folder / "planner-original-receipt.json").exists():
                files["planner-original-receipt.json"] = (folder / "planner-original-receipt.json").read_bytes()
        files["requirements.txt"] = b"mujoco==3.3.7\nnumpy==2.2.6\nscipy==1.15.3\n"
        files["REPRODUCE.md"] = ("# Forge incident regression test\n\n" + LABEL + "\n\n" + SCOPE +
            "\n\nInstall requirements.txt in the bound Python 3.11 runtime, then from any working directory:\n\n"
            "    python /absolute/bundle/scripts/incident_reproduce.py --bundle /absolute/bundle --verify\n"
            "    python /absolute/bundle/scripts/incident_reproduce.py --bundle /absolute/bundle --rerun\n"
            "    python /absolute/bundle/scripts/incident_reproduce.py --bundle /absolute/bundle --rerun --checkpoint /absolute/compatible.json\n\n"
            "--rerun executes the anchored original/intervention pair. Add --all-pairs for the entire frozen schedule. Alternate checkpoints are data-only JSON, validated against the exact task/controller/observations/actions/normalization/tensor schema. Their outcomes form a new diagnostic, never expected to reproduce the original policy. No credentials, server or network are used. --output writes a JSON report. All attempts are retained. The camera is an inspection view; this policy receives privileged state. OS/architecture are reported separately from pinned dependency compatibility.\n").encode()
        files["checksums.json"] = canonical({name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())})
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, raw in sorted(files.items()):
                archive.writestr(name, raw)
        raw = buffer.getvalue()
        (folder / "frozen-export.zip").write_bytes(raw)
        _write(frozen, {"filename": "frozen-export.zip", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "job_sha256": hashlib.sha256(canonical(job)).hexdigest()})
        return raw
