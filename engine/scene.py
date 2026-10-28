"""Original MIT-licensed gantry, free cuboids, and tray. No welds or pose resets in a run."""
from __future__ import annotations

import math
import mujoco
import numpy as np

from .spec import TASK_SPEC, content_hash, normalize_scenario, sample_nuisance


def scene_xml(scenario: dict, nuisance: dict | None = None) -> str:
    scenario = normalize_scenario(scenario)
    n = nuisance or sample_nuisance(scenario["seed"])
    p = scenario["parameters"]
    h, mu, y = p["obstacle_height"], p["friction"], 0.05+p["tray_offset_y"]
    px, py = np.array([-0.20, -0.05])+n["payload_reset_xy"]
    ox, oy = n["protected_reset_xy"]
    yaw = p["payload_yaw"]+n["payload_reset_yaw"]
    oyaw = n["protected_reset_yaw"]
    gain = n["actuator_gain_scale"]
    return f'''<mujoco model="forge_original_cartesian_gantry_v1">
  <compiler angle="radian"/>
  <option timestep="0.002" gravity="0 0 -9.81" integrator="implicitfast" iterations="80" cone="elliptic"/>
  <visual><global offwidth="1280" offheight="800"/><quality shadowsize="2048"/><headlight diffuse=".4 .4 .45" ambient=".3 .3 .34" specular=".25 .25 .3"/></visual>
  <statistic center="0 0 .12" extent=".65"/>
  <default><geom friction="{mu} .004 .0001" solref=".006 1" solimp=".95 .99 .001"/><joint damping="2"/></default>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1=".11 .15 .20" rgb2=".14 .18 .23" width="256" height="256"/>
    <material name="table_material" texture="grid" texrepeat="16 12" reflectance=".12"/>
    <material name="metal" rgba=".45 .50 .59 1" shininess=".7" specular=".5"/>
    <material name="mint" rgba=".35 .89 .80 1" shininess=".3"/>
    <material name="rose" rgba=".97 .46 .55 1" shininess=".4"/>
    <material name="tray_material" rgba=".30 .28 .44 1" shininess=".4"/>
  </asset>
  <worldbody>
    <light name="key" pos="-.3 -.5 1.5" dir=".2 .3 -1" diffuse=".9 .95 1" castshadow="true"/>
    <light name="fill" pos=".6 .3 .8" dir="-.4 -.2 -.8" diffuse=".4 .55 .65" castshadow="false"/>
    <camera name="inspection" pos=".70 -.85 .62" xyaxes=".77 .64 0 -.31 .37 .88"/>
    <geom name="table" type="plane" size=".65 .48 .02" material="table_material"/>
    <geom name="rail_left" type="box" pos="-.39 0 .42" size=".012 .30 .012" material="metal" contype="0" conaffinity="0"/>
    <geom name="rail_right" type="box" pos=".39 0 .42" size=".012 .30 .012" material="metal" contype="0" conaffinity="0"/>
    <geom name="pillar_left" type="box" pos="-.39 .28 .21" size=".014 .014 .21" material="metal" contype="0" conaffinity="0"/>
    <geom name="pillar_right" type="box" pos=".39 .28 .21" size=".014 .014 .21" material="metal" contype="0" conaffinity="0"/>
    <body name="payload" pos="{px} {py} .025" quat="{math.cos(yaw/2)} 0 0 {math.sin(yaw/2)}"><freejoint name="payload_free"/><geom name="payload_geom" type="box" size=".024 .018 .025" mass=".06" material="mint"/></body>
    <body name="protected" pos="{ox} {oy} {h/2}" quat="{math.cos(oyaw/2)} 0 0 {math.sin(oyaw/2)}"><freejoint name="protected_free"/><geom name="protected_geom" type="box" size=".025 .042 {h/2}" mass=".4" material="rose"/></body>
    <geom name="tray_floor" type="box" pos=".20 {y} .004" size=".077 .065 .004" material="tray_material"/>
    <geom name="tray_left" type="box" pos=".20 {y-.071} .022" size=".083 .006 .022" material="tray_material"/>
    <geom name="tray_right" type="box" pos=".20 {y+.071} .022" size=".083 .006 .022" material="tray_material"/>
    <geom name="tray_back" type="box" pos=".283 {y} .022" size=".006 .065 .022" material="tray_material"/>
    <geom name="tray_front" type="box" pos=".117 {y} .022" size=".006 .065 .022" material="tray_material"/>
    <body name="gantry" pos="0 0 .18" gravcomp="1">
      <joint name="gantry_x" type="slide" axis="1 0 0" range="-.4 .4" limited="true" damping="12"/>
      <joint name="gantry_y" type="slide" axis="0 1 0" range="-.3 .3" limited="true" damping="12"/>
      <joint name="gantry_z" type="slide" axis="0 0 1" range="-.12 .25" limited="true" damping="12"/>
      <geom name="palm" type="box" size=".036 .060 .012" mass=".7" material="metal"/>
      <geom name="stem" type="box" pos="0 0 .07" size=".012 .014 .06" mass=".04" rgba=".2 .26 .34 1" contype="0" conaffinity="0"/>
      <body name="left_finger" pos="0 0 -.04" gravcomp="1"><joint name="finger_left" type="slide" axis="0 1 0" range=".011 .065" limited="true" damping="1"/><geom name="left_pad" type="box" size=".032 .0075 .025" mass=".04" material="metal"/></body>
      <body name="right_finger" pos="0 0 -.04" gravcomp="1"><joint name="finger_right" type="slide" axis="0 -1 0" range=".011 .065" limited="true" damping="1"/><geom name="right_pad" type="box" size=".032 .0075 .025" mass=".04" material="metal"/></body>
    </body>
  </worldbody>
  <actuator>
    <position name="x_target" joint="gantry_x" kp="{1800*gain}" kv="80" ctrlrange="-.4 .4"/>
    <position name="y_target" joint="gantry_y" kp="{1800*gain}" kv="80" ctrlrange="-.3 .3"/>
    <position name="z_target" joint="gantry_z" kp="{2200*gain}" kv="90" ctrlrange="-.12 .25"/>
    <position name="left_target" joint="finger_left" kp="{350*gain}" kv="3" ctrlrange=".011 .065" forcerange="-8 8"/>
    <position name="right_target" joint="finger_right" kp="{350*gain}" kv="3" ctrlrange=".011 .065" forcerange="-8 8"/>
  </actuator>
</mujoco>'''


