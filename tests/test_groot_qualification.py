"""Contract tests use synthetic arrays, never claim GR00T execution."""
import json
import sys
from types import SimpleNamespace
import numpy as np
import pytest
from integrations.groot import contract as groot


def observation():
    spec=groot.load_contract()["modality"]
    value={k:np.zeros((1,1,256,256,3),dtype=np.uint8) for k in spec["video_keys"]}
    value.update({k:np.zeros((1,1,n),dtype=np.float32) for k,n in zip(spec["state_keys"],spec["state_dimensions"])})
    value[spec["language_key"]]=["Unit test; no model call"]
    return value


def actions():
    return {k:np.zeros((1,16,1),dtype=np.float32) for k in groot.load_contract()["modality"]["action_keys"]}


def test_pins_roster_and_distinct_model_action_horizons():
    c=groot.load_contract()
    assert c["checkpoint"]["repository"]=="nvidia/GR00T-N1.7-LIBERO"
    assert c["checkpoint"]["subdirectory"]=="libero_10"
    assert c["modality"]["action_horizon"]==16
    assert c["modality"]["model_max_action_horizon"]==40
    assert c["modality"]["executed_action_steps"]==8
    assert c["incident_selection"]["candidate_is_discovered_incident"] is False
    assert all(g["status"]=="pending" for g in c["gates"])
    assert len({s for t in c["task_roster"] for s in t["qualification_nominal_seeds"]})==200
    assert sum(x["bytes"] for x in c["checkpoint"]["files"])==6914934160


@pytest.mark.parametrize("mutate",[
    lambda o:o.update({"state.gripper":np.zeros((1,1,1),dtype=np.float32)}),
    lambda o:o.update({"video.image":np.zeros((1,256,256,3),dtype=np.uint8)}),
    lambda o:o.update({"state.x":np.full((1,1,1),np.nan,dtype=np.float32)}),
    lambda o:o.update({"state.z":np.zeros((1,1,1),dtype=np.float64)}),
    lambda o:o.update({"annotation.human.action.task_description":[""]}),
])
def test_observation_rejects_missing_time_wrong_gripper_and_nonfinite(mutate):
    value=observation();mutate(value)
    with pytest.raises(ValueError):groot.validate_observation(value)


@pytest.mark.parametrize("mutate",[
    lambda a:a.update({"action.gripper":np.zeros((1,16,2),dtype=np.float32)}),
    lambda a:a.update({"action.x":np.zeros((1,40,1),dtype=np.float32)}),
    lambda a:a.update({"action.y":np.full((1,16,1),np.inf,dtype=np.float32)}),
])
def test_action_rejects_wrong_horizon_gripper_and_nonfinite(mutate):
    value=actions();mutate(value)
    with pytest.raises(ValueError):groot.validate_action(value)


def test_valid_shapes_do_not_certify_camera_or_policy():
    assert groot.validate_observation(observation())["camera_orientation_qualified"] is False
    assert groot.validate_action(actions())["execution_horizon"]==8


def test_plan_enumerates_all_seeds_without_executing_or_downloading(tmp_path):
    plan=groot.launch_plan(tmp_path/"worker",tmp_path/"forge")
    assert plan["status"]=="not_executed"
    assert all(s["executed"] is False for s in plan["steps"])
    steps={s["name"]:s for s in plan["steps"]}
    assert "--locked" in steps["server_dependencies"]["argv"]
    assert "prepare-workspace" in steps["prepare_empty_workspace"]["argv"]
    assert "setup-simulator" in steps["simulation_dependencies"]["argv"]
    assert "groot_policy_server.py" in steps["server"]["argv"][1]
    assert steps["server"]["environment"]["HF_HUB_OFFLINE"]=="1"
    assert len([s for s in steps if s.startswith("capture_task_")])==200
    assert len([s for s in steps if s.startswith("official_nominal_comparison_")])==10
    assert not any("optim_states" in p for p in steps["download_checkpoint"]["argv"])
    assert plan["minimum_checkpoint_and_backbone_bytes"]>11_000_000_000
    assert not (tmp_path/"worker").exists()


