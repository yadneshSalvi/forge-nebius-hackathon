"""Same-expert, same-budget acquisition with complete failed-attempt accounting."""
from engine import FACTOR_SPEC, expert_policy, demo_from_episode, render_episode
from .protocol import ARMS, TRAINING_BUDGET
from .acquisition import curriculum_candidates
from . import providers
from .paired_acquisition import acquire_matched_boundaries

def raw_episode(ctx, episode_id):
    decorated=ctx.store.episode(episode_id)
    return ctx.store.read_artifact(decorated["artifact_sha"])

def acquire_curriculum(ctx,counterexample,model):
    if ctx.state().get("curriculum"):
        model=visual_evidence(ctx,counterexample,model)
        ctx.store.finish(ctx.cid,ctx.gen,"ready","curriculum",{"model_evidence":model})
        return
    retained=ctx.base_demos()[:8]
    nominal_refs=[]
    for d in retained:
        nominal_refs.append({"id":d["demo_id"],"source":"Retained base expert trajectory","split":"training","success":True,"trajectory_sha":ctx.store.artifact(d),"episode_id":None,"arm":"all","scenario":d["scenario"]})
    arms,demonstrations=[],list(nominal_refs)
    for arm_index,(arm,label) in enumerate({"random":ARMS["random"]}.items()):
        center=counterexample["minimized_params"] if arm=="minimized" else counterexample["source_params"]
        proposals=curriculum_candidates(arm,FACTOR_SPEC,center,ctx.config["seed"]+12000+arm_index,80)
        corrective,attempts=[],[]
        for scene in proposals:
            result=ctx.run(scene,expert_policy(),purpose=f"expert_{arm}",trace=True)
            attempts.append({"episode_id":result["id"],"success":result["success"],"valid":result["valid"],"terminal_reason":result["terminal_reason"]})
            if result["valid"] and result["success"]:
                demo=demo_from_episode(result["episode"],include_episode=True)
                sha=ctx.store.artifact(demo)
                corrective.append(demo)
                demonstrations.append({"id":demo["demo_id"],"episode_id":result["id"],"arm":arm,"split":"training","source":f"Same contact expert · {label}","success":True,"trajectory_sha":sha,"scenario":scene})
            ctx.update("curriculum",arm_index*16+len(corrective),48,f"{label}: {len(corrective)}/16 validated corrections; {len(attempts)-len(corrective)} rejected")
            if len(corrective)==16:break
        if len(corrective)!=16:raise RuntimeError(f"{label} exhausted 80 acquisition attempts without 16 successful corrections; training unavailable")
        demo_shas=[ctx.store.artifact(d) for d in retained+corrective]
        arms.append({"name":arm,"label":label,"demo_ids":[d["demo_id"] for d in retained+corrective],"demo_shas":demo_shas,"accepted":24,"rejected":len(attempts)-16,"retained_nominal":8,"corrective":16,"acquisition_episodes":len(attempts),"attempts":attempts})
    paired_arms,paired_demos,pairing=acquire_matched_boundaries(ctx,counterexample,retained)
    arms.extend(paired_arms)
    demonstrations.extend(paired_demos)
    curriculum={"id":ctx.cid+"-curriculum","base_checkpoint_sha":ctx.config["base_checkpoint_sha"],"base_manifest_sha":ctx.base_index["manifest_sha"],"arms":arms,"demonstrations":demonstrations,"excluded_splits":["validation","confirmation","sealed","challenge","tall_obstacle_low_friction","yaw_offset_composition"],"training_budget":TRAINING_BUDGET,"status":"validated","scope":"Instrumented-state waypoint labels from successful physical contact trajectories; not a vision policy"}
    curriculum["paired_acquisition_sha"]=ctx.store.artifact(pairing)
    curriculum["failure_clusters"]=[counterexample["terminal_reason"]]+[b["terminal_reason"] for b in counterexample["secondary_boundaries"]]
    curriculum["design"]="Two failure clusters, eight corrections per cluster. Source/minimized curricula use matched backgrounds and nuisance draws; only causal-coordinate placement differs. A pair enters both datasets only if both expert trajectories pass."
    ctx.update("visual_analysis",48,48,"Together Super VL is inspecting actual MuJoCo render frames",curriculum=curriculum)
    model=visual_evidence(ctx,counterexample,model)
    ctx.store.finish(ctx.cid,ctx.gen,"ready","curriculum",{"curriculum":curriculum,"model_evidence":model})

def visual_evidence(ctx,counterexample,model):
    if not model.get("visual") and ctx.config.get("live_models",True):
        ctx.boundary()
        original=raw_episode(ctx,counterexample["source_episode_id"])
        reduced=raw_episode(ctx,counterexample["minimized_episode_id"])
        folder=ctx.store.path/"renders"/ctx.cid
        image_paths=[folder/"source.png",folder/"minimized.png"]
        rendered=[render_episode(e,p) for e,p in zip([original,reduced],image_paths)]
        model={**model,"visual":providers.analyze_render(ctx.store,ctx.cid,ctx.gen,image_paths,[{"frame":i,"recorded_time":r["time"],"episode_id":r["episode_id"],"source":r["source"]} for i,r in enumerate(rendered)])}
        model["visual"]["image_urls"]=[f"/api/campaigns/{ctx.cid}/images/{p.name}" for p in image_paths]
        ctx.update("curriculum",48,48,"All curricula validated; review fixed training budget",model_evidence=model)
    return model
