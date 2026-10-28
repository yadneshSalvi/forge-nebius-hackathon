"""Geometry and physics-only task predicate; no dependency on policy or model text."""
from __future__ import annotations

import itertools
import numpy as np

from .spec import TASK_SPEC

_SIGNS = np.array(list(itertools.product([-1.0, 1.0], repeat=3)))


def quaternion_matrix(quaternion) -> np.ndarray:
    q = np.asarray(quaternion, dtype=float)
    if q.shape != (4,) or not np.all(np.isfinite(q)) or abs(float(q @ q) - 1) > 1e-4:
        raise ValueError("expected normalized WXYZ quaternion")
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def oriented_corners(position, quaternion, half_extents) -> np.ndarray:
    return (_SIGNS * np.asarray(half_extents)) @ quaternion_matrix(quaternion).T + np.asarray(position)


def quaternion_angle(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    dot = float(abs(np.dot(a, b)))
    return float(2 * np.arccos(np.clip(dot, 0, 1)))


def geometry_components(position, quaternion, linear_velocity, angular_velocity, opening: float, tray_offset_y: float = 0) -> dict:
    target = TASK_SPEC["target"]
    th = TASK_SPEC["thresholds"]
    corners = oriented_corners(position, quaternion, TASK_SPEC["payload"]["half_extents"])
    center = np.array(target["center_xy"]) + [0, tray_offset_y]
    half = np.asarray(target["half_extents_xy"])
    tolerance = th["containment_tolerance"]
    inside = bool(np.all(corners[:, :2] >= center-half-tolerance) and np.all(corners[:, :2] <= center+half+tolerance) and np.min(corners[:, 2]) >= target["floor_z"]-tolerance and np.max(corners[:, 2]) <= target["top_z"]+tolerance)
    linear_speed = float(np.linalg.norm(linear_velocity))
    angular_speed = float(np.linalg.norm(angular_velocity))
    released = bool(opening >= th["released_opening_min"])
    stationary = bool(linear_speed <= th["stable_linear_velocity_max"] and angular_speed <= th["stable_angular_velocity_max"])
    return {"inside_target": inside, "released": released, "stationary": stationary, "linear_speed": linear_speed, "angular_speed": angular_speed, "corners": corners.tolist()}


def final_verdict(components: dict, stable_duration: float, max_lift: float, protected_displacement: float, protected_angle: float, forbidden_contacts: int) -> dict:
    th = TASK_SPEC["thresholds"]
    checks = {"inside_target": bool(components["inside_target"]), "released": bool(components["released"]), "stable": bool(stable_duration + 1e-9 >= th["stable_duration_min"]), "lifted": bool(max_lift >= th["payload_center_lift_min"]), "protected_position": bool(protected_displacement <= th["protected_displacement_max"]), "protected_orientation": bool(protected_angle <= th["protected_angle_max"]), "no_forbidden_contact": forbidden_contacts == 0}
    if not checks["no_forbidden_contact"]:
        reason = "protected_contact"
    elif not checks["protected_position"] or not checks["protected_orientation"]:
        reason = "protected_disturbed"
    elif not checks["lifted"]:
        reason = "grasp_failed"
    elif not checks["inside_target"]:
        reason = "outside_target"
    elif not checks["released"]:
        reason = "not_released"
    elif not checks["stable"]:
        reason = "not_settled"
    else:
        reason = "success"
    return {"success": all(checks.values()), "terminal_reason": reason, "components": checks, "thresholds": dict(th)}
