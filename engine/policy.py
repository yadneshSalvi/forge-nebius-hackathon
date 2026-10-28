"""Real NumPy/Adam imitation of contact-expert waypoint targets.

Instrumented state -> two learned waypoints -> fixed phase controller. This is
not a vision policy, GR00T checkpoint, or learned low-level physics controller.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from .spec import CONTROLLER_REVISION, POLICY_SCHEMA, TASK_SPEC, TASK_SPEC_HASH, canonical_json, content_hash, embargo_reason, normalize_scenario, sample_nuisance

OBSERVATION_NAMES = ["measured_obstacle_height", "estimated_friction", "payload_yaw", "tray_offset_y", "measured_pick_x", "measured_pick_y", "tray_x", "tray_y"]
OBSERVATION_CENTER = [0.08, 0.50, 0, 0, -0.20, -0.05, 0.20, 0.05]
OBSERVATION_SCALE = [0.10, 0.35, 0.20, 0.05, 0.02, 0.02, 0.02, 0.05]
ACTION_NAMES = ["palm_lift_z", "finger_close_position"]
ACTION_CENTER = [0.20, 0.021]
ACTION_SCALE = [0.10, 0.010]
WEIGHT_SHAPES = {"w1": (8, 24), "b1": (24,), "w2": (24, 16), "b2": (16,), "w3": (16, 2), "b3": (2,)}
DEFAULT_BUDGET = {"steps": 600, "batch_size": 24, "learning_rate": 0.004}


def observation(scenario: dict, nuisance: dict | None = None) -> list[float]:
    s = normalize_scenario(scenario)
    n = nuisance or sample_nuisance(s["seed"])
    p = s["parameters"]
    measured_xy = np.array([-0.20, -0.05])+n["payload_reset_xy"]+n["pick_sensor_xy"]
    return [p["obstacle_height"]+n["height_sensor"], float(np.clip(p["friction"]+n["friction_sensor"], 0.145, 0.815)), p["payload_yaw"], p["tray_offset_y"], *measured_xy.tolist(), 0.20, 0.05+p["tray_offset_y"]]


def expert_action(obs: list[float]) -> list[float]:
    lift_z = max(0.180, obs[0]+0.110)
    close = 0.0255 - (0.06*9.81*1.9)/(2*max(obs[1], 0.14)*350)
    return [float(np.clip(lift_z, 0.15, 0.32)), float(np.clip(close, 0.011, 0.0245))]


def expert_policy() -> dict:
    value = {"schema": "forge.expert/v1", "kind": "expert", "policy_id": "contact-expert-v1", "task_spec_hash": TASK_SPEC_HASH, "controller_revision": CONTROLLER_REVISION, "description": "authored state-based lift/force-margin expert; used for successful demonstration acquisition"}
    value["checkpoint_hash"] = content_hash(value)
    return value


def _seal(value: dict) -> dict:
    value = copy.deepcopy(value)
    value.pop("checkpoint_hash", None)
    value["checkpoint_hash"] = content_hash(value)
    return value


def validate_checkpoint(policy: dict, expected_hash: str | None = None) -> dict:
    if not isinstance(policy, dict):
        raise ValueError("policy checkpoint must be a JSON object")
    p = copy.deepcopy(policy)
    digest = p.pop("checkpoint_hash", None)
    actual = content_hash(p)
    if digest != actual or (expected_hash is not None and expected_hash != actual):
        raise ValueError("policy checkpoint hash mismatch")
    p["checkpoint_hash"] = digest
    if p.get("kind") == "expert":
        if p != expert_policy():
            raise ValueError("unrecognized expert revision")
        return p
    if p.get("schema") != POLICY_SCHEMA or p.get("kind") != "numpy_waypoint_mlp":
        raise ValueError("incompatible policy schema")
    if p.get("task_spec_hash") != TASK_SPEC_HASH or p.get("controller_revision") != CONTROLLER_REVISION:
        raise ValueError("incompatible task/controller revision")
    if p.get("observation_names") != OBSERVATION_NAMES or p.get("action_names") != ACTION_NAMES:
        raise ValueError("incompatible observation/action contract")
    normalization = {"observation_center": OBSERVATION_CENTER, "observation_scale": OBSERVATION_SCALE, "action_center": ACTION_CENTER, "action_scale": ACTION_SCALE}
    if p.get("normalization") != normalization:
        raise ValueError("incompatible normalization")
    if set(p.get("weights", {})) != set(WEIGHT_SHAPES):
        raise ValueError("unexpected checkpoint weight names")
    if p.get("architecture") != [8, 24, 16, 2] or p.get("training", {}).get("final_weights_hash") != content_hash(p["weights"]):
        raise ValueError("checkpoint architecture/weight receipt mismatch")
    for name, shape in WEIGHT_SHAPES.items():
        a = np.asarray(p["weights"][name], dtype=float)
        if a.shape != shape or not np.all(np.isfinite(a)) or np.max(np.abs(a)) > 100:
            raise ValueError(f"invalid checkpoint tensor {name}")
    return p


def save_policy(policy: dict, path: str | Path) -> dict:
    p = validate_checkpoint(policy)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (canonical_json(p)+"\n").encode()
    temporary = path.with_name(path.name+".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(), "checkpoint_hash": p["checkpoint_hash"], "policy_id": p["policy_id"]}


def load_policy(path: str | Path, expected_hash: str | None = None) -> dict:
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("checkpoint exceeds 2 MB")
    data = path.read_bytes()
    p = json.loads(data)
    if expected_hash is not None and expected_hash not in {hashlib.sha256(data).hexdigest(), p.get("checkpoint_hash")}:
        raise ValueError("policy file hash mismatch")
    return validate_checkpoint(p)


def _forward(x: np.ndarray, w: dict):
    # Small fixed tensors use explicit einsum to avoid Accelerate BLAS floating
    # point flag noise observed on this macOS/NumPy build, and CPU thread variance.
    a = np.tanh(np.einsum("...i,ij->...j", x, w["w1"], optimize=False)+w["b1"])
    b = np.tanh(np.einsum("...i,ij->...j", a, w["w2"], optimize=False)+w["b2"])
    return np.einsum("...i,ij->...j", b, w["w3"], optimize=False)+w["b3"], (x, a, b)


def policy_action(policy: dict, obs: list[float]) -> list[float]:
    if policy.get("kind") == "expert":
        return expert_action(obs)
    x = (np.asarray(obs)-OBSERVATION_CENTER)/OBSERVATION_SCALE
    w = {k: np.asarray(v) for k, v in policy["weights"].items()}
    y, _ = _forward(x, w)
    action = y*np.asarray(ACTION_SCALE)+ACTION_CENTER
    return np.clip(action, [0.15, 0.011], [0.32, 0.0245]).tolist()


def _initial_weights(seed: int) -> dict:
    rng = np.random.default_rng(seed)
    return {name: rng.normal(0, math.sqrt(1/shape[0]), shape) if name.startswith("w") else np.zeros(shape) for name, shape in WEIGHT_SHAPES.items()}


def _demo_payload(demo: dict) -> dict:
    return {k: demo[k] for k in ["scenario", "observation", "target", "source_episode_id", "source_episode_hash", "task_spec_hash", "expert_checkpoint_hash", "oracle"]}


def demo_from_episode(episode: dict, include_episode: bool = True) -> dict:
    if episode.get("status") != "completed" or episode.get("success") is not True:
        raise ValueError("only same-oracle successful completed episodes are demonstrations")
    if episode.get("policy", {}).get("checkpoint_hash") != expert_policy()["checkpoint_hash"]:
        raise ValueError("demonstration must originate from registered contact expert")
    if episode.get("task_spec_hash") != TASK_SPEC_HASH:
        raise ValueError("demonstration task mismatch")
    if episode["scenario"]["split"] in {"sealed", "confirmation", "validation", "challenge"} or embargo_reason(episode["scenario"]["parameters"]):
        raise ValueError("forbidden evaluation split/composition in training demonstration")
    demo = {"schema": "forge.demonstration/v1", "scenario": copy.deepcopy(episode["scenario"]), "observation": episode["policy_observation"], "target": episode["policy_action"], "source_episode_id": episode["episode_id"], "source_episode_hash": episode["evidence_hash"], "task_spec_hash": TASK_SPEC_HASH, "expert_checkpoint_hash": expert_policy()["checkpoint_hash"], "oracle": copy.deepcopy(episode["oracle"]), "success": True, "label_semantics": "expert waypoint targets executed in the recorded physical contact trajectory"}
    demo["demo_id"] = "demo_"+content_hash(_demo_payload(demo))[:20]
    if include_episode:
        demo["episode"] = copy.deepcopy(episode)
    return demo


def validate_demonstration(demo: dict):
    if demo.get("schema") != "forge.demonstration/v1" or demo.get("success") is not True:
        raise ValueError("invalid successful demonstration")
    if demo.get("demo_id") != "demo_"+content_hash(_demo_payload(demo))[:20]:
        raise ValueError("demonstration content hash mismatch")
    if demo.get("task_spec_hash") != TASK_SPEC_HASH or demo.get("expert_checkpoint_hash") != expert_policy()["checkpoint_hash"]:
        raise ValueError("incompatible demonstration lineage")
    if demo["scenario"]["split"] in {"sealed", "confirmation", "validation", "challenge"} or embargo_reason(demo["scenario"]["parameters"]):
        raise ValueError("evaluation split/composition leakage rejected")
    expected_components = {"inside_target", "released", "stable", "lifted", "protected_position", "protected_orientation", "no_forbidden_contact"}
    if demo["oracle"].get("success") is not True or set(demo["oracle"].get("components", {})) != expected_components or any(value is not True for value in demo["oracle"]["components"].values()):
        raise ValueError("demonstration did not pass the registered task oracle")
    if len(demo.get("observation", [])) != 8 or len(demo.get("target", [])) != 2 or not np.all(np.isfinite(demo["observation"]+demo["target"])):
        raise ValueError("invalid demonstration tensors")
    if "episode" not in demo:
        raise ValueError("demonstration requires its source episode")
    from .simulator import episode_evidence_hash
    episode = demo["episode"]
    if episode_evidence_hash(episode) != demo["source_episode_hash"] or episode.get("evidence_hash") != demo["source_episode_hash"]:
        raise ValueError("demonstration episode integrity mismatch")
    if episode.get("status") != "completed" or episode.get("success") is not True or episode.get("policy", {}).get("checkpoint_hash") != expert_policy()["checkpoint_hash"]:
        raise ValueError("demonstration requires a completed registered expert episode")
    bindings = {"scenario": "scenario", "observation": "policy_observation", "target": "policy_action", "oracle": "oracle", "source_episode_id": "episode_id", "task_spec_hash": "task_spec_hash"}
    if any(demo[dk] != episode.get(ek) for dk, ek in bindings.items()):
        raise ValueError("demonstration labels differ from source episode")


def train_policy(demos: list[dict], base_checkpoint: dict | None = None, seed: int = 0, budget: dict | None = None, policy_id: str | None = None) -> dict:
    if not demos:
        raise ValueError("training requires successful demonstrations")
    for d in demos:
        validate_demonstration(d)
    ids = [d["demo_id"] for d in demos]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate demonstration lineage")
    config = {**DEFAULT_BUDGET, **(budget or {})}
    steps, batch_size, lr = int(config["steps"]), int(config["batch_size"]), float(config["learning_rate"])
    if not 1 <= steps <= 10000 or not 1 <= batch_size <= 256 or not 0 < lr <= 0.05:
        raise ValueError("training budget outside bounded envelope")
    if base_checkpoint is not None:
        base = validate_checkpoint(base_checkpoint)
        if base["kind"] != "numpy_waypoint_mlp":
            raise ValueError("adaptation requires a learned base checkpoint")
        w = {k: np.asarray(v, dtype=float).copy() for k, v in base["weights"].items()}
        parent = base["checkpoint_hash"]
    else:
        w, parent = _initial_weights(seed), None
    initial_weights_hash = content_hash({k: a.tolist() for k, a in w.items()})
    x = (np.asarray([d["observation"] for d in demos])-OBSERVATION_CENTER)/OBSERVATION_SCALE
    y = (np.asarray([d["target"] for d in demos])-ACTION_CENTER)/ACTION_SCALE
    start = time.perf_counter()
    initial_prediction, _ = _forward(x, w)
    initial_loss = float(np.mean((initial_prediction-y)**2))
    losses = [{"step": 0, "mse": initial_loss}]
    rng = np.random.default_rng(seed)
    m = {k: np.zeros_like(v) for k, v in w.items()}
    v = {k: np.zeros_like(a) for k, a in w.items()}
    for step in range(1, steps+1):
        selection = rng.choice(len(demos), size=batch_size, replace=True)
        prediction, (xb, a, b) = _forward(x[selection], w)
        grad = 2*(prediction-y[selection])/(len(selection)*2)
        gradients = {"w3": np.einsum("ni,nj->ij", b, grad, optimize=False), "b3": grad.sum(0)}
        gb = np.einsum("ni,ji->nj", grad, w["w3"], optimize=False)*(1-b*b)
        gradients.update(w2=np.einsum("ni,nj->ij", a, gb, optimize=False), b2=gb.sum(0))
        ga = np.einsum("ni,ji->nj", gb, w["w2"], optimize=False)*(1-a*a)
        gradients.update(w1=np.einsum("ni,nj->ij", xb, ga, optimize=False), b1=ga.sum(0))
        for name, g in gradients.items():
            g = np.clip(g, -5, 5)
            m[name] = 0.9*m[name]+0.1*g
            v[name] = 0.999*v[name]+0.001*g*g
            w[name] -= lr*(m[name]/(1-0.9**step))/(np.sqrt(v[name]/(1-0.999**step))+1e-8)
        if step % 50 == 0 or step == steps:
            pred, _ = _forward(x, w)
            losses.append({"step": step, "mse": float(np.mean((pred-y)**2))})
    training = {"algorithm": "NumPy backpropagation and Adam; supervised waypoint imitation", "seed": seed, "steps": steps, "batch_size": batch_size, "sampling": "independent bootstrap draws with replacement at every update", "learning_rate": lr, "demonstrations": len(demos), "demo_ids": ids, "manifest_hash": content_hash([_demo_payload(d) for d in demos]), "parent_checkpoint_hash": parent, "initial_weights_hash": initial_weights_hash, "final_weights_hash": content_hash({k: a.tolist() for k, a in w.items()}), "initial_loss": initial_loss, "final_loss": losses[-1]["mse"], "loss_curve": losses, "trainable_parameters": sum(a.size for a in w.values()), "elapsed_seconds": time.perf_counter()-start, "retained_nominal": sum(d["scenario"]["family"] == "nominal" for d in demos), "successful_expert_episodes": len(demos)}
    p = {"schema": POLICY_SCHEMA, "kind": "numpy_waypoint_mlp", "policy_id": policy_id or f"waypoint-mlp-seed-{seed}", "task_spec_hash": TASK_SPEC_HASH, "controller_revision": CONTROLLER_REVISION, "observation_names": OBSERVATION_NAMES, "action_names": ACTION_NAMES, "normalization": {"observation_center": OBSERVATION_CENTER, "observation_scale": OBSERVATION_SCALE, "action_center": ACTION_CENTER, "action_scale": ACTION_SCALE}, "architecture": [8, 24, 16, 2], "activation": "tanh; linear output; bounded physical target projection", "weights": {k: a.tolist() for k, a in w.items()}, "training": training, "parent_checkpoint_hash": parent}
    return validate_checkpoint(_seal(p))


def collect_demonstration(scenario: dict, trace: bool = False, cancel_callback=None) -> dict:
    from .simulator import run_episode
    episode = run_episode(scenario, expert_policy(), trace=trace, cancel_callback=cancel_callback)
    return demo_from_episode(episode, include_episode=True)


def bootstrap_base(output_dir: str | Path, n_demos: int = 40, seed: int = 17) -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    policy_path, demos_path = output/"base-checkpoint.json", output/"base-demonstrations.json"
    if policy_path.exists() and demos_path.exists():
        checkpoint = load_policy(policy_path)
        demos = json.loads(demos_path.read_text())
        for demo in demos:
            validate_demonstration(demo)
        if checkpoint["training"]["demo_ids"] != [d["demo_id"] for d in demos]:
            raise ValueError("cached base demonstration lineage mismatch")
        return {"checkpoint": checkpoint, "demos": demos, "manifest": json.loads((output/"base-manifest.json").read_text())}
    rng = np.random.default_rng(seed)
    demos, attempts = [], []
    distribution = TASK_SPEC["base_distribution"]
    if not 1 <= n_demos <= 200:
        raise ValueError("base acquisition budget must be 1..200 demonstrations")
    from .simulator import run_episode
    for index in range(n_demos*3):
        parameters = {name: float(rng.uniform(*bounds)) for name, bounds in distribution.items()}
        scenario = normalize_scenario({"seed": seed*10000+index, "split": "training", "family": "nominal", "parameters": parameters})
        episode = run_episode(scenario, expert_policy(), trace=False)
        attempts.append({"scenario_id": scenario["scenario_id"], "episode_id": episode["episode_id"], "success": episode["success"], "terminal_reason": episode["terminal_reason"], "evidence_hash": episode["evidence_hash"]})
        with (output/"base-acquisition-attempts.jsonl").open("a") as stream:
            stream.write(canonical_json(episode)+"\n")
        if episode["success"]:
            demos.append(demo_from_episode(episode))
        if len(demos) == n_demos:
            break
    if len(demos) < n_demos:
        (output/"base-acquisition-failed.json").write_text(canonical_json({"requested": n_demos, "successful": len(demos), "attempts": attempts})+"\n")
        raise ValueError("bounded base acquisition failed; all attempts retained")
    checkpoint = train_policy(demos, None, seed=seed, budget={"steps": 1000, "batch_size": 32, "learning_rate": 0.004}, policy_id="base-waypoint-mlp-v1")
    saved = save_policy(checkpoint, policy_path)
    demos_path.write_text(canonical_json(demos)+"\n")
    manifest = {"schema": "forge.base-training/v1", "task_spec_hash": TASK_SPEC_HASH, "checkpoint": saved, "demonstrations": n_demos, "attempts": attempts, "distribution": distribution, "training": checkpoint["training"], "scope": "development base training; no held-out evaluation"}
    (output/"base-manifest.json").write_text(canonical_json(manifest)+"\n")
    return {"checkpoint": checkpoint, "demos": demos, "manifest": manifest}
