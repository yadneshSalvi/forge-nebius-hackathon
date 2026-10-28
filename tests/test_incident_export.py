"""A small incident test works outside the checkout and rejects tampering."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import pytest
from control.incident import Incidents
from control.store import Store, canonical, digest
from engine import content_hash, expert_policy
from test_incident import incident_source


@pytest.fixture(scope="module")
def portable_incident(incident_source, tmp_path_factory):
    source, cid, eid, _, _ = incident_source
    data = tmp_path_factory.mktemp("incident-portable-data") / "data"
    shutil.copytree(source, data)
    manager = Incidents(Store(data))
    request = {"campaign_id": cid, "source_episode_id": eid, "factor": "obstacle_height", "value": .065, "nuisance_repeats": 1}
    source_entry = manager.context(cid)["sources"][0]
    episode = manager.store.read_artifact(source_entry["source_artifact_sha"])
    context = {"campaign_id": cid, "source_episode_id": eid, "source_artifact_sha": source_entry["source_artifact_sha"],
               "source_evidence_hash": episode["evidence_hash"], "checkpoint_sha": manager.store.get(cid, detail=False)["config"]["base_checkpoint_sha"],
               "task_spec_hash": episode["task_spec_hash"], "description": "Fixture physics → instrumented observations"}
    final_content = '{"fixture_hypothesis":"height → compare outcomes"}'
    original = {"schema": "forge.intervention-plan/v1", "status": "rejected", **context, "context": context, "context_sha": digest(context),
                "provider": "fixture", "model": "fixture-only", "returned_model": "fixture-only", "request_id": "fixture-call-one", "request_hash": digest(context),
                "final_content": final_content, "final_content_sha256": hashlib.sha256(final_content.encode()).hexdigest(), "estimated_cost_usd": .001, "usage": {"total_tokens": 10}}
    original_sha = manager.store.artifact(original)
    plan = {**original, "status": "validated", "factor": request["factor"], "value": request["value"], "inference_performed": False,
            "count_as_provider_call": False, "additional_estimated_cost_usd": 0,
            "derivation": {"original_receipt_sha": original_sha, "original_response_sha256": original["final_content_sha256"], "original_request_id": original["request_id"]}}
    plan.pop("estimated_cost_usd")
    plan.pop("usage")
    plan_sha = manager.store.artifact(plan)
    reviews = manager.store.path / "intervention-plan-reviews"
    reviews.mkdir()
    (reviews / f"{plan_sha}.json").write_bytes(canonical({"schema": "forge.intervention-plan-review/v1", "receipt_sha": plan_sha,
        "decision": "accept", "reason": "Fixture-only local validator review; no actual provider call or human study", "reviewed_at": "2026-10-28T12:00:00+00:00"}))
    request["planner_receipt_sha"] = plan_sha
    job, _ = manager.create(request, "portable-incident-key")
    manager.run(job["id"])
    done = manager.get(job["id"])
    assert done["status"] == "completed" and done["summary"]["fresh_pairs"] == 1
    assert len(done["pairs"]) == 2 and len(done["attempts"]) == 4
    assert done["pairs"][0]["original"]["success"] is False
    assert done["pairs"][0]["intervention"]["success"] is True
    destination = tmp_path_factory.mktemp("portable-incident") / "bundle"
    destination.mkdir()
    raw = manager.export(job["id"])
    assert len(raw) < 5_000_000
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        archive.extractall(destination)
    shutil.rmtree(data)
    return destination


@pytest.fixture
def bundle(portable_incident, tmp_path):
    destination = tmp_path / "bundle"
    shutil.copytree(portable_incident, destination)
    return destination


def invoke(bundle, *args):
    env = {k: v for k, v in os.environ.items() if not any(token in k.upper() for token in ("API_KEY", "TOKEN", "SECRET", "PYTHONPATH"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(bundle / "scripts/incident_reproduce.py"), "--bundle", str(bundle), *args],
                          cwd=bundle.parent, env=env, capture_output=True, text=True, timeout=60)


def reseal(bundle, relative):
    checks = json.loads((bundle / "checksums.json").read_text())
    checks[relative] = hashlib.sha256((bundle / relative).read_bytes()).hexdigest()
    (bundle / "checksums.json").write_bytes(canonical(checks))


def test_clean_standalone_verify_and_fresh_physics(bundle):
    result = invoke(bundle, "--verify", "--rerun", "--all-pairs")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["valid"] and report["dense_oracle_audits"] == 3
    assert report["runtime_dependencies_match"] and len(report["reruns"]) == 2
    assert all(row[b]["matches_recorded"] for row in report["reruns"] for b in ("original", "intervention"))
    assert not list(bundle.rglob("*.pyc"))


def test_compatible_alternate_policy_is_a_new_diagnostic(bundle, tmp_path):
    alternate = tmp_path / "alternate.json"
    alternate.write_bytes(canonical(expert_policy()))
    result = invoke(bundle, "--rerun", "--checkpoint", str(alternate))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["alternate_checkpoint"]["supplied"]
    assert report["reruns"][0]["original"]["matches_recorded"] is None
    assert report["reruns"][0]["original"]["success"] is True
    incompatible = expert_policy()
    incompatible["task_spec_hash"] = "wrong-task"
    incompatible.pop("checkpoint_hash")
    incompatible["checkpoint_hash"] = content_hash(incompatible)
    alternate.write_bytes(canonical(incompatible))
    rejected = invoke(bundle, "--rerun", "--checkpoint", str(alternate))
    assert rejected.returncode == 1 and "unrecognized expert" in rejected.stderr


@pytest.mark.parametrize("kind", ["source", "unchecked_python", "unchecked_pyc", "manifested_python", "manifested_pyc", "symlink", "path_traversal", "numeric_outcome", "paired_summary", "schedule", "original_receipt"])
def test_bundle_tampering_rejected(bundle, kind):
    if kind == "source":
        path = bundle / "engine/spec.py"
        path.write_text(path.read_text() + "\nraise RuntimeError('must not execute')\n")
        reseal(bundle, "engine/spec.py")
    elif kind == "unchecked_python":
        (bundle / "engine/injected.py").write_text("raise RuntimeError('unchecked')")
    elif kind == "unchecked_pyc":
        path = bundle / "engine/__pycache__/spec.cpython-311.pyc"
        path.parent.mkdir()
        path.write_bytes(b"unchecked cache")
    elif kind in {"manifested_python", "manifested_pyc"}:
        name = "numpy.py" if kind == "manifested_python" else "engine/injected.pyc"
        (bundle / name).write_bytes(b"raise RuntimeError('must not execute')")
        checks = json.loads((bundle / "checksums.json").read_text())
        checks[name] = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        (bundle / "checksums.json").write_bytes(canonical(checks))
    elif kind == "symlink":
        (bundle / "extra").symlink_to(bundle / "source.json")
    elif kind == "path_traversal":
        checks = json.loads((bundle / "checksums.json").read_text())
        checks["../outside"] = "0" * 64
        (bundle / "checksums.json").write_bytes(canonical(checks))
    elif kind == "numeric_outcome":
        path = bundle / "episodes/episode-0-original.json"
        episode = json.loads(path.read_text())
        episode["success"] = 0
        from engine.simulator import episode_evidence_hash
        episode["evidence_hash"] = episode_evidence_hash(episode)
        path.write_bytes(canonical(episode))
        reseal(bundle, "episodes/episode-0-original.json")
        job = json.loads((bundle / "incident.json").read_text())
        job["attempts"][0].update(episode_sha=hashlib.sha256(path.read_bytes()).hexdigest(), evidence_hash=episode["evidence_hash"], success=0)
        (bundle / "incident.json").write_bytes(canonical(job))
        reseal(bundle, "incident.json")
    elif kind == "original_receipt":
        path = bundle / "planner-original-receipt.json"
        receipt = json.loads(path.read_text())
        receipt["estimated_cost_usd"] = 0
        path.write_bytes(canonical(receipt))
        reseal(bundle, "planner-original-receipt.json")
    else:
        job = json.loads((bundle / "incident.json").read_text())
        if kind == "paired_summary":
            job["pairs"][0]["original"]["success"] = True
        else:
            job["config"]["paired_seeds"][1] = job["config"]["paired_seeds"][0]
            job["config_sha"] = content_hash(job["config"])
        (bundle / "incident.json").write_bytes(canonical(job))
        reseal(bundle, "incident.json")
    result = invoke(bundle, "--verify")
    assert result.returncode == 1
    assert "must not execute" not in result.stderr


def test_verification_works_below_legitimate_symlinked_parent(bundle, tmp_path):
    parent = tmp_path / "linked-parent"
    parent.symlink_to(bundle.parent, target_is_directory=True)
    result = invoke(parent / "bundle", "--verify")
    assert result.returncode == 0, result.stderr
