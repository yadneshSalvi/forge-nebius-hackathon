"""The included add-on restores actual evidence without executing its experiment."""
import gzip
import json

import httpx
import pytest

from control.incident import Incidents
from control.intervention_planner import list_plans, provider_status
from control.store import Conflict, Store, canonical
from scripts import import_incident_recording as recording


@pytest.fixture
def recorded_parent(tmp_path):
    store = Store(tmp_path / "data")
    _, files, job, _ = recording.read_recording()
    config = job["config"]
    source = json.loads(files["source.json"])
    checkpoint = json.loads(files["checkpoint.json"])
    assert store.artifact(source) == config["source_artifact_sha"]
    assert store.artifact(checkpoint) == config["checkpoint_sha"]
    parent_config = {"source_sha": config["scientific_source_lock"]["sha256"],
                     "task_sha": config["task_spec_hash"], "base_checkpoint_sha": config["checkpoint_sha"]}
    with store.connect() as connection:
        connection.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            config["campaign_id"], "Recording import fixture", canonical(parent_config).decode(),
            "completed", "complete", 1, job["created_at"], job["created_at"], "{}", "{}", 1,
            "discover", None, None, None))
        connection.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?)", (
            config["source_episode_id"], config["campaign_id"], "fixture-source", config["source_artifact_sha"], "{}", job["created_at"]))
    return store, job


def test_import_preserves_recorded_bytes_costs_rejection_and_episode_without_calls(recorded_parent, monkeypatch):
    store, expected = recorded_parent
    def forbidden(*args, **kwargs):
        raise AssertionError("Import cannot invoke network or new physics")
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr("control.incident.run_episode", forbidden)
    monkeypatch.setattr("engine.run_episode", forbidden)
    monkeypatch.setattr("control.intervention_planner.credentials", lambda: {})
    before = store.get(expected["config"]["campaign_id"], detail=True)
    result = recording.unpack(store)
    assert result["imported"] and result["new_model_calls"] == result["new_physics_episodes"] == 0
    manager = Incidents(store)
    assert manager.get(expected["id"]) == expected
    manager.verify_snapshot(manager.folder(expected["id"]), expected["config"])
    assert manager.export(expected["id"]) == recording.ARCHIVE.read_bytes()
    episode = manager.episode(expected["id"], 20, "intervention")
    assert episode["success"] is True
    assert json.loads(gzip.decompress((manager.folder(expected["id"])/"source.json.gz").read_bytes()))["evidence_hash"] == expected["config"]["source_evidence_hash"]
    records = list_plans(store)
    assert len(records) == 5
    assert any(r["review"] and r["review"]["decision"] == "reject" for r in records)
    status = next(r for r in provider_status(store) if r["provider"] == "Nebius")
    assert status["calls"] == 2 and status["local_revalidations"] == 1
    assert status["estimated_cost_usd"] == .012082 and status["unknown_cost_calls"] == 0
    assert status["completed_incidents"] == 1
    assert store.get(expected["config"]["campaign_id"], detail=True) == before
    sizes = {str(p.relative_to(store.path)): p.read_bytes() for p in store.path.rglob("*") if p.is_file() and "sqlite" not in p.name}
    second = recording.unpack(store)
    assert not second["imported"] and second["already_present"]
    assert len(list_plans(store)) == 5
    assert all((store.path/name).read_bytes() == raw for name, raw in sizes.items())


def test_missing_or_conflicting_parent_refuses_before_restore(tmp_path, recorded_parent):
    with pytest.raises(ValueError, match="starter first"):
        recording.unpack(Store(tmp_path / "empty"))
    store, job = recorded_parent
    with store.connect() as connection:
        connection.execute("UPDATE campaigns SET config='{}'")
    with pytest.raises(Conflict, match="parent, task or checkpoint"):
        recording.unpack(store)
    assert not (store.path/"incidents"/job["id"]).exists()
    assert not list_plans(store)


def test_modified_archive_and_conflicting_receipts_cannot_overwrite_evidence(tmp_path, recorded_parent, monkeypatch):
    store, job = recorded_parent
    original = recording.ARCHIVE
    changed = tmp_path/"changed.zip"
    raw = bytearray(original.read_bytes());raw[-1] ^= 1;changed.write_bytes(raw)
    monkeypatch.setattr(recording,"ARCHIVE",changed)
    with pytest.raises(ValueError,match="checksum mismatch"):
        recording.unpack(store)
    monkeypatch.setattr(recording,"ARCHIVE",original)
    _, _, _, records = recording.read_recording()
    entry = records[0]
    folder = store.path/"intervention-plans";folder.mkdir()
    path = folder/"keep.json"
    path.write_bytes(canonical({**entry["artifact"],"receipt_sha":entry["receipt_sha"],"estimated_cost_usd":999}))
    before = path.read_bytes()
    with pytest.raises(Conflict,match="conflicts with retained"):
        recording.unpack(store)
    assert path.read_bytes() == before
    assert not (store.path/"incidents"/job["id"]).exists()


def test_existing_incomplete_incident_is_not_repaired_by_overwrite(recorded_parent):
    store, job = recorded_parent
    folder = store.path/"incidents"/job["id"];folder.mkdir(parents=True)
    (folder/"job.json").write_bytes(canonical(job))
    with pytest.raises(Conflict,match="incomplete"):
        recording.unpack(store)
    assert sorted(p.name for p in folder.iterdir()) == ["job.json"]
