"""Actual NumPy adaptation from one frozen base checkpoint."""
import numpy as np
from engine import train_policy, validate_checkpoint
from .protocol import TRAINING_SEEDS, TRAINING_BUDGET, PROTOCOL_SHA
from .store import now
from .lineage import source_lock

def train(ctx):
    curriculum=ctx.state().get("curriculum")
    if not curriculum or curriculum["status"]!="validated":raise ValueError("Validated successful demonstrations required")
    runs=ctx.state().get("training",{}).get("runs",[])
    for arm in curriculum["arms"]:
        demos=[ctx.store.read_artifact(sha) for sha in arm["demo_shas"]]
        if len(demos)!=24:raise ValueError("Matched 24-demonstration budget violated")
        for seed in TRAINING_SEEDS:
            ctx.boundary()
            existing=next((r for r in runs if r["arm"]==arm["name"] and r["seed"]==seed),None)
            if existing:
                validate_checkpoint(ctx.store.read_artifact(existing["checkpoint_sha"]))
                continue
            checkpoint=train_policy(demos,ctx.base,seed=seed,budget={k:TRAINING_BUDGET[k] for k in ("steps","batch_size","learning_rate")},policy_id=f"{arm['name']}-waypoint-seed-{seed}")
            sha=ctx.store.artifact(checkpoint)
            change=float(np.sqrt(sum(np.sum((np.asarray(checkpoint["weights"][key])-np.asarray(ctx.base["weights"][key]))**2) for key in checkpoint["weights"])))
            detail=checkpoint["training"]
            runs.append({"arm":arm["name"],"label":arm["label"],"seed":seed,"policy_id":checkpoint["policy_id"],"checkpoint_sha":sha,"checkpoint_hash":checkpoint["checkpoint_hash"],"base_checkpoint_sha":ctx.config["base_checkpoint_sha"],"base_checkpoint_hash":ctx.base["checkpoint_hash"],"examples":24,"steps":detail["steps"],"initial_loss":detail["initial_loss"],"final_loss":detail["final_loss"],"elapsed_seconds":detail["elapsed_seconds"],"weight_change_l2":change,"manifest_hash":detail["manifest_hash"],"final_weights_hash":detail.get("final_weights_hash"),"loss_curve":detail["loss_curve"]})
            ctx.update("training",len(runs),15,f"Trained {arm['label']} · seed {seed}",training={"status":"running","runs":runs})
    training={"status":"completed","runs":runs,"weights_frozen_at":now(),"source_sha":source_lock()["sha256"],"protocol_sha":PROTOCOL_SHA,"initialization":"Same frozen base weights for all 15 adaptations; optimizer state reset equally; each update bootstraps 24 examples with replacement"}
    ctx.update("evaluation",0,16,"All weights frozen; evaluating the pre-generated development manifest",training=training)
    from .evaluation import evaluate_development
    report=evaluate_development(ctx,runs)
    ctx.store.finish(ctx.cid,ctx.gen,"completed","report",{"training":training,"report":report})
