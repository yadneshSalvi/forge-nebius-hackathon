"""Versioned initial-scene intervention checks; never change the frozen engine."""
from __future__ import annotations
import copy
import math
import numpy as np
from engine import FACTOR_SPEC, TASK_SPEC_HASH, content_hash, normalize_scenario
from engine.policy import observation, policy_action, validate_checkpoint
from engine.scene import make_scene, scene_description
from engine.oracle import geometry_components, final_verdict
from engine.simulator import episode_evidence_hash
from engine.spec import sample_nuisance
from .statistics import paired

LABEL = "Post-final diagnostic · initial-scene paired reset"
SCOPE = "Total scene intervention effect in the gantry simulation, including instrumented policy observations. Excluded from registered statistics, nomination and training. No mid-episode fork or perception-only claim."


def compatible_checkpoint(value):
    """Data-only alternate policy: reject extra fields and bool-valued tensors."""
    allowed = {"schema", "kind", "policy_id", "task_spec_hash", "controller_revision", "observation_names", "action_names", "normalization", "architecture", "activation", "weights", "training", "parent_checkpoint_hash", "checkpoint_hash"}
    if not isinstance(value, dict):
        raise ValueError("Alternate checkpoint must be a JSON object")
    if value.get("kind") != "expert":
        if set(value) - allowed or not isinstance(value.get("policy_id"), str) or not 1 <= len(value["policy_id"]) <= 120:
            raise ValueError("Alternate checkpoint metadata/schema is incompatible")
        def numbers(item):
            if isinstance(item, list):
                return all(numbers(v) for v in item)
            if isinstance(item, dict):
                return all(numbers(v) for v in item.values())
            return type(item) in (int, float) and math.isfinite(item)
        if not numbers(value.get("weights")) or not numbers(value.get("normalization")) or any(type(v) is not int for v in value.get("architecture", [])):
            raise ValueError("Alternate checkpoint requires finite numeric tensors and integer architecture")
    return validate_checkpoint(value)


def intervention_scenario(source, factor, value, seed=None):
    if factor not in FACTOR_SPEC:
        raise ValueError("Unsupported intervention factor")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Intervention value must be finite")
    if value == source["parameters"][factor]:
        raise ValueError("Intervention must change exactly one factor")
    parameters = copy.deepcopy(source["parameters"])
    if set(parameters) != set(FACTOR_SPEC):
        raise ValueError("Source must bind all four registered factors")
    parameters[factor] = float(value)
    return normalize_scenario({"split": source["split"], "family": source["family"],
                               "seed": source["seed"] if seed is None else seed,
                               "parameters": parameters})


def original_scenario(source, seed):
    if seed == source["seed"]:
        return copy.deepcopy(source)
    return normalize_scenario({**source, "seed": seed, "scenario_id": None})


def episode_validity(episode, scenario, policy):
    policy = validate_checkpoint(policy)
    if episode_evidence_hash(episode) != episode.get("evidence_hash"):
        raise ValueError("Episode evidence hash mismatch")
    if episode.get("scenario") != scenario or episode.get("task_spec_hash") != TASK_SPEC_HASH:
        raise ValueError("Episode scenario/task binding mismatch")
    if episode.get("policy") != {k: policy[k] for k in ("policy_id", "checkpoint_hash", "kind")}:
        raise ValueError("Episode checkpoint binding mismatch")
    if episode.get("nuisance") != sample_nuisance(scenario["seed"]):
        raise ValueError("Episode nuisance differs from exact registered RNG draw")
    model, data, nuisance, xml = make_scene(scenario)
    initial = episode["trace"]["frames"][0]
    if initial["time"] != 0 or not np.array_equal(data.qpos, initial["qpos"]) or not np.array_equal(data.qvel, initial["qvel"]):
        raise ValueError("Episode did not start from the bound initial reset")
    if episode["scene"] != scene_description(model, xml):
        raise ValueError("Episode scene asset binding mismatch")
    if episode["policy_observation"] != observation(scenario, nuisance):
        raise ValueError("Policy observation differs from bound initial scene")
    if episode["policy_action"] != policy_action(policy, observation(scenario, nuisance)):
        raise ValueError("Recorded policy action differs from bound checkpoint inference")
    if episode["status"] != "completed" or type(episode["success"]) is not bool:
        raise ValueError("Incomplete attempt has no valid task outcome")
    if type(episode["oracle"].get("success")) is not bool or episode["oracle"]["success"] != episode["success"] or episode["oracle"]["terminal_reason"] != episode["terminal_reason"]:
        raise ValueError("Episode oracle and outcome are contradictory")
    final = episode["trace"]["frames"][-1]
    q, v, metrics = final["qpos"], final["qvel"], episode["metrics"]
    components = geometry_components(q[:3], q[3:7], v[:3], v[3:6], q[17] + q[18] - .015, scenario["parameters"]["tray_offset_y"])
    verdict = final_verdict(components, metrics["stable_duration"], metrics["max_payload_height"], metrics["protected_max_displacement"], metrics["protected_max_angle"], metrics["forbidden_contact_steps"])
    if content_hash(verdict) != content_hash(episode["oracle"]):
        raise ValueError("Recorded oracle contradicts final state/aggregate predicates")
    if metrics["physics_steps"] != 4700 or abs(final["time"] - metrics["duration"]) > 1e-9:
        raise ValueError("Completed episode has inconsistent duration/physics steps")
    final_metrics = {"final_payload_position": q[:3], "final_payload_quaternion": q[3:7],
                     "final_payload_corners": components["corners"], "final_gripper_opening": q[17] + q[18] - .015,
                     "final_linear_speed": components["linear_speed"], "final_angular_speed": components["angular_speed"]}
    if any(not _same(value, metrics.get(key)) for key, value in final_metrics.items()):
        raise ValueError("Final-state metrics contradict recorded final state")
    aggregates = episode["physics_aggregates"]
    if aggregates["physics_steps"] != metrics["physics_steps"] or aggregates["forbidden_contact_steps"] != metrics["forbidden_contact_steps"]:
        raise ValueError("Physics aggregates contradict recorded metrics")
    return {"valid": True, "initial_qpos": data.qpos.tolist(), "initial_qvel": data.qvel.tolist(),
            "scene_hash": content_hash(xml), "nuisance_hash": content_hash(nuisance)}


