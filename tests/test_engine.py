import copy
import json
import math
from pathlib import Path

import mujoco
import numpy as np
import pytest

import engine
from engine.oracle import final_verdict, geometry_components, oriented_corners, quaternion_matrix
from engine.policy import _demo_payload, expert_action
from engine.scene import make_scene
from engine.simulator import control_schedule, controller_command


@pytest.fixture(scope="module")
def trained_base(tmp_path_factory):
    return engine.bootstrap_base(tmp_path_factory.mktemp("base"), n_demos=12, seed=17)


def test_oriented_geometry_and_quaternion_units():
    q = [math.sqrt(.5), 0, 0, math.sqrt(.5)]
    corners = oriented_corners([0, 0, 0], q, [.024, .018, .025])
    assert np.max(corners[:, 0]) == pytest.approx(.018)
    assert np.max(corners[:, 1]) == pytest.approx(.024)
    with pytest.raises(ValueError):
        quaternion_matrix([1, 1, 0, 0])
    good = geometry_components([.20, .05, .033], [1, 0, 0, 0], [0]*3, [0]*3, .095)
    assert good["inside_target"] and good["released"] and good["stationary"]
    # Center alone is inside, but one corner crosses the target wall.
    bad = geometry_components([.27, .05, .033], [1, 0, 0, 0], [0]*3, [0]*3, .095)
    assert not bad["inside_target"]


def test_oracle_requires_every_component():
    c = {"inside_target": True, "released": True}
    assert final_verdict(c, 2., .10, 0., 0., 0)["success"]
    assert not final_verdict(c, 1.99, .10, 0., 0., 0)["success"]
    assert final_verdict(c, 3., .10, .004, 0., 1)["terminal_reason"] == "protected_contact"
    assert not final_verdict(c, 3., .06, 0., 0., 0)["success"]
    assert not final_verdict(c, 3., .10, 0., .051, 0)["success"]


@pytest.mark.parametrize("factor,value", [("obstacle_height",float("nan")), ("friction",.15), ("tray_offset_y",.04), ("payload_yaw",float("inf"))])
def test_invalid_resets_rejected(factor, value):
    with pytest.raises(ValueError):
        engine.normalize_scenario({"parameters": {factor: value}})


def test_embargo_and_split_boundary():
    parameters = {"obstacle_height": .15, "friction": .24}
    for split in ["development", "training", "validation", "confirmation", "nominal"]:
        with pytest.raises(ValueError, match="embargoed"):
            engine.normalize_scenario({"split": split, "parameters": parameters})
    assert engine.normalize_scenario({"split": "sealed", "parameters": parameters})["split"] == "sealed"
    with pytest.raises(ValueError, match="embargoed"):
        engine.normalize_scenario({"parameters": {"payload_yaw": -.15, "tray_offset_y": .03}})
    with pytest.raises(ValueError):
        engine.normalize_scenario({"seed": True})


def test_action_signs_reset_and_free_objects():
    s = engine.nominal_scenario(12)
    m, d, n, xml = make_scene(s)
    assert m.neq == 0 and m.nq == 19 and m.nv == 17
    assert m.jnt_type[0] == mujoco.mjtJoint.mjJNT_FREE
    assert m.jnt_type[1] == mujoco.mjtJoint.mjJNT_FREE
    obs = engine.observation(s, n)
    schedule = control_schedule(obs, expert_action(obs))
    above, _ = controller_command(.4, schedule)
    below, _ = controller_command(1.45, schedule)
    closed, _ = controller_command(2.05, schedule)
    assert below[2] < above[2] and closed[3] < below[3]
    assert d.qpos[14] == -.20 and d.qpos[15] == -.05
    assert "equality" not in xml and "mocap" not in xml


@pytest.mark.parametrize("parameters", [{}, {"obstacle_height":.17,"friction":.35}, {"friction":.16}, {"payload_yaw":-.18}, {"tray_offset_y":.035}])
def test_real_contact_expert_passes_same_oracle(parameters):
    e = engine.run_episode(engine.normalize_scenario({"seed":100,"parameters":parameters}), "expert", trace=False)
    assert e["success"] and all(e["oracle"]["components"].values())
    assert e["metrics"]["max_payload_height"] > .10
    assert e["physics_aggregates"]["sampled_every_physics_step"]
    assert e["metrics"]["physics_steps"] == 4700
    assert e["metrics"]["final_payload_position"][0] > .15


def test_deterministic_replay_is_conditional_not_probability():
    a = engine.run_episode(engine.nominal_scenario(45), "expert", trace=False)
    b = engine.run_episode(engine.nominal_scenario(45), "expert", trace=False)
    c = engine.run_episode(engine.nominal_scenario(46), "expert", trace=False)
    assert a["evidence_hash"] == b["evidence_hash"]
    assert a["nuisance"] != c["nuisance"]
    assert a["policy_observation"] != c["policy_observation"]


