"""Authoritative contact physics, oracle, raw replay, and recorded-state renderer."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import time
import mujoco
import numpy as np
from .oracle import final_verdict, geometry_components, oriented_corners, quaternion_angle, quaternion_matrix
from .policy import expert_policy, observation, policy_action, validate_checkpoint
from .scene import make_scene, scene_description
from .spec import TASK_SPEC, TASK_SPEC_HASH, content_hash, normalize_scenario, runtime_lock

DT = TASK_SPEC["physics"]["timestep"]
PHASE_NAMES = ["settle", "approach", "close", "lift", "transfer", "lower", "release", "retreat", "settle_target"]

def control_schedule(obs, action, duration_scale=1.0):
    px, py, tx, ty = obs[4:8]
    lift, close = action
    points = [(0., [px, py, .18, .052]), (.45, [px, py, .18, .052]), (1.45, [px, py, .08, .052]), (2.05, [px, py, .08, close]), (3.20, [px, py, lift, close]), (5., [tx, ty, lift, close]), (6.10, [tx, ty, .095, close]), (6.70, [tx, ty, .095, .055]), (7.40, [tx, ty, .20, .055]), (9.60/duration_scale, [tx, ty, .20, .055])]
    return np.asarray([p[0]*duration_scale for p in points]), np.asarray([p[1] for p in points])

def controller_command(t, schedule):
    times, targets = schedule
    index = max(0, min(int(np.searchsorted(times, t, side="right")-1), len(times)-2))
    u = min(1., max(0., (t-times[index])/(times[index+1]-times[index])))
    u = u*u*(3-2*u)
    target = targets[index]*(1-u)+targets[index+1]*u
    return np.array([target[0], target[1], target[2]-.18, target[3], target[3]]), PHASE_NAMES[index]

def _command_trajectory(schedule, steps):
    times, targets = schedule
    t = np.arange(steps)*DT
    index = np.clip(np.searchsorted(times, t, side="right")-1, 0, len(times)-2)
    u = np.clip((t-times[index])/(times[index+1]-times[index]), 0, 1)
    u = (u*u*(3-2*u))[:, None]
    target = targets[index]*(1-u)+targets[index+1]*u
    return np.column_stack([target[:, 0], target[:, 1], target[:, 2]-.18, target[:, 3], target[:, 3]]), index

def _body_states(qpos, qvel, obstacle_height):
    gx, gy, gz, left, right = qpos[14:19]
    gv = qvel[12:15]
    bodies = {}
    for name, qi, vi, half in [("payload", 0, 0, [.024, .018, .025]), ("protected", 7, 6, [.025, .042, obstacle_height/2])]:
        position, quat = qpos[qi:qi+3], qpos[qi+3:qi+7]
        bodies[name] = {"position": position.tolist(), "quaternion": quat.tolist(), "linear_velocity": qvel[vi:vi+3].tolist(), "angular_velocity": (quaternion_matrix(quat)@qvel[vi+3:vi+6]).tolist(), "corners": oriented_corners(position, quat, half).tolist()}
    for name, position, velocity in [("gantry", [gx, gy, .18+gz], gv), ("left_finger", [gx, gy+left, .14+gz], gv+np.array([0, qvel[15], 0])), ("right_finger", [gx, gy-right, .14+gz], gv+np.array([0, -qvel[16], 0]))]:
        bodies[name] = {"position": list(position), "quaternion": [1, 0, 0, 0], "linear_velocity": velocity.tolist(), "angular_velocity": [0, 0, 0]}
    bodies["world"] = {"position": [0, 0, 0], "quaternion": [1, 0, 0, 0], "linear_velocity": [0, 0, 0], "angular_velocity": [0, 0, 0]}
    return bodies

def _frame(t, phase, qpos, qvel, ctrl, contacts, height):
    return {"time": round(float(t), 6), "phase": phase, "qpos": qpos.tolist(), "qvel": qvel.tolist(), "bodies": _body_states(qpos, qvel, height), "gripper_opening": float(qpos[17]+qpos[18]-.015), "control": ctrl.tolist(), "contacts": contacts}

def episode_evidence_hash(episode):
    return content_hash({k: v for k, v in episode.items() if k not in {"evidence_hash", "timing"}})

def run_episode(scenario, policy, trace=True, cancel_callback=None):
    scenario = normalize_scenario(scenario)
    if policy == "expert":
        policy = expert_policy()
    elif isinstance(policy, (str, Path)):
        from .policy import load_policy
        policy = load_policy(policy)
    policy = validate_checkpoint(policy)
    wall_start = time.perf_counter()
    model, data, nuisance, xml = make_scene(scenario)
    obs = observation(scenario, nuisance)
    action = policy_action(policy, obs)
    schedule = control_schedule(obs, action, nuisance["phase_duration_scale"])
    th = TASK_SPEC["thresholds"]
    geom_names = [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) for i in range(model.ngeom)]
    protected_geom, table_geom = geom_names.index("protected_geom"), geom_names.index("table")
    initial_protected_position, initial_protected_quat = data.qpos[7:10].copy(), data.qpos[10:14].copy()
    initial_qpos, initial_qvel = data.qpos.copy(), data.qvel.copy()
    frames, raw_qpos, raw_qvel, raw_control, raw_contacts, raw_protected_points = [], [], [], [], [], []
    pair_stats = defaultdict(lambda: {"contact_steps": 0, "points": 0, "normal_impulse": 0., "maximum_normal_force": 0.})
    max_lift, max_displacement, max_angle, stable_duration = .025, 0., 0., 0.
    forbidden_steps, forbidden_points, forbidden_impulse, peak_forbidden = 0, 0, 0., 0.
    first_violation, interrupted, physics_steps = None, False, 0
    force = np.zeros(6)
    nsteps = int(round(TASK_SPEC["duration"]/DT))
    commands, phases = _command_trajectory(schedule, nsteps)
    for step in range(nsteps):
        if step % 20 == 0 and cancel_callback is not None and cancel_callback():
            interrupted = True
            break
        ctrl = commands[step]
        if trace:
            q_before, v_before = data.qpos.copy(), data.qvel.copy()
            raw_qpos.append(np.round(q_before, 9).tolist())
            raw_qvel.append(np.round(v_before, 8).tolist())
            raw_control.append(np.round(ctrl, 9).tolist())
        data.ctrl[:] = ctrl
        mujoco.mj_step(model, data)
        physics_steps += 1
        groups, step_forbidden = {}, False
        contact_ids = range(data.ncon)
        if not trace:
            g1, g2 = data.contact.geom1, data.contact.geom2
            contact_ids = np.flatnonzero(((g1 == protected_geom) & (g2 != table_geom)) | ((g2 == protected_geom) & (g1 != table_geom)))
        for contact_id in contact_ids:
            c = data.contact[contact_id]
            mujoco.mj_contactForce(model, data, contact_id, force)
            normal = float(abs(force[0]))
            key = (int(c.geom1), int(c.geom2))
            if trace and protected_geom in key and table_geom not in key:
                raw_protected_points.append([step, key[0], key[1], normal, *c.pos.tolist(), float(c.dist)])
            if key not in groups:
                groups[key] = {"normal": 0., "world_force": np.zeros(3), "weighted_pos": np.zeros(3), "distance": 1., "count": 0}
            g = groups[key]
            g["normal"] += normal
            g["world_force"] += np.asarray(c.frame).reshape(3, 3).T@force[:3]
            g["weighted_pos"] += np.asarray(c.pos)*max(normal, 1e-12)
            g["distance"] = min(g["distance"], float(c.dist))
            g["count"] += 1
            if protected_geom in key and table_geom not in key and normal > th["forbidden_contact_force_min"]:
                step_forbidden = True
                forbidden_points += 1
                forbidden_impulse += normal*DT
                peak_forbidden = max(peak_forbidden, normal)
                if first_violation is None:
                    first_violation = {"step": step, "time": round(step*DT, 6), "geom1": geom_names[c.geom1], "geom2": geom_names[c.geom2], "normal_force": normal, "position": c.pos.tolist()}
        contacts_for_frame = []
        for (g1, g2), group in groups.items():
            position = group["weighted_pos"]/max(group["normal"], group["count"]*1e-12)
            names = (geom_names[g1], geom_names[g2])
            stats = pair_stats["|".join(names)]
            stats["contact_steps"] += 1
            stats["points"] += group["count"]
            stats["normal_impulse"] += group["normal"]*DT
            stats["maximum_normal_force"] = max(stats["maximum_normal_force"], group["normal"])
            if trace:
                raw_contacts.append([step, g1, g2, round(group["normal"], 8), *np.round(group["world_force"], 8).tolist(), round(group["distance"], 9), *np.round(position, 8).tolist(), group["count"]])
                contacts_for_frame.append({"geom1": names[0], "geom2": names[1], "position": position.tolist(), "normal_force": group["normal"], "world_force": group["world_force"].tolist(), "distance": group["distance"], "contact_points": group["count"]})
        forbidden_steps += int(step_forbidden)
        q, v = data.qpos, data.qvel
        max_lift = max(max_lift, float(q[2]))
        max_displacement = max(max_displacement, float(np.linalg.norm(q[7:10]-initial_protected_position)))
        max_angle = max(max_angle, quaternion_angle(q[10:14], initial_protected_quat))
        if data.time >= 5. and float(q[17]+q[18]-.015) >= th["released_opening_min"]:
            components = geometry_components(q[:3], q[3:7], v[:3], v[3:6], float(q[17]+q[18]-.015), scenario["parameters"]["tray_offset_y"])
            stable_duration = stable_duration+DT if components["inside_target"] and components["released"] and components["stationary"] else 0.
        else:
            stable_duration = 0.
        if trace and step % 20 == 0:
            frames.append(_frame(step*DT, PHASE_NAMES[phases[step]], q_before, v_before, ctrl, contacts_for_frame, scenario["parameters"]["obstacle_height"]))
        if step % 20 == 0 and (not np.all(np.isfinite(q)) or not np.all(np.isfinite(v))):
            raise RuntimeError("MuJoCo produced nonfinite state")
    q, v = data.qpos.copy(), data.qvel.copy()
    for warning in (mujoco.mjtWarning.mjWARN_BADQPOS, mujoco.mjtWarning.mjWARN_BADQVEL, mujoco.mjtWarning.mjWARN_BADQACC):
        if data.warning[int(warning)].number:
            raise RuntimeError("MuJoCo numerical-state warning; attempt requires infrastructure review")
    components = geometry_components(q[:3], q[3:7], v[:3], v[3:6], float(q[17]+q[18]-.015), scenario["parameters"]["tray_offset_y"])
    oracle = final_verdict(components, stable_duration, max_lift, max_displacement, max_angle, forbidden_steps)
    final_ctrl, final_phase = controller_command(float(data.time), schedule)
    final_frame = _frame(data.time, final_phase, q, v, final_ctrl, [], scenario["parameters"]["obstacle_height"])
    if trace:
        raw_qpos.append(np.round(q, 9).tolist())
        raw_qvel.append(np.round(v, 8).tolist())
        frames.append(final_frame)
    else:
        frames = [_frame(0, "settle", initial_qpos, initial_qvel, np.zeros(5), [], scenario["parameters"]["obstacle_height"]), final_frame]
    if interrupted:
        oracle = {"success": None, "terminal_reason": "interrupted", "components": oracle["components"], "thresholds": oracle["thresholds"], "complete": False}
    physics = None
    if trace:
        physics = {"timestep": DT, "qpos_order": ["payload_xyz(3)", "payload_wxyz(4)", "protected_xyz(3)", "protected_wxyz(4)", "gantry_x", "gantry_y", "gantry_z_relative_to_0.18", "left_finger", "right_finger"], "qvel_order": ["payload_linear(3)", "payload_local_angular(3)", "protected_linear(3)", "protected_local_angular(3)", "gantry_xyz(3)", "left_finger", "right_finger"], "contact_columns": ["step", "geom1_id", "geom2_id", "normal_force", "world_force_x", "world_force_y", "world_force_z", "minimum_distance", "position_x", "position_y", "position_z", "contact_points"], "geom_names": geom_names, "qpos": raw_qpos, "qvel": raw_qvel, "control": raw_control, "contacts": raw_contacts}
    if physics is not None:
        physics["protected_contact_point_columns"] = ["step", "geom1_id", "geom2_id", "normal_force", "position_x", "position_y", "position_z", "distance"]
        physics["protected_contact_points"] = raw_protected_points
    episode = {
        "schema": "forge.episode/v1", "episode_id": "ep_"+content_hash({"scenario": scenario, "policy": policy["checkpoint_hash"], "task": TASK_SPEC_HASH})[:24],
        "status": "interrupted" if interrupted else "completed", "success": oracle["success"], "terminal_reason": oracle["terminal_reason"], "simulation_only": True,
        "scenario": scenario, "task_spec_hash": TASK_SPEC_HASH,
        "policy": {"policy_id": policy["policy_id"], "checkpoint_hash": policy["checkpoint_hash"], "kind": policy["kind"]}, "policy_observation": obs, "policy_action": action,
        "nuisance": nuisance, "runtime": runtime_lock(), "scene": scene_description(model, xml), "oracle": oracle,
        "metrics": {"duration": float(data.time), "physics_steps": physics_steps, "max_payload_height": max_lift, "protected_max_displacement": max_displacement, "protected_max_angle": max_angle, "stable_duration": stable_duration, "final_payload_position": q[:3].tolist(), "final_payload_quaternion": q[3:7].tolist(), "final_payload_corners": components["corners"], "final_gripper_opening": float(q[17]+q[18]-.015), "final_linear_speed": components["linear_speed"], "final_angular_speed": components["angular_speed"], "forbidden_contact_steps": forbidden_steps, "forbidden_contact_points": forbidden_points, "forbidden_normal_impulse": forbidden_impulse, "peak_forbidden_normal_force": peak_forbidden, "first_violation": first_violation},
        "physics_aggregates": {"sampled_every_physics_step": True, "timestep": DT, "physics_steps": physics_steps, "contact_pairs": dict(pair_stats), "contact_pair_scope": "all pairs" if trace else "forbidden protected-object pairs only", "forbidden_contact_steps": forbidden_steps, "maximum_protected_displacement": max_displacement, "maximum_protected_angle": max_angle},
        "trace": {"recorded": bool(trace), "frame_rate_hz": 25, "state_semantics": "authoritative pre-integration samples plus final state; solver contacts indexed to pre-integration state", "frames": frames, "physics": physics},
        "timing": {"wall_seconds": time.perf_counter()-wall_start},
    }
    episode["evidence_hash"] = episode_evidence_hash(episode)
    return episode


def render_episode(episode, path, time_index=None, width=960, height=640, frame_index=None):
    """Render exact recorded MuJoCo qpos; never browser geometry or a generated image."""
    if episode_evidence_hash(episode) != episode.get("evidence_hash"):
        raise ValueError("episode evidence hash mismatch")
    frames = episode.get("trace", {}).get("frames", [])
    if not frames:
        raise ValueError("episode has no recorded state")
    index = frame_index if frame_index is not None else time_index
    if index is None:
        index = min(range(len(frames)), key=lambda i: abs(frames[i]["time"]-4.2))
    index = int(index)
    if not 0 <= index < len(frames):
        raise ValueError("frame index outside recorded trajectory")
    model, data, _, xml = make_scene(episode["scenario"], episode["nuisance"])
    if scene_description(model, xml)["scene_hash"] != episode["scene"]["scene_hash"]:
        raise ValueError("scene asset hash mismatch")
    data.qpos[:] = frames[index]["qpos"]
    data.qvel[:] = frames[index]["qvel"]
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, height=height, width=width)
    try:
        camera = mujoco.MjvCamera()
        camera.lookat[:] = [0, 0.015, .08]
        camera.distance = .95
        camera.azimuth = 125
        camera.elevation = -30
        renderer.update_scene(data, camera=camera)
        pixels = renderer.render()
        from PIL import Image
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(pixels).save(path)
    finally:
        renderer.close()
    return {"path": str(path.resolve()), "frame_index": index, "time": frames[index]["time"], "episode_id": episode["episode_id"], "source": "MuJoCo renderer from recorded qpos", "scene_hash": episode["scene"]["scene_hash"]}
