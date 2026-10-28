"""Controlled physics, immutable source binding, and bounded job lifecycle."""
import copy
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import gzip
import io
import json
import os
import shutil
import time
import threading
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from engine import bootstrap_base, normalize_scenario, run_episode
from engine.simulator import episode_evidence_hash
from control import incident, main
from control.incident import Incidents, _process_identity
from control.incident_validation import episode_validity, intervention_scenario, pair_validity
from control.lineage import source_lock
from control.store import Store, Conflict, canonical
from engine import content_hash


@pytest.fixture(scope="module")
def incident_source(tmp_path_factory):
    path = tmp_path_factory.mktemp("incident-source")
    base = bootstrap_base(path / "test-base", n_demos=12, seed=17)["checkpoint"]
    store = Store(path)
    checkpoint_sha = store.artifact(base)
    config = {"task_sha": main.task_spec()["task_spec_hash"], "source_sha": source_lock()["sha256"], "base_checkpoint_sha": checkpoint_sha, "search_budget": 12, "seed": 17}
    cid, _ = store.create("Incident fixture", config, "incident-fixture")
    info = store.launch_info(cid)
    store.claim(cid, 1, info["worker_token"], 123)
    scenario = normalize_scenario({"seed": 2, "parameters": {"obstacle_height": .17}})
    source = run_episode(scenario, base, trace=True)
    assert source["success"] is False
    eid = cid + "-source"
    store.save_episode(cid, 1, "source", source, {"id": eid, "success": False})
    store.finish(cid, 1, "completed", "report", {"counterexample": {"minimized_episode_id": eid, "source_episode_id": eid}, "report": {}})
    return path, cid, eid, base, source


@pytest.fixture
def local_incidents(incident_source, tmp_path):
    path, cid, eid, base, source = incident_source
    destination = tmp_path / "data"
    shutil.copytree(path, destination)
    manager = Incidents(Store(destination))
    request = {"campaign_id": cid, "source_episode_id": eid, "factor": "obstacle_height", "value": .065, "nuisance_repeats": 1}
    return manager, request, base, source


def test_exact_source_context_and_strict_creation(local_incidents):
    manager, request, base, source = local_incidents
    before = manager.store.get(request["campaign_id"])
    context = manager.context(request["campaign_id"])
    assert context["sources"][0]["source_episode_id"] == request["source_episode_id"]
    for change in ({"factor": "camera"}, {"value": .17}, {"value": .2}, {"value": True}, {"source_episode_id": "unrelated"}, {"nuisance_repeats": 21}, {"nuisance_repeats": True}, {"parameters": {}}):
        with pytest.raises((ValueError, KeyError)):
            manager.create({**request, **change}, "invalid-incident")
    job, created = manager.create(request, "exact-source-key")
    assert created and job["config"]["source_scenario"] == source["scenario"]
    assert len(job["config"]["paired_seeds"]) == 2
    assert manager.create(request, "exact-source-key")[1] is False
    with pytest.raises(Conflict):
        manager.create({**request, "value": .07}, "exact-source-key")
    with pytest.raises(Conflict):
        manager.create(request, "another-job-key")
    assert manager.store.get(request["campaign_id"]) == before


@pytest.mark.parametrize("factor,value", [("obstacle_height", .065), ("friction", .7), ("payload_yaw", .03), ("tray_offset_y", .005)])
def test_all_four_axes_preserve_nuisance_and_unrelated_reset(local_incidents, factor, value):
    manager, request, checkpoint, source = local_incidents
    original = run_episode(source["scenario"], checkpoint, trace=False)
    right = intervention_scenario(source["scenario"], factor, value)
    intervention = run_episode(right, checkpoint, trace=False)
    result = pair_validity(original, intervention, source["scenario"], checkpoint, factor, value, source["scenario"]["seed"])
    assert result["valid"] and result["nuisance_equal"]
    assert [k for k in right["parameters"] if right["parameters"][k] != source["scenario"]["parameters"][k]] == [factor]
    if factor == "obstacle_height":
        assert result["changed_initial_qpos_indices"] == [9]
    if factor in {"friction", "tray_offset_y"}:
        assert result["initial_state_identical"]


