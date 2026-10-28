"""Registered local simulation contract. Values are SI in a right-handed z-up world."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import platform
import sys
from typing import Any

import mujoco
import numpy as np


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


FACTOR_SPEC = {
    "obstacle_height": {"nominal": 0.065, "min": 0.045, "max": 0.170, "step": 0.005, "unit": "m"},
    "friction": {"nominal": 0.65, "min": 0.16, "max": 0.80, "step": 0.04, "unit": "coefficient"},
    "payload_yaw": {"nominal": 0.0, "min": -0.18, "max": 0.18, "step": 0.03, "unit": "rad"},
    "tray_offset_y": {"nominal": 0.0, "min": -0.035, "max": 0.035, "step": 0.005, "unit": "m"},
}

CONTROLLER_REVISION = "gantry-position-phases-v1"
ASSET_REVISION = "forge-original-gantry-v1"
POLICY_SCHEMA = "forge.numpy-waypoint-mlp/v1"
TASK_SPEC = {
    "schema": "forge.task/v1",
    "task_id": "gantry-kit-transfer-v1",
    "revision": "1.0.0",
    "scope": "local_cpu_mujoco_simulation_only",
    "embodiment": "original_cartesian_3_axis_parallel_jaw_gantry",
    "asset_revision": ASSET_REVISION,
    "asset_license": "MIT; original FORGE geometry",
    "simulator": "MuJoCo 3.3.7 (Apache-2.0)",
    "controller_revision": CONTROLLER_REVISION,
    "policy_kind": "instrumented-state NumPy MLP waypoint regression above fixed phase controller",
    "units": {"length": "m", "mass": "kg", "time": "s", "angle": "rad", "force": "N", "torque": "N m"},
    "frames": {"world": "right-handed; x/y table plane; +z up", "quaternion": "WXYZ", "velocities": "world linear and angular"},
    "physics": {"timestep": 0.002, "integrator": "implicitfast", "solver_iterations": 80, "cone": "elliptic", "gravity": [0, 0, -9.81]},
    "duration": 9.4,
    "payload": {"half_extents": [0.024, 0.018, 0.025], "mass": 0.06, "initial_center": [-0.20, -0.05, 0.025]},
    "protected": {"half_extents_xy": [0.025, 0.042], "mass": 0.40, "initial_center_xy": [0, 0]},
    "target": {"center_xy": [0.20, 0.05], "half_extents_xy": [0.077, 0.065], "floor_z": 0.008, "top_z": 0.080},
    "success_predicate": "all oriented payload corners inside tray; fingers released; payload settled for final 2 s; payload lifted; protected object never moved/tilted beyond thresholds; no forbidden contact",
    "thresholds": {
        "containment_tolerance": 0.0005,
        "released_opening_min": 0.075,
        "stable_linear_velocity_max": 0.015,
        "stable_angular_velocity_max": 0.15,
        "stable_duration_min": 2.0,
        "payload_center_lift_min": 0.070,
        "protected_displacement_max": 0.003,
        "protected_angle_max": 0.050,
        "forbidden_contact_force_min": 0.10,
    },
    "permitted_contacts": ["payload-table", "payload-fingers", "payload-tray", "protected-table"],
    "forbidden_contacts": "protected object against payload, fingers, palm or tray with normal force >0.10 N at any physics step",
    "valid_reset": "all finite factors in declared envelope; payload/protected resting on table; no initial inter-object overlap; target inside gantry reach; initial free-body quaternions unit length",
    "factors": FACTOR_SPEC,
    "nuisance_distribution": {
        "generator": "numpy.random.PCG64; scenario.seed",
        "reset_xy": "independent uniform[-0.0008,+0.0008] m for payload/protected",
        "reset_yaw": "independent uniform[-0.003,+0.003] rad for payload/protected",
        "pick_sensor_xy": "independent Normal(0,0.00035) m clipped to +/-0.001 m; constant per episode",
        "height_sensor": "Normal(0,0.0003) m clipped to +/-0.0008 m",
        "friction_sensor": "Normal(0,0.006) clipped to +/-0.015",
        "actuator_gain_scale": "uniform[0.97,1.03]",
        "phase_duration_scale": "uniform[0.985,1.015]; final settling window remains 2 s",
        "meaning": "different seeds sample this distribution; repeating an identical seed establishes deterministic repeatability only",
    },
    "training_budget": {"adaptation_demonstrations": 24, "nominal_retention": 8, "corrective": 16, "adam_updates": 600, "batch_size": 24, "sampling": "24 independent draws with replacement per update; optimization seed controls bootstrap batches", "learning_rate": 0.004, "training_seeds": [101, 202, 303, 404, 505]},
    "base_distribution": {"obstacle_height": [0.045, 0.080], "friction": [0.52, 0.80], "payload_yaw": [-0.12, 0.12], "tray_offset_y": [-0.025, 0.025]},
    "finite_reduction_neighborhood": "exhaustive lower-objective single-factor registered-grid substitution including sign reversals and nonadjacent values; include nominal value explicitly even if off regular step",
    "embargoed_compositions": "obstacle_height >=0.145 AND friction <=0.28; OR abs(payload_yaw) >=0.12 AND abs(tray_offset_y) >=0.025; prohibited for development, search, training, validation, confirmation; sealed/challenge inference only",
}
TASK_SPEC_HASH = content_hash(TASK_SPEC)


def task_spec() -> dict:
    value = copy.deepcopy(TASK_SPEC)
    value["task_spec_hash"] = TASK_SPEC_HASH
    return value


def runtime_lock() -> dict:
    return {
        "schema": "forge.runtime/v1", "simulation_only": True,
        "os": platform.system(), "os_version": platform.mac_ver()[0] or platform.release(),
        "machine": platform.machine(), "python": platform.python_version(),
        "mujoco": mujoco.__version__, "numpy": np.__version__,
        "controller_revision": CONTROLLER_REVISION, "asset_revision": ASSET_REVISION,
        "task_spec_hash": TASK_SPEC_HASH, "device": "CPU", "cuda": False,
        "hardware_robot": False, "isaac": False, "groot": False,
        "policy": "original NumPy instrumented-state waypoint MLP; not NVIDIA policy weights",
    }


def normalize_scenario(scenario: dict | None = None) -> dict:
    source = copy.deepcopy(scenario or {})
    if not isinstance(source, dict):
        raise ValueError("scenario must be an object")
    supplied = source.get("parameters", {})
    if not isinstance(supplied, dict):
        raise ValueError("parameters must be an object")
    unknown = set(supplied) - set(FACTOR_SPEC)
    if unknown:
        raise ValueError(f"unknown scenario factors: {sorted(unknown)}")
    parameters = {}
    for name, factor in FACTOR_SPEC.items():
        raw = supplied.get(name, source.get(name, factor["nominal"]))
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        value = float(raw)
        if not math.isfinite(value) or not factor["min"] - 1e-9 <= value <= factor["max"] + 1e-9:
            raise ValueError(f"{name} outside [{factor['min']}, {factor['max']}]")
        parameters[name] = value
    seed = source.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be a uint32 integer")
    split = source.get("split", "development")
    if split not in {"development", "confirmation", "nominal", "sealed", "training", "validation", "challenge"}:
        raise ValueError("unsupported scenario split")
    if split not in {"sealed", "challenge"} and embargo_reason(parameters):
        raise ValueError("embargoed held-out composition: " + embargo_reason(parameters))
    result = {"split": split, "family": str(source.get("family", "registered_factors"))[:100], "seed": seed, "parameters": parameters}
    result["scenario_id"] = str(source.get("scenario_id") or "scn_" + content_hash(result)[:16])
    return result


def nominal_scenario(seed: int = 0, **kwargs) -> dict:
    return normalize_scenario({"seed": seed, "family": "nominal", "split": "nominal", **kwargs})


def embargo_reason(parameters: dict) -> str | None:
    if parameters["obstacle_height"] >= 0.145-1e-9 and parameters["friction"] <= 0.28+1e-9:
        return "tall_low_friction"
    if abs(parameters["payload_yaw"]) >= 0.12-1e-9 and abs(parameters["tray_offset_y"]) >= 0.025-1e-9:
        return "yaw_tray_composition"
    return None


def sample_nuisance(seed: int) -> dict:
    rng = np.random.default_rng(seed)
    return {
        "payload_reset_xy": rng.uniform(-0.0008, 0.0008, 2).tolist(),
        "protected_reset_xy": rng.uniform(-0.0008, 0.0008, 2).tolist(),
        "payload_reset_yaw": float(rng.uniform(-0.003, 0.003)),
        "protected_reset_yaw": float(rng.uniform(-0.003, 0.003)),
        "pick_sensor_xy": np.clip(rng.normal(0, 0.00035, 2), -0.001, 0.001).tolist(),
        "height_sensor": float(np.clip(rng.normal(0, 0.0003), -0.0008, 0.0008)),
        "friction_sensor": float(np.clip(rng.normal(0, 0.006), -0.015, 0.015)),
        "actuator_gain_scale": float(rng.uniform(0.97, 1.03)),
        "phase_duration_scale": float(rng.uniform(0.985, 1.015)),
    }