def test_training_actual_weights_checkpoint_and_tamper(trained_base, tmp_path):
    p = trained_base["checkpoint"]
    assert p["training"]["final_loss"] < p["training"]["initial_loss"]*.1
    assert p["training"]["initial_weights_hash"] != p["training"]["final_weights_hash"]
    assert engine.run_episode(engine.nominal_scenario(0), p, trace=False)["success"]
    path = tmp_path/"policy.json"
    receipt = engine.save_policy(p, path)
    loaded = engine.load_policy(path, receipt["sha256"])
    assert loaded == p
    q = copy.deepcopy(p); q["weights"]["w1"][0][0] += .01
    path.write_text(json.dumps(q))
    with pytest.raises(ValueError, match="hash"):
        engine.load_policy(path)
    q = copy.deepcopy(p); q["normalization"]["action_scale"][0] = 1
    q["checkpoint_hash"] = engine.content_hash({k:v for k,v in q.items() if k!="checkpoint_hash"})
    with pytest.raises(ValueError, match="normalization"):
        engine.validate_checkpoint(q)


def test_five_training_seeds_same_parent_different_bootstrap(trained_base):
    p, demos = trained_base["checkpoint"], trained_base["demos"]
    trained = [engine.train_policy(demos,p,seed=seed,budget={"steps":40}) for seed in [101,202,303,404,505]]
    assert {a["parent_checkpoint_hash"] for a in trained} == {p["checkpoint_hash"]}
    assert len({a["training"]["initial_weights_hash"] for a in trained}) == 1
    assert len({a["training"]["final_weights_hash"] for a in trained}) == 5
    repeated = engine.train_policy(demos,p,seed=101,budget={"steps":40})
    assert repeated["weights"] == trained[0]["weights"]
    # Elapsed time is a measurement; checkpoint byte identity is not claimed.
    assert engine.policy_action(repeated, demos[0]["observation"]) == engine.policy_action(trained[0], demos[0]["observation"])


def test_demo_bindings_empty_oracle_and_leakage(trained_base):
    original = trained_base["demos"][0]
    for mutation in ["target", "oracle", "split"]:
        d = copy.deepcopy(original)
        if mutation == "target": d["target"][0] += .02
        if mutation == "oracle": d["oracle"]["components"] = {}
        if mutation == "split": d["scenario"]["split"] = "sealed"
        d["demo_id"] = "demo_"+engine.content_hash(_demo_payload(d))[:20]
        with pytest.raises(ValueError): engine.validate_demonstration(d)
    d = copy.deepcopy(original); del d["episode"]
    with pytest.raises(ValueError,match="source episode"): engine.validate_demonstration(d)
    with pytest.raises(ValueError,match="duplicate"): engine.train_policy([original,original],trained_base["checkpoint"])


def test_cancel_is_interrupted_attempt():
    calls = []
    def cancel():
        calls.append(True)
        return len(calls) >= 3
    e = engine.run_episode(engine.nominal_scenario(0),"expert",trace=True,cancel_callback=cancel)
    assert e["status"] == "interrupted" and e["success"] is None
    assert e["terminal_reason"] == "interrupted"
    assert e["metrics"]["physics_steps"] == 40
    assert len(e["trace"]["physics"]["qpos"]) == 41


def test_full_trace_geometry_and_contact_audit(trained_base):
    p = trained_base["checkpoint"]
    s = engine.normalize_scenario({"seed":2,"parameters":{"obstacle_height":.17}})
    e = engine.run_episode(s,p,trace=True)
    assert not e["success"] and e["terminal_reason"] == "protected_contact"
    assert engine.audit_episode(e)["valid"]
    assert len(e["trace"]["physics"]["qpos"]) == 4701
    assert e["trace"]["physics"]["protected_contact_points"]
    m,d,_,_ = make_scene(s,e["nuisance"])
    f=e["trace"]["frames"][105]
    d.qpos[:]=f["qpos"];d.qvel[:]=f["qvel"]
    mujoco.mj_forward(m,d)
    for name in ["payload","protected","gantry","left_finger","right_finger"]:
        i=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,name)
        assert d.xpos[i] == pytest.approx(f["bodies"][name]["position"],abs=1e-10)
    tampered=copy.deepcopy(e);tampered["metrics"]["forbidden_contact_points"]=0
    tampered["evidence_hash"]=engine.episode_evidence_hash(tampered)
    assert not engine.audit_episode(tampered)["valid"]
