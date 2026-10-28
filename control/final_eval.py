"""Registered, frozen-checkpoint evaluation. No data acquisition or tuning."""
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import time
from engine import run_episode, normalize_scenario, TASK_SPEC_HASH, validate_checkpoint
from .store import ROOT, Store, digest, now, FenceLost
from .protocol import PROTOCOL_SHA, PROTOCOL, ARMS, TRAINING_SEEDS
from .lineage import source_lock, register_final_exposure
from .runner import RunContext

def evaluation_source_lock():
    paths=[ROOT/"control"/n for n in ("final_eval.py","final_report.py","final_worker.py","statistics.py","lineage.py")]+[ROOT/"scripts"/"run_registered_evaluation.py"]
    files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return {"files":files,"sha256":digest(files)}

def _artifact_sha(value):
    return isinstance(value,str) and re.fullmatch(r"[a-f0-9]{64}",value) is not None

def _utc_timestamp(value,label):
    try:
        parsed=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError()
        return parsed.astimezone(dt.timezone.utc)
    except (AttributeError,TypeError,ValueError) as exc:
        raise ValueError(f"Invalid {label} timestamp; timezone is required") from exc

def validate_registration(manifest,parent):
    """Validate the immutable registration before any exposure or physical work."""
    if not isinstance(manifest,dict) or manifest.get("schema")!="forge.root-registration/v1":raise ValueError("Unsupported final registration schema")
    if parent.get("status")!="completed":raise ValueError("Development campaign must be completed before registration")
    if not parent.get("id") or manifest.get("parent_campaign_id")!=parent["id"]:raise ValueError("Registered parent campaign mismatch")
    config=parent.get("config",{})
    if manifest.get("task_spec_hash")!=TASK_SPEC_HASH or config.get("task_sha")!=TASK_SPEC_HASH:raise ValueError("Registered task hash mismatch")
    if manifest.get("protocol_sha")!=PROTOCOL_SHA or config.get("protocol_sha")!=PROTOCOL_SHA:raise ValueError("Registered protocol hash mismatch")
    if manifest.get("source_sha")!=config.get("source_sha"):raise ValueError("Registered development source mismatch")
    if source_lock()["sha256"]!=config.get("source_sha"):raise ValueError("Scientific implementation changed after development freeze")
    evaluation_lock=evaluation_source_lock()
    if manifest.get("evaluation_source_files")!=evaluation_lock["files"] or manifest.get("evaluation_source_sha")!=evaluation_lock["sha256"]:raise ValueError("Registered evaluation source lock mismatch")
    training=parent.get("training",{})
    runs=training.get("runs",[])
    if training.get("status")!="completed" or not isinstance(runs,list) or len(runs)!=15:raise ValueError("All 15 trained checkpoints must be frozen first")
    expected={(arm,seed) for arm in ARMS for seed in TRAINING_SEEDS}
    bindings=[]
    for run in runs:
        if not isinstance(run,dict) or not isinstance(run.get("arm"),str) or type(run.get("seed")) is not int or (run.get("arm"),run.get("seed")) not in expected or not _artifact_sha(run.get("checkpoint_sha")):
            raise ValueError("Invalid frozen training arm/seed/checkpoint binding")
        bindings.append({key:run[key] for key in ("arm","seed","checkpoint_sha")})
    if {(r["arm"],r["seed"]) for r in bindings}!=expected:raise ValueError("Incomplete or duplicate frozen training arms/seeds")
    bindings.sort(key=lambda run:(run["arm"],run["seed"]))
    if manifest.get("frozen_training_runs")!=bindings:raise ValueError("Registered frozen training mapping changed")
    base_sha=config.get("base_checkpoint_sha")
    artifacts=[base_sha]+[r["checkpoint_sha"] for r in bindings]
    if not _artifact_sha(base_sha) or len(set(artifacts))!=16:raise ValueError("Sixteen distinct frozen checkpoint artifacts are required")
    frozen=manifest.get("frozen_checkpoint_artifacts")
    if not isinstance(frozen,list) or len(frozen)!=16 or not all(_artifact_sha(sha) for sha in frozen) or sorted(frozen)!=sorted(artifacts):raise ValueError("Registered checkpoint artifact set changed")
    report=parent.get("report",{})
    nominees=report.get("nominations",{})
    if not isinstance(nominees,dict) or set(nominees)!=set(ARMS):raise ValueError("Development-only nominations must be frozen first")
    for arm,nominee in nominees.items():
        if not isinstance(nominee,dict) or type(nominee.get("seed")) is not int or not any(r["arm"]==arm and r["seed"]==nominee.get("seed") and r["checkpoint_sha"]==nominee.get("checkpoint_sha") for r in bindings):
            raise ValueError("Development nomination does not match a frozen trained checkpoint")
    if manifest.get("development_nominations")!=nominees:raise ValueError("Registered development nominations changed")
    frozen_at=report.get("nominations_frozen_at")
    if manifest.get("nominations_frozen_at")!=frozen_at:raise ValueError("Registered nomination freeze timestamp changed")
    nomination_time=_utc_timestamp(frozen_at,"nomination freeze")
    registration_time=_utc_timestamp(manifest.get("registered_at"),"registration")
    if nomination_time>=registration_time or registration_time>dt.datetime.now(dt.timezone.utc):raise ValueError("Nomination freeze must precede registration, and registration cannot be in the future")
    if training.get("weights_frozen_at") and _utc_timestamp(training["weights_frozen_at"],"training freeze")>nomination_time:raise ValueError("Nomination timestamp precedes the frozen weights")
    scenes=manifest.get("scenarios",[])
    if not isinstance(scenes,list) or len(scenes)!=500 or not all(isinstance(s,dict) for s in scenes):raise ValueError("Registered protocol requires exactly 500 physical scenarios")
    if sum(s.get("family")=="nominal" for s in scenes)!=200:raise ValueError("Registered protocol requires 200 IID nominal scenarios")
    ids,physical=set(),set()
    families={"nominal","fresh_in_envelope","tall_low_friction","yaw_offset_composition"}
    for s in scenes:
        if s.get("split")!="sealed":raise ValueError("Final scenario must carry sealed split")
        if s.get("family") not in families:raise ValueError("Unknown registered scenario family")
        if not isinstance(s.get("scenario_id"),str) or not s["scenario_id"]:raise ValueError("Final scenario identifier must be explicit")
        if not isinstance(s.get("parameters"),dict) or set(s["parameters"])!=set(PROTOCOL["nominal_distribution"]):raise ValueError("Final scenario must explicitly freeze all four factors")
        normalized=normalize_scenario(s)
        physical_key=digest({"parameters":{k:(0.0 if v==0 else v) for k,v in normalized["parameters"].items()},"seed":normalized["seed"]})
        if physical_key in physical:raise ValueError("Repeated physical final case")
        physical.add(physical_key)
        if s.get("family")=="nominal":
            if any(not bounds[0]<=normalized["parameters"][key]<=bounds[1] for key,bounds in PROTOCOL["nominal_distribution"].items()):raise ValueError("Nominal scenario lies outside registered nominal distribution")
        p=normalized["parameters"]
        first=p["obstacle_height"]>=.145 and p["friction"]<=.28
        second=abs(p["payload_yaw"])>=.12 and abs(p["tray_offset_y"])>=.025
        family=s["family"]
        if (family=="fresh_in_envelope" and (first or second)) or (family=="tall_low_friction" and not first) or (family=="yaw_offset_composition" and (not second or first)):
            raise ValueError("Registered scenario family does not match its declared region")
        if s["scenario_id"] in ids:raise ValueError("Duplicate scenario identifier")
        ids.add(s["scenario_id"])