def make_scene(scenario: dict, nuisance: dict | None = None):
    scenario = normalize_scenario(scenario)
    nuisance = nuisance or sample_nuisance(scenario["seed"])
    xml = scene_xml(scenario, nuisance)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    # Reset joint coordinates once, before stepping. Free bodies subsequently move only through physics.
    data.qpos[14:19] = [-0.20, -0.05, 0, 0.052, 0.052]
    mujoco.mj_forward(model, data)
    return model, data, nuisance, xml


def scene_description(model, xml: str) -> dict:
    geometries = []
    for i in range(model.ngeom):
        geomtype = int(model.geom_type[i])
        rgba = model.geom_rgba[i].tolist()
        mat = model.geom_matid[i]
        if mat >= 0:
            rgba = model.mat_rgba[mat].tolist()
        geometries.append({
            "name": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i),
            "type": "plane" if geomtype == mujoco.mjtGeom.mjGEOM_PLANE else "box",
            "body": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[i])),
            "position": model.geom_pos[i].tolist(), "quaternion": model.geom_quat[i].tolist(),
            "size": model.geom_size[i].tolist(), "rgba": rgba,
            "collidable": bool(model.geom_contype[i] or model.geom_conaffinity[i]),
        })
    return {"schema": "forge.scene/v1", "geometry_frame": "body_local", "quaternion_order": "WXYZ", "world_up": "+z", "units": "m", "asset_license": "MIT", "scene_hash": content_hash(xml), "geometries": geometries, "target": TASK_SPEC["target"]}