@pytest.mark.parametrize("mutation", ["numeric_success", "action", "policy_id", "oracle", "initial_state", "nuisance"])
def test_rehashed_internal_contradictions_rejected(local_incidents, mutation):
    _, _, checkpoint, source = local_incidents
    episode = copy.deepcopy(source)
    if mutation == "numeric_success":
        episode["success"] = 0
    elif mutation == "action":
        episode["policy_action"][0] += .01
    elif mutation == "policy_id":
        episode["policy"]["policy_id"] = "wrong-policy"
    elif mutation == "oracle":
        episode["oracle"]["terminal_reason"] = "success"
    elif mutation == "initial_state":
        episode["trace"]["frames"][0]["qpos"][0] += .001
    else:
        episode["nuisance"]["actuator_gain_scale"] += .001
    episode["evidence_hash"] = episode_evidence_hash(episode)
    with pytest.raises(ValueError):
        episode_validity(episode, source["scenario"], checkpoint)


def test_fresh_schedule_and_persisted_launch_failure(local_incidents, monkeypatch):
    manager, request, _, _ = local_incidents
    first, _ = manager.create(request, "launch-failure-one")
    def failed(*args, **kwargs):
        raise OSError("intentional launch failure")
    monkeypatch.setattr(incident.subprocess, "Popen", failed)
    manager.launch(first["id"])
    failed_job = manager.get(first["id"])
    assert failed_job["status"] == "failed" and failed_job["attempts"][0]["status"] == "launch_failed"
    second, _ = manager.create(request, "launch-failure-two")
    assert first["config"]["paired_seeds"][0] == second["config"]["paired_seeds"][0]
    assert set(first["config"]["paired_seeds"][1:]).isdisjoint(second["config"]["paired_seeds"][1:])


