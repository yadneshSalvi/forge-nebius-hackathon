"""Coverage and actual model-guided finite development search."""
from engine import FACTOR_SPEC, task_spec
from .protocol import finite_pool, scenario
from .acquisition import coverage
from . import providers

def discover(ctx):
    seed,budget=ctx.config["seed"],ctx.config["search_budget"]
    trials=[]
    for i,p in enumerate(coverage(FACTOR_SPEC)):
        trials.append(ctx.run(scenario(p,seed*101+i,family="coverage"),purpose="discovery",trace=True))
        ctx.update("discovery",len(trials),budget,"Running registered coverage trials")
    model=ctx.state().get("model_evidence",{})
    pool=finite_pool(FACTOR_SPEC,seed+1001,48)
    if not model.get("planner"):
        ctx.update("planning",len(trials),budget,"Nemotron Ultra is ranking the finite development candidate pool")
        evidence=[{"id":r["id"],"parameters":r["scenario"]["parameters"],"success":r["success"],"terminal_reason":r["terminal_reason"],"metrics":r["episode"].get("metrics",{})} for r in trials]
        prior_id=ctx.config.get("development_parent_id")
        if prior_id:
            prior=ctx.store.get(prior_id,detail=False)
            old_rows=ctx.store.read_artifact(prior["report"]["outcomes_sha"])["rows"]
            nominated=prior["report"]["nominations"]["minimized"]["seed"]
            for row in old_rows:
                if row["arm"]=="minimized" and row["training_seed"]==nominated and not row["success"]:
                    old=ctx.store.episode(row["episode_id"])
                    evidence.append({"id":row["episode_id"],"parameters":old["scenario"]["parameters"],"success":False,"terminal_reason":row["terminal_reason"],"metrics":old["metrics"],"policy_action":old["policy_action"],"scope":"Previously exposed V1 development failure, not final evaluation"})
        if ctx.config.get("live_models",True):
            ctx.boundary()
            planner=providers.plan_search(ctx.store,ctx.cid,ctx.gen,task_spec(),pool,evidence)
        else:
            planner={"status":"disabled_explicit_offline_run","provider":None,"model":None,"hypotheses":[],"search_order":[p["candidate_id"] for p in pool],"rationale":"Offline test order. No model inference claimed."}
        model={**model,"planner":planner}
        ctx.update("discovery",len(trials),budget,"Validated search plan; running finite candidate trials",model_evidence=model)
    ranked=model["planner"]["search_order"]
    by_id={p["candidate_id"]:p for p in pool}
    chosen=[]
    coverage_order=list(by_id)
    for i in range(budget-len(trials)):
        preferences=coverage_order if i%5==4 else ranked+coverage_order
        candidate=next(x for x in preferences if x not in chosen)
        chosen.append(candidate)
        family="reserved_coverage" if i%5==4 else "model_ranked"
        trials.append(ctx.run(scenario(by_id[candidate]["parameters"],seed*101+len(trials),family=family),purpose="discovery",trace=True))
        ctx.update("discovery",len(trials),budget,f"Completed {len(trials)} of {budget} finite search trials")
    evidence={"candidate_pool_sha":ctx.store.artifact(pool),"selected_candidate_ids":chosen,"episode_ids":[r["id"] for r in trials],"valid":sum(r["valid"] for r in trials),"failures":sum(r["valid"] and not r["success"] for r in trials),"scheduled":budget,"coverage_reserved_fraction":.2,"selection_rule":"Seven fixed controls, then model ranking with every fifth adaptive slot reserved for coverage. First confirmed clearance failure and simplest distinct grasp-failure control are reduced separately."}
    ctx.update("minimization",0,160,"Rechecking the first failure with paired nuisance draws",discovery=evidence)
    from .reduction import reduce_failure
    counterexample=ctx.state().get("counterexample") or reduce_failure(ctx,trials)
    if counterexample is None:
        ctx.store.finish(ctx.cid,ctx.gen,"completed","report",{"no_reproducible_failure":True,"decision":"No source met the registered 4/5 threshold; no curriculum or training was invented."})
        return
    if counterexample["confirmation"]["failures"] < 16:
        ctx.store.finish(ctx.cid,ctx.gen,"completed","report",{"counterexample":counterexample,"decision":"Fresh confirmation did not meet 16/20 persistence. Training is unavailable for this unconfirmed boundary."})
        return
    secondary=ctx.state().get("secondary_counterexample")
    if secondary is None:
        from .minimizer import objective
        candidates=[r for r in trials if r["valid"] and not r["success"] and r["terminal_reason"]!=counterexample["terminal_reason"]]
        candidates.sort(key=lambda r:objective(r["scenario"]["parameters"],FACTOR_SPEC))
        secondary=reduce_failure(ctx,candidates,output_key="secondary_counterexample")
    if secondary is None or secondary["confirmation"]["failures"]<16:
        raise RuntimeError("Second failure cluster did not meet fresh confirmation; V2 paired curriculum is unavailable")
    counterexample={**counterexample,"secondary_boundaries":[secondary]}
    ctx.update("curriculum",0,48,"Two measured failure boundaries confirmed",counterexample=counterexample)
    from .curriculum import acquire_curriculum
    acquire_curriculum(ctx,counterexample,model)
