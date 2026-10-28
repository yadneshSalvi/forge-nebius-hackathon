"""Final analysis using only preregistered development nominations."""
import numpy as np
from .protocol import ARMS, PROTOCOL_SHA
from .statistics import summarize, paired, seed_cluster_interval
from .store import now

def make_final_report(ctx,parent,manifest,rows,exposure):
    order=[s["scenario_id"] for s in manifest["scenarios"]]
    scene_map={s["scenario_id"]:s for s in manifest["scenarios"]}
    rows=sorted(rows,key=lambda r:(r["scenario_id"],r["arm"],r["training_seed"] or 0))
    lookup={(r["arm"],r["training_seed"],r["scenario_id"]):r for r in rows}
    base=[lookup[("base",None,s)] for s in order]
    nominations=parent["report"]["nominations"]
    arms=[]
    selected_rows={}
    for arm,label in ARMS.items():
        runs=[r for r in parent["training"]["runs"] if r["arm"]==arm]
        seed_reports,arrays=[],[]
        for run in runs:
            outcome=[lookup[(arm,run["seed"],s)] for s in order]
            result={**summarize(outcome),**paired([o["success"] for o in base],[o["success"] for o in outcome]),"seed":run["seed"],"checkpoint_sha":run["checkpoint_sha"]}
            result.update(interval=None,delta_interval=None,nominal_lower_95=None,interval_method="Descriptive fixed 200/300 stratified mixture; no pooled binomial interval")
            result["strata"]={}
            for stratum in ("nominal","shifted"):
                keep=lambda o: (o["family"]=="nominal")==(stratum=="nominal")
                b=[o for o in base if keep(o)];r=[o for o in outcome if keep(o)]
                result["strata"][stratum]={**summarize(r),**paired([o["success"] for o in b],[o["success"] for o in r])}
            seed_reports.append(result)
            arrays.append([o["success"] for o in outcome])
        nominee=[lookup[(arm,nominations[arm]["seed"],s)] for s in order]
        selected_rows[arm]=nominee
        nominal_b=[o for o in base if o["family"]=="nominal"]
        nominal_r=[o for o in nominee if o["family"]=="nominal"]
        nominal={**summarize(nominal_r),**paired([o["success"] for o in nominal_b],[o["success"] for o in nominal_r]),"checkpoint_seed":nominations[arm]["seed"]}
        counts={k:sum(s["paired"][k] for s in seed_reports) for k in ("rescued","regressed","both_success","both_failure")}
        families=[]
        for family in sorted({o["family"] for o in base}):
            b=[o for o in base if o["family"]==family];r=[o for o in nominee if o["family"]==family]
            families.append({"family":family,"baseline":summarize(b),**summarize(r),**paired([o["success"] for o in b],[o["success"] for o in r])})
        aggregate=summarize([o for o in rows if o["arm"]==arm])
        aggregate["interval"]=None
        aggregate["interval_method"]="Descriptive fixed 200/300 stratified mixture; see separate nominal and shifted intervals"
        shifted_b=[o for o in base if o["family"]!="nominal"];shifted_r=[o for o in nominee if o["family"]!="nominal"]
        shifted={**summarize(shifted_r),**paired([o["success"] for o in shifted_b],[o["success"] for o in shifted_r])}
        arms.append({"name":arm,"label":label,**aggregate,"delta":float(np.mean(arrays)-np.mean([o["success"] for o in base])),"delta_interval":None,"delta_interval_method":"Descriptive pooled point estimate only; fixed strata and repeated training seeds are not IID trials","paired":counts,"paired_denominator":len(order)*len(runs),"nominal":nominal,"shifted":shifted,"seeds":seed_reports,"families":families,"nomination":nominations[arm]})
    candidate=selected_rows["minimized"]
    shifted_candidate=[o["success"] for o in candidate if o["family"]!="nominal"]
    comparisons={}
    for arm,other in {"base":base,"random":selected_rows["random"],"source":selected_rows["source"]}.items():
        comparisons[arm]=paired([o["success"] for o in other if o["family"]!="nominal"],shifted_candidate)
    candidate_nominal=next(a["nominal"] for a in arms if a["name"]=="minimized")
    protected_failures=sum(o["metrics"]["forbidden_contact_steps"]>0 for o in candidate)
    checks={"shifted_improvement_lower_bound_positive":comparisons["base"]["delta_interval"][0]>0,
        "at_least_ten_points_above_both_nominated_comparators":all(comparisons[a]["delta"]>=.10 for a in ("random","source")),
        "paired_lower_bound_positive_against_both_comparators":all(comparisons[a]["delta_interval"][0]>0 for a in ("random","source")),
        "nominal_one_sided_95_lower_above_minus_three_points":candidate_nominal["nominal_lower_95"]>-.03,
        "no_observed_critical_protected_contact":protected_failures==0}
    decision="simulation_candidate" if all(checks.values()) else "do_not_promote"
    reasons=[name.replace("_"," ")+": "+("passed" if value else "not met") for name,value in checks.items()]
    regressions=[]
    rescues=[]
    for arm,outcome in selected_rows.items():
        for b,r in zip(base,outcome):
            if b["success"] and not r["success"]:
                regressions.append({"scenario_id":r["scenario_id"],"family":r["family"],"arm":arm,"seed":r["training_seed"],"base_episode_id":b["episode_id"],"revised_episode_id":r["episode_id"],"terminal_reason":r["terminal_reason"],"checkpoint_sha":r["checkpoint_sha"]})
            elif not b["success"] and r["success"]:
                rescues.append({"scenario_id":r["scenario_id"],"family":r["family"],"arm":arm,"seed":r["training_seed"],"base_episode_id":b["episode_id"],"revised_episode_id":r["episode_id"],"terminal_reason":r["terminal_reason"],"checkpoint_sha":r["checkpoint_sha"]})
    rich=[]
    for kind,group in (("regression",regressions),("rescue",rescues)):
        selected=sorted(group,key=lambda r:(r["arm"]!="minimized",r["scenario_id"]))[:2]
        for item in selected:
            scene=scene_map[item["scenario_id"]]
            checkpoint=ctx.store.read_artifact(item["checkpoint_sha"])
            b=ctx.run(scene,ctx.base,purpose="registered_comparison",trace=True)
            r=ctx.run(scene,checkpoint,purpose="registered_comparison",trace=True)
            if kind=="regression" and not(b["success"] and not r["success"]):raise RuntimeError("Final regression replay disagreed with frozen outcome")
            if kind=="rescue" and not(not b["success"] and r["success"]):raise RuntimeError("Final rescue replay disagreed with frozen outcome")
            rich.append({**item,"kind":kind,"base_episode_id":b["id"],"revised_episode_id":r["id"],"trace_verified":True})
    report={"id":ctx.cid+"-registered-report","created_at":now(),"label":"Independently registered confirmation","scope":"500 registered MuJoCo scenarios × 16 frozen checkpoints. 200 IID nominal + 300 IID shifted-mixture draws. Simulation only.","decision":decision,"decision_reasons":reasons,"promotion_checks":checks,"manifest_sha":ctx.config["registered_manifest_sha"],"protocol_sha":PROTOCOL_SHA,"evaluation_source_sha":ctx.config["evaluation_source_sha"],"outcomes_sha":ctx.store.artifact({"manifest_sha":ctx.config["registered_manifest_sha"],"rows":rows}),"baseline":summarize(base),"arms":arms,"selected_arm":"minimized","nominations":nominations,"nominations_frozen_at":parent["report"]["nominations_frozen_at"],"shifted_comparisons":comparisons,"regressions":regressions,"comparisons":[],"exposure":exposure,"parent_campaign_id":parent["id"],"evaluation_campaign_id":ctx.cid,"limitations":parent["report"]["limitations"]+["Checkpoint nominations were fixed using development data before this final manifest was opened.","Finite registered simulator evidence does not certify hardware safety or generalize to unseen embodiments."],"resources":{"registered_scenarios":500,"frozen_checkpoints":16,"simulation_episodes":len(rows),"workers":ctx.config["workers"],"budget_claim":"Matched training data and updates; registered evaluation paired identically; acquisition costs remain in the linked development report"}}
    report["comparisons"]=rich
    report["rescues"]=rescues
    report["resources"]["rich_replay_episodes"]=2*len(rich)
    report["baseline"]["interval"]=None
    report["baseline"]["interval_method"]="Descriptive fixed 200/300 stratified mixture; no pooled binomial interval"
    report["baseline"]["strata"]={"nominal":summarize([o for o in base if o["family"]=="nominal"]),"shifted":summarize([o for o in base if o["family"]!="nominal"])}
    report["artifact_sha"]=ctx.store.artifact(report)
    return report
