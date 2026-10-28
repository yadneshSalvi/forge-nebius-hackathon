"""Fresh paired challenge; frozen weights, no learning or statistical claim."""
def challenge(ctx):
    scene=ctx.config["challenge_scenario"]
    revised=ctx.store.read_artifact(ctx.config["revised_checkpoint_sha"])
    ctx.update("challenge",0,2,"Running the frozen base on the selected condition")
    base=ctx.run(scene,ctx.base,purpose="judge_challenge_base",trace=True)
    ctx.update("challenge",1,2,"Running the nominated policy with the same nuisance seed")
    result=ctx.run(scene,revised,purpose="judge_challenge_revised",trace=True)
    data={"base_episode_id":base["id"],"revised_episode_id":result["id"],"parameters":scene["parameters"],"seed":scene["seed"],"base_success":base["success"],"revised_success":result["success"],"base_reason":base["terminal_reason"],"revised_reason":result["terminal_reason"],"label":"Fresh simulation challenge · not sealed statistical evidence","source_campaign_id":ctx.config["parent_campaign_id"],"retraining":False}
    ctx.update("challenge",2,2,"Both policies completed; inspect the measured paired outcome",challenge=data)
    ctx.store.finish(ctx.cid,ctx.gen,"completed","challenge",{"challenge":data})
