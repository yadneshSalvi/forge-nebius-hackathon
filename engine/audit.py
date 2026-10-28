"""Read-only oracle reconstruction from raw states and individual contact forces."""
import numpy as np
from .oracle import final_verdict, geometry_components, quaternion_angle
from .spec import TASK_SPEC, TASK_SPEC_HASH
from .simulator import episode_evidence_hash

def audit_episode(episode):
    if episode_evidence_hash(episode) != episode.get("evidence_hash"):
        raise ValueError("episode evidence hash mismatch")
    if episode.get("task_spec_hash") != TASK_SPEC_HASH:
        raise ValueError("episode task mismatch")
    if episode.get("status") != "completed":
        raise ValueError("interrupted attempts have no task verdict to audit")
    physics = episode.get("trace", {}).get("physics")
    if not physics:
        raise ValueError("full physics trace required for reconstruction")
    q, v = np.asarray(physics["qpos"]), np.asarray(physics["qvel"])
    steps = episode["metrics"]["physics_steps"]
    if q.shape != (steps+1, 19) or v.shape != (steps+1, 17) or len(physics["control"]) != steps:
        raise ValueError("incomplete physics trace")
    if not np.all(np.isfinite(q)) or not np.all(np.isfinite(v)):
        raise ValueError("nonfinite trace")
    dt, stable = physics["timestep"], 0.
    for index in range(1, len(q)):
        c = geometry_components(q[index, :3], q[index, 3:7], v[index, :3], v[index, 3:6], q[index, 17]+q[index, 18]-.015, episode["scenario"]["parameters"]["tray_offset_y"])
        stable = stable+dt if c["inside_target"] and c["released"] and c["stationary"] else 0.
    max_height = float(np.max(q[:, 2]))
    max_displacement = float(np.max(np.linalg.norm(q[:, 7:10]-q[0, 7:10], axis=1)))
    max_angle = max(quaternion_angle(quat, q[0, 10:14]) for quat in q[:, 10:14])
    forbidden = [p for p in physics["protected_contact_points"] if p[3] > TASK_SPEC["thresholds"]["forbidden_contact_force_min"]]
    forbidden_steps = len({p[0] for p in forbidden})
    result = final_verdict(c, stable, max_height, max_displacement, max_angle, forbidden_steps)
    expected_metrics = {"forbidden_contact_steps": forbidden_steps, "forbidden_contact_points": len(forbidden), "forbidden_normal_impulse": sum(p[3]*dt for p in forbidden), "peak_forbidden_normal_force": max([p[3] for p in forbidden], default=0.), "protected_max_displacement": max_displacement, "max_payload_height": max_height, "stable_duration": stable}
    mismatches = []
    if result["components"] != episode["oracle"]["components"] or result["success"] != episode["success"]:
        mismatches.append("task_predicate")
    for key, measured in expected_metrics.items():
        tolerance = 2e-7 if key != "stable_duration" else dt+1e-9
        if abs(measured-episode["metrics"][key]) > tolerance:
            mismatches.append(key)
    return {"valid": not mismatches, "mismatches": mismatches, "recomputed_oracle": result, "recomputed_metrics": expected_metrics, "physics_states": len(q), "protected_contact_points": len(physics["protected_contact_points"])}