def test_hash_verifier_detects_change_and_path_traversal(tmp_path):
    path=tmp_path/"metadata.json";path.write_text('{"units":"m"}')
    sha=groot.file_hash(path)
    assert groot.verify_files(tmp_path,[{"path":"metadata.json","sha256":sha}])["ok"]
    path.write_text('{"units":"cm"}')
    assert not groot.verify_files(tmp_path,[{"path":"metadata.json","sha256":sha}])["ok"]
    with pytest.raises(ValueError):groot.verify_files(tmp_path,[{"path":"../outside","sha256":sha}])


def test_failed_and_rehashed_missing_gate_preflight_rejected(tmp_path):
    value={"schema":"forge.groot-preflight/v1","contract_sha256":groot.digest(groot.load_contract()),"ready_for_runtime_probe":False,"checks":{"cuda":{"ok":False}}}
    value["preflight_sha256"]=groot.digest(value)
    path=tmp_path/"preflight.json";path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match="not passed"):groot.read_preflight(path)
    value["ready_for_runtime_probe"]=True;path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match="hash mismatch"):groot.read_preflight(path)


def test_missing_backbone_does_not_write_cache_ref(tmp_path):
    with pytest.raises(ValueError,match="absent or changed"):groot.pin_backbone_cache(tmp_path)
    assert not list(tmp_path.rglob("main"))


def test_setup_guard_preserves_existing_config_and_simulation(tmp_path):
    workspace=tmp_path/"worker";groot.prepare_workspace(workspace)
    source=workspace/"Isaac-GR00T";source.mkdir()
    account=tmp_path/"account";account.mkdir()
    assert groot.guard_simulator_setup(source,account_home=account)["status"]=="setup_paths_clear"
    config=account/".libero";config.mkdir();(config/"config.yaml").write_text("keep: true")
    with pytest.raises(ValueError,match="existing"):groot.guard_simulator_setup(source,account_home=account)
    assert (config/"config.yaml").read_text()=="keep: true"
    with pytest.raises(ValueError,match="empty dedicated"):groot.prepare_workspace(workspace)


@pytest.mark.parametrize("memories,expected", [([8,48],False),([16,8],True),([],False)])
def test_preflight_checks_the_actual_selected_cuda_zero(monkeypatch,memories,expected):
    cuda=SimpleNamespace(is_available=lambda:bool(memories),device_count=lambda:len(memories),
                         get_device_name=lambda i:f"unit-device-{i}",
                         get_device_properties=lambda i:SimpleNamespace(total_memory=memories[i]*2**30))
    fake=SimpleNamespace(__version__="2.9.0+cu128",version=SimpleNamespace(cuda="12.8"),cuda=cuda)
    monkeypatch.setitem(sys.modules,"torch",fake)
    monkeypatch.setattr(groot.importlib.util,"find_spec",lambda name:object() if name=="torch" else None)
    monkeypatch.setattr(groot.shutil,"which",lambda name:None)
    report=groot.preflight()
    assert report["checks"]["cuda"]["ok"] is expected
    assert report["checks"]["cuda"]["selected_device"]=="cuda:0"
    assert report["qualified"] is False
    assert report["ready_for_runtime_probe"] is False  # No real source/model/runtime gates passed.


def test_changed_forge_adapter_invalidates_otherwise_consistent_preflight(tmp_path,monkeypatch):
    required={"platform","python","source","checkpoint","backbone","cuda","offline_runtime"}
    value={"schema":"forge.groot-preflight/v1","contract_sha256":groot.digest(groot.load_contract()),
           "forge_adapter_lock":groot.adapter_lock(),"ready_for_runtime_probe":True,
           "checks":{name:{"ok":True} for name in required}}
    value["preflight_sha256"]=groot.digest(value)
    path=tmp_path/"synthetic-preflight.json";path.write_text(json.dumps(value))
    monkeypatch.setattr(groot,"adapter_lock",lambda:{"sha256":"changed","files":{}})
    with pytest.raises(ValueError,match="adapter changed"):groot.read_preflight(path)
