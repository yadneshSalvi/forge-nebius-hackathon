"""Matched two-cluster corrective data; joint successful-expert acceptance."""
from engine import FACTOR_SPEC, expert_policy, demo_from_episode
from .protocol import ARMS
from .acquisition import curriculum_candidates

def acquire_matched_boundaries(ctx,counterexample,retained):
    boundaries=[counterexample]+counterexample["secondary_boundaries"]
    if len(boundaries)!=2:raise ValueError("V2 requires exactly two confirmed measured failure clusters")
    proposals={arm:curriculum_candidates(arm,FACTOR_SPEC,{},ctx.config["seed"]+12050,80,boundaries=boundaries) for arm in ("source","minimized")}
    accepted={arm:[] for arm in proposals}
    attempts={arm:[] for arm in proposals}
    counts=[0,0]
    pairing,refs=[],[]
    for i,(left,right) in enumerate(zip(proposals["source"],proposals["minimized"])):
        cluster=i%2
        if counts[cluster]>=8:continue
        causal={k for k,v in FACTOR_SPEC.items() if abs(boundaries[cluster]["minimized_params"][k]-v["nominal"])>1e-8}
        if left["seed"]!=right["seed"] or any(left["parameters"][k]!=right["parameters"][k] for k in FACTOR_SPEC if k not in causal):raise ValueError("Paired background/nuisance mismatch")
        results={arm:ctx.run(scene,expert_policy(),purpose=f"expert_{arm}",trace=True) for arm,scene in (("source",left),("minimized",right))}
        passes=all(r["valid"] and r["success"] for r in results.values())
        pairing.append({"cluster":cluster,"causal_factors":sorted(causal),"nuisance_seed":left["seed"],"accepted":passes,"source_episode_id":results["source"]["id"],"minimized_episode_id":results["minimized"]["id"],"source_parameters":left["parameters"],"minimized_parameters":right["parameters"]})
        for arm,r in results.items():
            attempts[arm].append({"episode_id":r["id"],"success":r["success"],"valid":r["valid"],"terminal_reason":r["terminal_reason"],"included":passes,"cluster":cluster,"rejection_reason":None if passes else "At least one member of the matched expert pair did not pass"})
            if passes:
                demo=demo_from_episode(r["episode"],include_episode=True)
                accepted[arm].append(demo)
                refs.append({"id":demo["demo_id"],"episode_id":r["id"],"arm":arm,"split":"training","source":f"Matched contact-expert pair · {ARMS[arm]}","success":True,"trajectory_sha":ctx.store.artifact(demo),"scenario":r["scenario"],"cluster":cluster})
        if passes:counts[cluster]+=1
        ctx.update("curriculum",16+2*sum(counts),48,f"Matched boundary curricula: {counts[0]}/8 clearance and {counts[1]}/8 grasp pairs")
        if counts==[8,8]:break
    if counts!=[8,8]:raise RuntimeError("Matched acquisition exhausted 80 candidate pairs before both clusters reached eight successful pairs")
    arms=[]
    for arm in ("source","minimized"):
        demos=retained+accepted[arm]
        arms.append({"name":arm,"label":ARMS[arm],"demo_ids":[d["demo_id"] for d in demos],"demo_shas":[ctx.store.artifact(d) for d in demos],"accepted":24,"rejected":len(attempts[arm])-16,"retained_nominal":8,"corrective":16,"acquisition_episodes":len(attempts[arm]),"attempts":attempts[arm],"cluster_allocation":[8,8]})
    return arms,refs,pairing