def pair_validity(original, intervention, source, policy, factor, value, seed):
    left = original_scenario(source, seed)
    right = intervention_scenario(source, factor, value, seed)
    a, b = episode_validity(original, left, policy), episode_validity(intervention, right, policy)
    changed = [key for key in FACTOR_SPEC if left["parameters"][key] != right["parameters"][key]]
    if changed != [factor] or original["nuisance"] != intervention["nuisance"]:
        raise ValueError("Intervention is not a controlled one-factor pair")
    # Height changes protected center z=h/2; yaw changes payload quaternion.
    allowed = {"obstacle_height": {9}, "payload_yaw": {3, 4, 5, 6}, "friction": set(), "tray_offset_y": set()}[factor]
    delta = [i for i, (x, y) in enumerate(zip(a["initial_qpos"], b["initial_qpos"])) if x != y]
    if set(delta) - allowed or a["initial_qvel"] != b["initial_qvel"]:
        raise ValueError("Unrelated initial state changed between branches")
    return {"valid": True, "one_factor_only": True, "nuisance_equal": True,
            "nuisance_hash": a["nuisance_hash"], "same_checkpoint": True,
            "initial_scene_reset_verified": True, "unchanged_initial_coordinates_verified": True,
            "changed_initial_qpos_indices": delta, "initial_state_identical": not delta,
            "initial_state_note": "Height changes protected center z=h/2; yaw changes payload quaternion. Other state coordinates and all nuisance draws are identical.",
            "original_initial_state_sha": content_hash({"qpos": a["initial_qpos"], "qvel": a["initial_qvel"]}),
            "intervention_initial_state_sha": content_hash({"qpos": b["initial_qpos"], "qvel": b["initial_qvel"]}),
            "changed_parameters": {factor: {"from": left["parameters"][factor], "to": value}}}


def reproduction_differences(expected, actual):
    keys = ("scenario", "task_spec_hash", "policy", "policy_observation", "policy_action", "nuisance",
            "scene", "status", "success", "terminal_reason", "oracle", "metrics")
    return [key for key in keys if not _same(expected.get(key), actual.get(key))]


def _same(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(expected) == set(actual) and all(_same(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(_same(a, b) for a, b in zip(expected, actual))
    if type(expected) is bool or expected is None or isinstance(expected, str):
        return type(expected) is type(actual) and expected == actual
    if isinstance(expected, (float, int)):
        return type(actual) in (int, float) and math.isfinite(actual) and (actual == expected if type(expected) is int and type(actual) is int else math.isclose(expected, actual, abs_tol=1e-6, rel_tol=1e-7))
    return expected == actual


def diagnostic_summary(pairs):
    fresh = [p for p in pairs if p["trial_index"] > 0 and p["validity"]["valid"] is True]
    bound = paired([p["original"]["success"] for p in fresh], [p["intervention"]["success"] for p in fresh]) if fresh else None
    assessment = "inconclusive"
    if bound and bound["delta_interval"][0] > 0:
        assessment = "fewer_failures_under_tested_intervention"
    elif bound and bound["delta_interval"][1] < 0:
        assessment = "more_failures_under_tested_intervention"
    return {"anchor_pairs": int(any(p["trial_index"] == 0 for p in pairs)), "fresh_pairs": len(fresh),
            "original_successes": sum(p["original"]["success"] for p in fresh),
            "intervention_successes": sum(p["intervention"]["success"] for p in fresh),
            "rescues": sum(not p["original"]["success"] and p["intervention"]["success"] for p in fresh),
            "regressions": sum(p["original"]["success"] and not p["intervention"]["success"] for p in fresh),
            "paired_effect": bound, "assessment": assessment,
            "interpretation": "Paired diagnostic draws at this chosen scene; conservative 95% difference interval excludes source-seed anchor. Abstain when it overlaps zero. No release or generalization claim."}
