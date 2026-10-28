"""Real subprocess/physics checks for local lifecycle and accepted evidence."""
import json
import time

import pytest

import engine
from control.lineage import source_lock
from control.protocol import PROTOCOL_SHA, development_manifest
from control.store import Store, FenceLost, canonical
from control.supervisor import Supervisor


def until(store, cid, predicate, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = store.get(cid)
        if predicate(state):
            return state
        if state["status"] == "failed":
            raise AssertionError(state.get("error"))
        time.sleep(.04)
    raise AssertionError(f"Lifecycle condition timed out: {store.get(cid, detail=False)}")


def test_real_worker_pause_resume_cancel_and_restart(tmp_path):
    base = engine.bootstrap_base(tmp_path / "base", n_demos=12, seed=17)
    store = Store(tmp_path)
    index = {
        "checkpoint_sha": store.artifact(base["checkpoint"]),
        "checkpoint_hash": base["checkpoint"]["checkpoint_hash"],
        "manifest_sha": store.artifact(base["manifest"]),
        "demo_shas": [store.artifact(demo) for demo in base["demos"]],
    }
    (tmp_path / "base" / "index.json").write_bytes(canonical(index))
    config = {
        "seed": 427, "search_budget": 12, "live_models": False,
        "task_sha": engine.TASK_SPEC_HASH, "protocol_sha": PROTOCOL_SHA,
        "source_sha": source_lock()["sha256"],
        "base_checkpoint_sha": index["checkpoint_sha"],
        "development_manifest_sha": store.artifact(development_manifest(engine.FACTOR_SPEC, 427)),
    }
    cid, _ = store.create("Offline lifecycle qualification", config, "operations-create")
    supervisor = Supervisor(store)
    try:
        supervisor.start(cid)
        first = until(store, cid, lambda state: len(state["episodes"]) >= 1)
        accepted = {row["id"] for row in first["episodes"]}
        store.action(cid, "pause", first["generation"], "operations-pause")
        paused = until(store, cid, lambda state: state["status"] == "paused")
        supervisor.children[cid].wait(timeout=5)
        assert accepted <= {row["id"] for row in paused["episodes"]}
        assert all(row["status"] == "completed" for row in paused["episodes"])
        count = len(paused["episodes"])

        store.action(cid, "resume", paused["generation"], "operations-resume")
        supervisor.start(cid)
        resumed = until(store, cid, lambda state: len(state["episodes"]) > count)
        assert resumed["generation"] == 2
        accepted = {row["id"] for row in resumed["episodes"]}
        store.action(cid, "cancel", resumed["generation"], "operations-cancel")
        supervisor.cancel(cid)
        canceled = store.get(cid)
        assert canceled["status"] == "canceled"
        assert supervisor.children[cid].poll() is not None
        assert accepted <= {row["id"] for row in canceled["episodes"]}
        with pytest.raises(FenceLost):
            store.progress(cid, resumed["generation"], "discovery", 999, 999, "late stale write")

        count = len(canceled["episodes"])
        store.action(cid, "resume", canceled["generation"], "operations-second-resume")
        supervisor.start(cid)
        running = until(store, cid, lambda state: len(state["episodes"]) > count)
        old_info = store.launch_info(cid)
        accepted = {row["id"] for row in running["episodes"]}
        # A newly constructed supervisor has no Popen object. Recovery must find
        # the owned PID/token, fence it in SQLite and terminate the real process.
        restarted = Supervisor(store)
        restarted.recover()
        supervisor.children[cid].wait(timeout=5)
        interrupted = store.get(cid)
        assert interrupted["status"] == "interrupted"
        assert interrupted["generation"] == running["generation"] + 1
        assert not restarted._matching(old_info["pid"], old_info["worker_token"])
        assert accepted <= {row["id"] for row in interrupted["episodes"]}
        assert all(row["status"] == "completed" for row in interrupted["episodes"])
        assert not interrupted["provider_calls"]
        with pytest.raises(FenceLost):
            store.finish(cid, running["generation"], "completed", "report")
        assert {"pause", "resume", "termination_confirmed", "recovered"} <= {event["kind"] for event in interrupted["events"]}
    finally:
        supervisor.shutdown()
        for child in supervisor.children.values():
            child.wait(timeout=5)
