"""Paired finite reduction followed by fresh nuisance-draw confirmation."""
from engine import FACTOR_SPEC
from .protocol import scenario, embargo
from .minimizer import reduce_counterexample, objective
from .statistics import wilson

def reduce_failure(ctx,trials,output_key="counterexample"):
    seed=ctx.config["seed"]
    offset=0 if output_key=="counterexample" else 10000003
    paired_seeds=[(seed*1009+70001+i+offset)%(2**32) for i in range(5)]
    source=None
    for candidate in [r for r in trials if r["valid"] and not r["success"]]:
        repeats=[ctx.run(scenario(candidate["scenario"]["parameters"],s,family="source_repeatability"),purpose="source_confirmation") for s in paired_seeds]
        if sum(r["valid"] and not r["success"] for r in repeats)>=4 and all(r["valid"] for r in repeats):
            source=candidate
            break
    if source is None:return None
    def evaluate(p,s):
        if embargo(p):return {"valid":False,"success":None,"id":"excluded-compositional-region"}
        return ctx.run(scenario(p,s,family="paired_reduction"),purpose="minimization")
    def progress(step,count):
        ctx.update("minimization",count,160,f"Tested {count} finite candidate sets with paired nuisance draws")
    reduced,steps,locality=reduce_counterexample(source["scenario"]["parameters"],FACTOR_SPEC,evaluate,paired_seeds,max_candidates=160,on_step=progress)
    confirmations=[]
    for i in range(20):
        confirmations.append(ctx.run(scenario(reduced,(seed*1013+90001+i+offset)%(2**32),split="confirmation",family="fresh_counterexample_confirmation"),purpose="fresh_confirmation"))
        ctx.update("confirmation",i+1,20,"Measuring persistence under fresh nuisance draws")
    failures=[r for r in confirmations if r["valid"] and not r["success"]]
    selected=failures[0] if failures else confirmations[0]
    nuisance_seed=selected["scenario"]["seed"]
    source_display=ctx.run(scenario(source["scenario"]["parameters"],nuisance_seed,split="confirmation",family="microscope_paired"),purpose="microscope_source",trace=True)
    reduced_display=ctx.run(scenario(reduced,nuisance_seed,split="confirmation",family="microscope_paired"),purpose="microscope_minimized",trace=True)
    before,after=objective(source["scenario"]["parameters"],FACTOR_SPEC),objective(reduced,FACTOR_SPEC)
    n=sum(r["valid"] for r in confirmations)
    counterexample={
        "terminal_reason":source["terminal_reason"],
        "source_episode_id":source_display["id"],"minimized_episode_id":reduced_display["id"],
        "discovery_source_episode_id":source["id"],"source_params":source["scenario"]["parameters"],
        "minimized_params":reduced,"steps":steps,"confirmation":{"failures":len(failures),"total":n,"scheduled":20,"interval":wilson(len(failures),n),"episode_ids":[r["id"] for r in confirmations],"independent_nuisance_draws":True},
        "locality":locality,"changed_before":before[0],"changed_after":after[0],
        "magnitude_before":before[1],"magnitude_after":after[1],"microscope_nuisance_seed":nuisance_seed,
        "source_qualification":{"paired_nuisance_seeds":paired_seeds,"failure_threshold":4,"total":5},
    }
    ctx.update("curriculum",0,48,"Fresh confirmation complete; acquiring corrective expert trajectories",**{output_key:counterexample})
    return counterexample
