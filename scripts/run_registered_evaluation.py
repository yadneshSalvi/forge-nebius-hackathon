"""Run only an externally registered final manifest against frozen policies."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control.store import Store, digest
from control.supervisor import Supervisor
from control.final_eval import validate_registration,validate_evaluation_config,evaluation_source_lock
from control.protocol import PROTOCOL_SHA

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign")
    parser.add_argument("--manifest",type=Path)
    parser.add_argument("--workers",type=int,choices=[1,2,3,4],default=4)
    parser.add_argument("--resume")
    parser.add_argument("--validate-only",action="store_true")
    args=parser.parse_args()
    store=Store();supervisor=Supervisor(store)
    if args.resume:
        cid=args.resume
        current=store.get(cid,detail=False)
        if current["config"].get("kind")!="registered_evaluation":raise ValueError("Resume target is not a registered evaluation")
        manifest=store.read_artifact(current["config"]["registered_manifest_sha"])
        parent=store.get(current["config"]["parent_campaign_id"],detail=False)
        validate_registration(manifest,parent)
        validate_evaluation_config(manifest,parent,current["config"])
        if current["config"]["evaluation_source_sha"]!=evaluation_source_lock()["sha256"] or current["config"]["evaluation_source_sha"]!=manifest["evaluation_source_sha"]:
            raise ValueError("Frozen evaluation implementation changed; resume prohibited")
        if args.validate_only:
            print(json.dumps({"validated":True,"campaign_id":cid,"action":"read_only_resume_validation"}),flush=True)
            return
        store.action(cid,"resume",current["generation"],"resume-"+uuid.uuid4().hex)
    else:
        if not args.campaign or not args.manifest:parser.error("--campaign and --manifest are required for a new registration")
        parent=store.get(args.campaign,detail=False)
        manifest=json.loads(args.manifest.read_text())
        validate_registration(manifest,parent)
        lock=evaluation_source_lock()
        print(json.dumps({"validated":True,"manifest_sha":digest(manifest),"evaluation_source_sha":lock["sha256"],"nominations":parent["report"]["nominations"],"checkpoints":16,"scenarios":500}),flush=True)
        if args.validate_only:return
        config={"kind":"registered_evaluation","parent_campaign_id":parent["id"],"seed":0,"search_budget":8000,"task_sha":parent["config"]["task_sha"],"protocol_sha":PROTOCOL_SHA,"source_sha":parent["config"]["source_sha"],"base_checkpoint_sha":parent["config"]["base_checkpoint_sha"],"registered_manifest_sha":store.artifact(manifest),"evaluation_source_sha":lock["sha256"],"evaluation_source_lock_sha":store.artifact(lock),"workers":args.workers,"live_models":False}
        cid,new=store.create("Registered policy confirmation",config,"registered-"+digest({"manifest":manifest,"parent":parent["id"]})[:40])
        if not new and store.get(cid,False)["status"]=="completed":
            print(json.dumps({"campaign_id":cid,"status":"completed","message":"Existing immutable result; no new compute"}),flush=True)
            return
    print(json.dumps({"campaign_id":cid,"action":"starting_or_resuming","note":"Ctrl-C detaches this monitor; cancel the evaluation through FORGE to stop compute"}),flush=True)
    supervisor.start(cid)
    previous=None
    while True:
        supervisor.reap()
        state=store.get(cid,detail=False)
        summary={"campaign_id":cid,"status":state["status"],"stage":state["stage"],"progress":state["progress"],"error":state.get("error")}
        if summary!=previous:print(json.dumps(summary),flush=True);previous=summary
        if state["status"] not in {"queued","running","pause_requested","cancel_requested"}:break
        time.sleep(2)
    if state["status"]!="completed":raise SystemExit(1)

if __name__=="__main__":main()
