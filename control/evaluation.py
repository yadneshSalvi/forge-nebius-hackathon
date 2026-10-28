"""Frozen development evaluation, explicit nomination, paired diagnostics."""
import numpy as np
from .protocol import ARMS, PROTOCOL_SHA
from .statistics import summarize, paired, seed_cluster_interval
from .store import now

def evaluate_development(ctx,runs):
    manifest=ctx.store.read_artifact(ctx.config["development_manifest_sha"])
    scenes=manifest["scenarios"]
    policies=[{"arm":"base","seed":None,"policy_id":ctx.base["policy_id"],"checkpoint_sha":ctx.config["base_checkpoint_sha"]}]+runs
    outcomes=[]
    count=0
    for entry in policies:
        checkpoint=ctx.store.read_artifact(entry["checkpoint_sha"])
        for scene in scenes:
            r=ctx.run(scene,checkpoint,purpose=f"evaluation_{entry['arm']}_{entry['seed']}",trace=False)
            outcomes.append({"scenario_id":scene["scenario_id"],"family":scene["family"],"scenario_seed":scene["seed"],"split":scene["split"],"arm":entry["arm"],"training_seed":entry["seed"],"policy_id":entry["policy_id"],"checkpoint_sha":entry["checkpoint_sha"],"episode_id":r["id"],"success":r["success"],"valid":r["valid"],"terminal_reason":r["terminal_reason"]})
            count+=1
            if count%8==0 or count==len(policies)*len(scenes):
                ctx.update("evaluation",count,len(policies)*len(scenes),f"Completed {count} paired development episodes")
    outcome_sha=ctx.store.artifact({"manifest_sha":ctx.config["development_manifest_sha"],"rows":outcomes})
    baseline=[o for o in outcomes if o["arm"]=="base"]
    if not all(o["valid"] for o in outcomes):raise RuntimeError("Evaluation contains invalid scenes; outcomes retained but report remains incomplete")
    arms,nominations=[],{}
    for arm,label in ARMS.items():
        arm_runs=[r for r in runs if r["arm"]==arm]
        seed_reports,arrays=[],[]
        all_arm=[o for o in outcomes if o["arm"]==arm]
        for run in arm_runs:
            rows=[o for o in all_arm if o["training_seed"]==run["seed"]]
            result={**summarize(rows),**paired([o["success"] for o in baseline],[o["success"] for o in rows]),"seed":run["seed"],"checkpoint_sha":run["checkpoint_sha"]}
            seed_reports.append(result)
            arrays.append([o["success"] for o in rows])
        nomination=sorted(seed_reports,key=lambda r:(-r["successes"],r["seed"]))[0]
        nominations[arm]={"seed":nomination["seed"],"checkpoint_sha":nomination["checkpoint_sha"],"development_successes":nomination["successes"],"development_total":nomination["total"],"rule":"Highest frozen development-validation success count; lowest training seed breaks ties"}
        nominated=[o for o in all_arm if o["training_seed"]==nomination["seed"]]
        nominal_base=[o for o in baseline if o["family"]=="nominal"]
        nominal_revised=[o for o in nominated if o["family"]=="nominal"]
        nominal={**summarize(nominal_revised),**paired([o["success"] for o in nominal_base],[o["success"] for o in nominal_revised]),"checkpoint_seed":nomination["seed"]}
        counts={k:sum(s["paired"][k] for s in seed_reports) for k in ("rescued","regressed","both_success","both_failure")}
        families=[]
        for family in sorted({o["family"] for o in baseline}):
            b=[o for o in baseline if o["family"]==family]
            r=[o for o in nominated if o["family"]==family]
            families.append({"family":family,"baseline":summarize(b),**summarize(r),**paired([o["success"] for o in b],[o["success"] for o in r])})
        summary=summarize(all_arm)
        summary["interval"]=[min(s["interval"][0] for s in seed_reports),max(s["interval"][1] for s in seed_reports)]
        summary["interval_method"]="Envelope of seed-conditional Wilson intervals; not 5N independent scenario draws"
        arms.append({"name":arm,"label":label,**summary,"delta":float(np.mean(arrays)-np.mean([o["success"] for o in baseline])),"delta_interval":seed_cluster_interval([o["success"] for o in baseline],arrays),"delta_interval_method":"Descriptive paired scenario/seed bootstrap; not used for non-inferiority","paired":counts,"paired_denominator":len(all_arm),"nominal":nominal,"seeds":seed_reports,"families":families,"nomination":nominations[arm]})
    return finish_report(ctx,runs,manifest,baseline,outcomes,arms,nominations,outcome_sha)