def test_orphaned_and_unrelated_pid_do_not_block(local_incidents):
    manager, request, _, _ = local_incidents
    job, _ = manager.create(request, "orphan-launch-key")
    path = manager.folder(job["id"]) / "job.json"
    job["created_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=31)).isoformat()
    path.write_bytes(canonical(job))
    assert manager.get(job["id"])["status"] == "failed"
    job["pid"] = os.getpid()
    job["process_identity"] = {**_process_identity(os.getpid()), "command": "unrelated"}
    path.write_bytes(canonical(job))
    assert manager.get(job["id"])["status"] == "failed"
    assert manager.create(request, "new-owned-job-key")[1]


def test_real_cancellation_retains_interrupted_physics(local_incidents, monkeypatch):
    manager, request, _, _ = local_incidents
    job, _ = manager.create(request, "cancel-physics-key")
    actual = incident.run_episode
    def interrupted(scene, checkpoint, trace, cancel_callback):
        calls = 0
        def trigger():
            nonlocal calls
            calls += 1
            if calls == 4:
                manager.cancel(job["id"], "cancel-physics-action")
            return cancel_callback()
        return actual(scene, checkpoint, trace=trace, cancel_callback=trigger)
    monkeypatch.setattr(incident, "run_episode", interrupted)
    manager.run(job["id"])
    result = manager.get(job["id"])
    assert result["status"] == "canceled" and result["pairs"] == []
    assert result["attempts"][0]["status"] == "interrupted"
    episode = manager.episode(job["id"], 0, "original")
    assert episode["success"] is None and 0 < episode["metrics"]["physics_steps"] < 4700
    manager.cancel(job["id"], "cancel-physics-action")


def test_gets_and_invalid_browser_requests_never_execute(local_incidents, monkeypatch):
    manager, request, _, _ = local_incidents
    monkeypatch.setattr(main, "store", manager.store)
    launches = []
    monkeypatch.setattr(Incidents, "launch", lambda self, iid: launches.append(iid))
    client = TestClient(main.app)
    assert client.get("/api/incidents").json() == []
    assert client.get("/api/incidents/context", params={"campaign_id": request["campaign_id"]}).status_code == 200
    assert client.post("/api/incidents", json=request).status_code == 400
    assert client.post("/api/incidents", json=request, headers={"Idempotency-Key": "foreign-origin-key", "Origin": "https://elsewhere.example"}).status_code == 403
    assert client.post("/api/incidents", content="{}", headers={"Content-Type": "text/plain", "Idempotency-Key": "wrong-json-type"}).status_code == 415
    assert client.post("/api/incidents", json={**request, "checkpoint": {}}, headers={"Idempotency-Key": "unknown-field-key"}).status_code == 422
    assert launches == []
    response = client.post("/api/incidents", json=request, headers={"Idempotency-Key": "accepted-api-key"})
    assert response.status_code == 201
    iid = response.json()["id"]
    assert client.get(f"/api/incidents/{iid}").json()["status"] == "queued"
    assert client.get(f"/api/incidents/{iid}/episodes/0/original").status_code == 404
    assert client.get(f"/api/incidents/{iid}/export").status_code == 409
    client.post("/api/incidents", json=request, headers={"Idempotency-Key": "accepted-api-key"})
    assert launches == [iid]


def test_planner_receipt_binds_exact_source_and_context(local_incidents):
    manager, request, _, source = local_incidents
    parent = manager.store.get(request["campaign_id"], detail=False)
    artifact = manager.context(request["campaign_id"])["sources"][0]["source_artifact_sha"]
    context = {"campaign_id": request["campaign_id"], "source_episode_id": request["source_episode_id"],
               "source_artifact_sha": artifact, "source_evidence_hash": source["evidence_hash"],
               "checkpoint_sha": parent["config"]["base_checkpoint_sha"], "task_spec_hash": source["task_spec_hash"]}
    receipt = {"schema": "forge.intervention-plan/v1", "status": "validated", **context,
               "factor": request["factor"], "value": request["value"], "context": context, "context_sha": content_hash(context)}
    for change in ({"checkpoint_sha": "0" * 64}, {"source_evidence_hash": "0" * 64}, {"value": .07}, {"status": "rejected"}, {"context_sha": "0" * 64}):
        sha = manager.store.artifact({**receipt, **change})
        with pytest.raises(ValueError, match="Planner"):
            manager.create({**request, "planner_receipt_sha": sha}, "wrong-planner-receipt")
    sha = manager.store.artifact(receipt)
    with pytest.raises(ValueError, match="accepted review"):
        manager.create({**request, "planner_receipt_sha": sha}, "unreviewed-planner-key")
    review_folder = manager.store.path / "intervention-plan-reviews"
    review_folder.mkdir()
    review_path = review_folder / f"{sha}.json"
    review = {"schema": "forge.intervention-plan-review/v1", "receipt_sha": sha, "decision": "reject", "reason": "Unsupported mechanism", "reviewed_at": "2026-10-28T12:00:00+00:00"}
    review_path.write_bytes(canonical(review))
    with pytest.raises(ValueError, match="review rejects"):
        manager.create({**request, "planner_receipt_sha": sha}, "rejected-planner-key")
    review["decision"] = "accept"
    review["reason"] = "Fixture mechanism checked against exact input contract"
    review_path.write_bytes(canonical(review))
    job, _ = manager.create({**request, "planner_receipt_sha": sha}, "accepted-planner-receipt")
    assert job["config"]["planner_receipt_sha"] == sha
    review["decision"] = "reject"
    review_path.write_bytes(canonical(review))
    with pytest.raises(ValueError, match="review rejects"):
        manager.run(job["id"])
    assert manager.get(job["id"])["status"] == "failed" and not manager.get(job["id"])["attempts"]


def test_source_change_fails_before_physics_and_no_retry(local_incidents, monkeypatch):
    manager, request, _, _ = local_incidents
    job, _ = manager.create(request, "source-change-key")
    monkeypatch.setattr(incident, "source_lock", lambda: {"files": {}, "sha256": "changed"})
    monkeypatch.setattr(incident, "run_episode", lambda *a, **kw: pytest.fail("Physics must not execute after source change"))
    with pytest.raises(ValueError, match="changed"):
        manager.run(job["id"])
    assert manager.get(job["id"])["status"] == "failed" and manager.get(job["id"])["attempts"] == []
    with pytest.raises(Conflict):
        manager.run(job["id"])


def test_single_fresh_rescue_requires_abstention():
    from control.incident_validation import diagnostic_summary
    pairs = [{"trial_index": i, "validity": {"valid": True}, "original": {"success": False}, "intervention": {"success": True}} for i in range(2)]
    summary = diagnostic_summary(pairs)
    assert summary["anchor_pairs"] == 1 and summary["fresh_pairs"] == 1
    assert summary["assessment"] == "inconclusive" and summary["paired_effect"]["delta_interval"][0] < 0


def test_alternate_checkpoint_rejects_extra_fields_and_boolean_tensors(local_incidents):
    from control.incident_validation import compatible_checkpoint
    _, _, checkpoint, _ = local_incidents
    assert compatible_checkpoint(checkpoint)["checkpoint_hash"] == checkpoint["checkpoint_hash"]
    for alteration in ("extra", "boolean_tensor", "float_architecture"):
        value = copy.deepcopy(checkpoint)
        if alteration == "extra":
            value["executable"] = "arbitrary code is not an accepted policy field"
        elif alteration == "boolean_tensor":
            value["weights"]["b1"][0] = True
        else:
            value["architecture"][0] = 8.0
        with pytest.raises(ValueError, match="Alternate"):
            compatible_checkpoint(value)


def test_isolated_worker_executes_real_pair_without_parent_poll_compute(local_incidents):
    manager, request, _, _ = local_incidents
    job, _ = manager.create(request, "isolated-physics-worker")
    manager.launch(job["id"])
    launched = manager.get(job["id"])
    assert launched["pid"] != os.getpid() and launched["process_identity"]["pgid"] == launched["pid"]
    assert "control.incident_worker" in launched["process_identity"]["command"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = manager.get(job["id"])
        if result["status"] not in {"queued", "running"}:
            break
        time.sleep(.05)
    assert result["status"] == "completed", result
    assert result["validity"]["source_reproduction_verified"]
    assert len(result["attempts"]) == 4 and result["summary"]["fresh_pairs"] == 1


def test_snapshot_exports_survive_later_adapter_changes(local_incidents, monkeypatch):
    manager, request, _, _ = local_incidents
    job, _ = manager.create(request, "source-snapshot-export")
    manager.run(job["id"])
    monkeypatch.setattr(incident, "adapter_lock", lambda: {"files": {}, "sha256": "later-adapter"})
    first = manager.export(job["id"])
    assert manager.export(job["id"]) == first
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        config = json.loads(archive.read("incident.json"))["config"]
        assert config["adapter_lock"] == job["config"]["adapter_lock"]
        for name, sha in config["adapter_lock"]["files"].items():
            import hashlib
            assert hashlib.sha256(archive.read(name)).hexdigest() == sha
    path = manager.folder(job["id"]) / "frozen-export.zip"
    path.write_bytes(b"corrupted archive")
    with pytest.raises(ValueError, match="archive/job integrity"):
        manager.export(job["id"])


def test_snapshot_corruption_fails_before_physics(local_incidents, monkeypatch):
    manager, request, _, _ = local_incidents
    job, _ = manager.create(request, "source-snapshot-tamper")
    snapshot = manager.folder(job["id"]) / "sources/control/incident_validation.py"
    snapshot.write_text(snapshot.read_text() + "\n# tampered snapshot\n")
    monkeypatch.setattr(incident, "run_episode", lambda *a, **kw: pytest.fail("Physics must not execute from corrupt source snapshot"))
    with pytest.raises(ValueError, match="snapshot mismatch"):
        manager.run(job["id"])
    assert manager.get(job["id"])["status"] == "failed" and not manager.get(job["id"])["attempts"]


def test_concurrent_first_exports_share_one_immutable_archive(local_incidents, monkeypatch):
    manager, request, _, _ = local_incidents
    job, _ = manager.create(request, "concurrent-export-key")
    manager.cancel(job["id"], "cancel-before-export")
    manager.run(job["id"])  # cancellation checked before any new physics
    assert manager.get(job["id"])["status"] == "canceled"
    assert manager.get(job["id"])["attempts"] == []
    original = Incidents._export
    counter_lock = threading.Lock()
    active, maximum = 0, 0
    def observed(self, iid):
        nonlocal active, maximum
        with counter_lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(.05)
            return original(self, iid)
        finally:
            with counter_lock:
                active -= 1
    monkeypatch.setattr(Incidents, "_export", observed)
    other = Incidents(Store(manager.store.path))
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(manager.export, job["id"])
        b = executor.submit(other.export, job["id"])
        first, second = a.result(), b.result()
    assert maximum == 1 and first == second == manager.export(job["id"])