def validate_evaluation_config(manifest,parent,config):
    """Bind a queued/resumed job to the same registration and base artifact."""
    required={"kind":"registered_evaluation","parent_campaign_id":parent["id"],"task_sha":manifest["task_spec_hash"],"protocol_sha":manifest["protocol_sha"],"source_sha":manifest["source_sha"],"base_checkpoint_sha":parent["config"]["base_checkpoint_sha"],"registered_manifest_sha":digest(manifest),"evaluation_source_sha":manifest["evaluation_source_sha"]}
    if any(config.get(key)!=value for key,value in required.items()):raise ValueError("Evaluation job configuration differs from the frozen registration")
    if type(config.get("workers")) is not int or not 1<=config["workers"]<=4:raise ValueError("Evaluation worker count is outside the frozen local limit")

def _physical_job(scene,checkpoint):
    return run_episode(scene,checkpoint,trace=False)

def run_registered(store,cid,gen):
    ctx=RunContext(store,cid,gen)
    config=ctx.config
    parent=store.get(config["parent_campaign_id"],detail=False)
    manifest=store.read_artifact(config["registered_manifest_sha"])
    validate_registration(manifest,parent)
    validate_evaluation_config(manifest,parent,config)
    if evaluation_source_lock()["sha256"]!=config["evaluation_source_sha"]:raise ValueError("Evaluation implementation changed; resume prohibited")
    if parent["config"].get("source_lock_sha") and store.read_artifact(parent["config"]["source_lock_sha"])!=source_lock():raise ValueError("Development scientific source snapshot mismatch")
    runs=parent["training"]["runs"]
    policies=[{"arm":"base","seed":None,"checkpoint_sha":config["base_checkpoint_sha"],"policy_id":ctx.base["policy_id"]}]+runs
    checkpoints={p["checkpoint_sha"]:validate_checkpoint(store.read_artifact(p["checkpoint_sha"])) for p in policies}
    if sorted(checkpoints)!=sorted(manifest["frozen_checkpoint_artifacts"]):raise ValueError("Actual evaluation checkpoint set differs from the frozen registration")
    exposure=register_final_exposure(store,TASK_SPEC_HASH,PROTOCOL_SHA,config["registered_manifest_sha"],list(checkpoints))
    rows=[]
    pending=[]
    for scene in manifest["scenarios"]:
        for p in policies:
            identity=digest({"scenario":scene,"checkpoint":p["checkpoint_sha"],"purpose":"registered_evaluation"})
            ident=cid+"-e"+identity[:14]
            old=store.existing_episode(cid,identity)
            if old is not None:
                rows.append(outcome_row(scene,p,ident,old))
            else:pending.append((scene,p,identity,ident))
    total=len(manifest["scenarios"])*len(policies)
    ctx.update("registered_evaluation",len(rows),total,"Evaluating frozen checkpoints on independently registered cases",exposure=exposure)
    iterator=iter(pending)
    with ProcessPoolExecutor(max_workers=config["workers"]) as pool:
        futures={}
        def submit_next():
            try:job=next(iterator)
            except StopIteration:return False
            futures[pool.submit(_physical_job,job[0],checkpoints[job[1]["checkpoint_sha"]])]=job
            return True
        for _ in range(config["workers"]*2):submit_next()
        while futures:
            ctx.boundary()
            done,_=wait(futures,timeout=1,return_when=FIRST_COMPLETED)
            for future in done:
                scene,p,identity,ident=futures.pop(future)
                episode=future.result()
                if episode["status"]!="completed":raise RuntimeError("Incomplete final episode; no verdict accepted")
                row=outcome_row(scene,p,ident,episode)
                summary={"id":ident,"scenario":scene,"policy_id":p["policy_id"],"checkpoint_hash":episode["policy"]["checkpoint_hash"],"purpose":"registered_evaluation","success":episode["success"],"valid":True,"outcome":episode["terminal_reason"],"terminal_reason":episode["terminal_reason"],"status":"completed","metrics":episode["metrics"],"trace_available":False}
                store.save_episode(cid,gen,identity,episode,summary)
                rows.append(row)
                submit_next()
            if done and (len(rows)%32<len(done) or not futures):ctx.update("registered_evaluation",len(rows),total,f"Committed {len(rows)} of {total} registered paired episodes")
    from .final_report import make_final_report
    report=make_final_report(ctx,parent,manifest,rows,exposure)
    store.finish(cid,gen,"completed","report",{"report":report,"registered_report":report})
    with store.transaction() as db:
        p=store._row(db,config["parent_campaign_id"])
        payload=json.loads(p["payload"])
        payload["registered_report"]=report
        db.execute("UPDATE campaigns SET payload=?,updated_at=? WHERE id=?",(json.dumps(payload,separators=(",",":")),now(),p["id"]))
        store._event(db,p["id"],p["generation"],"registered_confirmation_attached",{"evaluation_campaign_id":cid,"report_sha":report["artifact_sha"]})

def outcome_row(scene,p,ident,episode):
    return {"scenario_id":scene["scenario_id"],"family":scene["family"],"scenario_seed":scene["seed"],"arm":p["arm"],"training_seed":p["seed"],"policy_id":p["policy_id"],"checkpoint_sha":p["checkpoint_sha"],"episode_id":ident,"success":episode["success"],"valid":True,"terminal_reason":episode["terminal_reason"],"metrics":episode["metrics"]}