def finish_report(ctx,runs,manifest,baseline,outcomes,arms,nominations,outcome_sha):
    by_scene={o["scenario_id"]:o for o in baseline}
    scenes={s["scenario_id"]:s for s in manifest["scenarios"]}
    regressions,rescues=[],[]
    for row in [r for r in outcomes if r["arm"]!="base"]:
        b=by_scene[row["scenario_id"]]
        item={"scenario_id":row["scenario_id"],"family":row["family"],"arm":row["arm"],"seed":row["training_seed"],"base_episode_id":b["episode_id"],"revised_episode_id":row["episode_id"],"terminal_reason":row["terminal_reason"],"checkpoint_sha":row["checkpoint_sha"],"nomination":row["training_seed"]==nominations[row["arm"]]["seed"]}
        if b["success"] and not row["success"]:regressions.append(item)
        elif not b["success"] and row["success"]:rescues.append(item)
    comparisons=[]
    for label,group in (("regression",regressions),("rescue",rescues)):
        priority=sorted(group,key=lambda r:(not (r["arm"]=="minimized" and r["nomination"]),r["scenario_id"],r["seed"]))
        for item in priority[:2]:
            scene=scenes[item["scenario_id"]]
            checkpoint=ctx.store.read_artifact(item["checkpoint_sha"])
            b=ctx.run(scene,ctx.base,purpose="report_comparison",trace=True)
            r=ctx.run(scene,checkpoint,purpose="report_comparison",trace=True)
            if label=="regression" and not (b["success"] and not r["success"]):raise RuntimeError("Rich replay disagreed with frozen regression outcome")
            if label=="rescue" and not (not b["success"] and r["success"]):raise RuntimeError("Rich replay disagreed with frozen rescue outcome")
            comparisons.append({**item,"kind":label,"base_episode_id":b["id"],"revised_episode_id":r["id"],"trace_verified":True})
    detail=ctx.store.get(ctx.cid)
    calls=detail["provider_calls"]
    usage={"calls":len(calls),"prompt_tokens":sum((c["summary"].get("usage") or {}).get("prompt_tokens",0) for c in calls),"completion_tokens":sum((c["summary"].get("usage") or {}).get("completion_tokens",0) for c in calls),"known_estimated_cost_usd":sum(c["summary"].get("estimated_cost_usd") or 0 for c in calls),"usage_unknown_calls":sum(not c["summary"].get("usage") for c in calls)}
    categories={}
    for e in detail["episodes"]:
        p=e["purpose"]
        categories[p]=categories.get(p,0)+1
    report={"id":ctx.cid+"-development-report","created_at":now(),"label":"Exploratory development evaluation","scope":"MuJoCo simulation only · instrumented-state waypoint policy · public development protocol, not an untouched final holdout","decision":"confirmation_required","decision_reasons":["Development results are used for checkpoint nomination and cannot qualify promotion.","Final registered comparison and conservative nominal non-inferiority check are required.","No hardware, Isaac or GR00T runtime has been qualified."],"manifest_sha":ctx.config["development_manifest_sha"],"protocol_sha":PROTOCOL_SHA,"outcomes_sha":outcome_sha,"baseline":summarize(baseline),"arms":arms,"selected_arm":"minimized","nominations":nominations,"nominations_frozen_at":now(),"regressions":regressions,"rescues":rescues,"comparisons":comparisons,"limitations":["One original Cartesian gantry and one rigid payload; no robot hardware or real-world reliability inference.","The waypoint MLP uses privileged instrumented state; this is not visual grasping or GR00T adaptation.","All arms match 24 successful demonstrations and 600 Adam updates; acquisition/search/provider costs differ.","Five optimization seeds share one fixed base and one curriculum per arm; dataset-selection uncertainty is not estimated.","Development families exclude two registered compositional regions. Fresh-seed results alone do not establish new-family generalization.","Bootstrap method summaries are descriptive; finite-n paired bounds govern any later nominal gate."],"resources":{"simulation_episodes":len(detail["episodes"]),"episodes_by_purpose":categories,"training_seconds":sum(r["elapsed_seconds"] for r in runs),"nvidia_inference":usage,"budget_claim":"Matched training examples and optimizer updates only; full acquisition costs shown separately"}}
    report["artifact_sha"]=ctx.store.artifact(report)
    return report
