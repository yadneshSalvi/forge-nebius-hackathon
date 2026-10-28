#!/usr/bin/env python3
"""GPU-host LIBERO client: actual observations/actions/state, no fabricated episodes.

Run only in the pinned simulation environment after GPU preflight/server startup.
The collector is implemented and statically tested, but not runtime-qualified here.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.groot.contract import canonical, digest, file_hash, load_contract, read_preflight, validate_action, validate_observation, verify_source


class PolicyOutputError(ValueError):
    """Invalid returned actions are policy failures, not infrastructure exclusions."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--task-index", type=int, choices=range(10), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = load_contract()
    task = contract["task_roster"][args.task_index]
    if args.seed not in task["qualification_nominal_seeds"]:
        raise ValueError("Seed is outside this task's frozen nominal qualification schedule")
    if args.output.exists():
        raise ValueError("Attempt directory already exists; recorded attempts cannot be overwritten")
    preflight = read_preflight(args.preflight, contract)
    if not verify_source(args.source_root, contract)["ok"]:
        raise ValueError("Source changed after preflight")
    if sys.version_info[:2] != (3,12) or importlib.metadata.version("mujoco") != "3.3.1" or importlib.metadata.version("numpy") != "1.26.4":
        raise ValueError("Use the pinned Python3.12 LIBERO simulation island; not the gantry environment")
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    sys.path.insert(0, str(args.source_root.resolve()))
    import numpy as np
    import gymnasium as gym
    from gr00t.eval.sim.LIBERO.libero_env import register_libero_envs, normalize_gripper_action, invert_gripper_action
    from gr00t.policy.server_client import PolicyClient
    from PIL import Image

    args.output.mkdir(parents=True)
    record = {"schema":"forge.groot-qualification-episode/v1", "status":"started",
              "contract_sha256":digest(contract), "task":task, "seed":args.seed,
              "preflight_sha256":preflight["preflight_sha256"], "success":None,
              "forge_adapter_lock":preflight["forge_adapter_lock"],
              "scope":"Nominal qualification; not discovery, correction data or final evaluation",
              "environment_command_scope":"Recomputed pinned wrapper gripper transform of the proposed action; not measured actuator torque. last_solver_actuator_control reads sim.data.ctrl after each environment step.",
              "mid_episode_fork_qualified":False, "steps":[], "chunks":[], "files":{}}
    started = time.monotonic()
    env = client = None
    state_rows = []
    def save():
        (args.output/"episode.json").write_bytes(canonical(record))
    def stop(signum, frame):
        raise InterruptedError("Episode canceled or exceeded the bounded runtime")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(900)
    save()
    try:
        register_libero_envs()
        env = gym.make(task["environment"])
        client = PolicyClient(host="127.0.0.1", port=5555, timeout_ms=60000, api_token=os.environ.get("FORGE_GR00T_API_TOKEN"))
        identity = client.call_endpoint("forge_identity", requires_input=False)
        unsigned = {k:v for k,v in identity.items() if k != "identity_sha256"}
        if (identity.get("contract_sha256") != digest(contract) or identity.get("identity_sha256") != digest(unsigned)
                or identity.get("model_class") != "Gr00tN1d7" or identity.get("device") != "cuda:0"
                or identity.get("source_revision") != contract["source"]["revision"]
                or identity.get("checkpoint_revision") != contract["checkpoint"]["revision"]
                or identity.get("forge_adapter_lock") != preflight["forge_adapter_lock"]):
            raise ValueError("Policy server identity is not bound to the expected official model contract")
        record["server_identity"] = identity
        record["policy_reset"] = client.call_endpoint("forge_reset", {"seed":args.seed})
        observation, info = env.reset(seed=args.seed)
        raw_env = env.unwrapped._env
        initial = raw_env.get_sim_state().copy()
        np.save(args.output/"initial_state.npy", initial, allow_pickle=False)
        record["files"]["initial_state.npy"] = file_hash(args.output/"initial_state.npy")
        record["initial_state_sha256"] = record["files"]["initial_state.npy"]
        controller = raw_env.robots[0].controller
        controls = {}
        for name in ("input_min","input_max","output_min","output_max","control_delta","control_dim","kp","damping_ratio","policy_freq","goal_pos","goal_ori"):
            value = getattr(controller,name,None)
            if isinstance(value,np.ndarray): value = value.tolist()
            if value is None or isinstance(value,(str,int,float,bool,list)): controls[name]=value
        record["controller"] = {"class":type(controller).__name__,"configuration":controls,"capture_scope":"selected control parameters; full mid-episode controller restoration not qualified"}
        record["initial_success"] = bool(info.get("success",False))
        if record["initial_success"]:
            raise ValueError("Invalid nominal reset: task already succeeds before policy execution")
        for key in contract["modality"]["video_keys"]:
            filename=key.replace("video.","")+"-initial.png"
            Image.fromarray(observation[key]).save(args.output/filename)
            record["files"][filename]=file_hash(args.output/filename)
        record["status"]="running"
        save()
        state_rows=[initial]
        finished=False
        for chunk_index in range(90):
            latest=client.call_endpoint("forge_identity",requires_input=False)
            if latest.get("server_instance")!=identity["server_instance"]:
                raise ValueError("Policy server changed during the episode; stale attempt fenced")
            batch={}
            for key in contract["modality"]["video_keys"]:batch[key]=np.asarray(observation[key],dtype=np.uint8)[None,None]
            for key in contract["modality"]["state_keys"]:batch[key]=np.asarray(observation[key],dtype=np.float32)[None,None]
            text_key=contract["modality"]["language_key"]
            batch[text_key]=[observation[text_key]]
            validate_observation(batch,contract)
            actions, action_info=client.get_action(batch)
            try:
                validate_action(actions,contract)
            except ValueError as exc:
                raise PolicyOutputError(str(exc)) from exc
            filename=f"chunk-{chunk_index:04d}.npz"
            np.savez_compressed(args.output/filename,**{k:v for k,v in batch.items() if k!=text_key},**actions)
            sha=file_hash(args.output/filename)
            record["files"][filename]=sha
            record["chunks"].append({"index":chunk_index,"step":len(record["steps"]),"file":filename,"sha256":sha,"instruction":batch[text_key][0],"proposed_steps":16,"executed_steps":0})
            for local_step in range(8):
                action={key:array[0,local_step].copy() for key,array in actions.items()}
                proposed=np.concatenate([action[k] for k in contract["modality"]["action_keys"]])
                executed=invert_gripper_action(normalize_gripper_action(proposed.copy()))
                observation,reward,terminated,truncated,info=env.step(action)
                state_rows.append(raw_env.get_sim_state().copy())
                record["steps"].append({"step":len(record["steps"]),"chunk":chunk_index,"chunk_step":local_step,"proposed_action":proposed.tolist(),"environment_command":executed.tolist(),"last_solver_actuator_control":raw_env.sim.data.ctrl.copy().tolist(),"success":bool(info.get("success",False)),"reward":float(reward),"terminated":bool(terminated),"truncated":bool(truncated),"simulation_time":float(raw_env.sim.data.time)})
                record["chunks"][-1]["executed_steps"]+=1
                if terminated or truncated:
                    finished=True
                    break
            np.savez_compressed(args.output/"simulation_states.npz",state=np.asarray(state_rows))
            save()
            if finished:break
        record["files"]["simulation_states.npz"]=file_hash(args.output/"simulation_states.npz")
        record["success"]=bool(raw_env.check_success())
        record["terminal_reason"]="stock_predicate_pass" if record["success"] else ("terminated_without_success" if finished else "720_step_timeout")
        record["status"]="completed"
    except (KeyboardInterrupt,InterruptedError):
        record.update(status="interrupted",success=None,error="Canceled or runtime limit reached; incomplete attempt excluded from task outcomes")
    except PolicyOutputError as exc:
        record.update(status="policy_failed",success=False,terminal_reason="invalid_action_output",error=str(exc)[:1200])
    except Exception as exc:
        record.update(status="infrastructure_failed",success=None,error_kind=type(exc).__name__,error=str(exc)[:1200])
    finally:
        signal.alarm(0)
        record["elapsed_seconds"]=round(time.monotonic()-started,3)
        if state_rows:
            np.savez_compressed(args.output/"simulation_states.npz",state=np.asarray(state_rows))
        # Preserve all partial files, including arrays written before interruption.
        record["files"]={p.name:file_hash(p) for p in args.output.iterdir() if p.is_file() and p.name!="episode.json"}
        record["evidence_sha256"]=digest({k:v for k,v in record.items() if k!="evidence_sha256"})
        save()
        if client is not None:client.close()
        if env is not None:env.close()
    print(json.dumps({"status":record["status"],"success":record["success"],"steps":len(record["steps"]),"path":str(args.output.resolve()),"qualified":False}))
    return 0 if record["status"]=="completed" else 2


if __name__=="__main__":
    raise SystemExit(main())
