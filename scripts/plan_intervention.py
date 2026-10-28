#!/usr/bin/env python3
"""Preview, request, then explicitly accept one source-bound intervention."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control.incident import Incidents
from control.intervention_planner import plan, preview, review_plan, revalidate_retained_response
from control.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "propose"):
        child = commands.add_parser(name)
        child.add_argument("--campaign", required=True)
        child.add_argument("--source", required=True)
        child.add_argument("--provider", required=True, choices=("fireworks", "nebius"))
        child.add_argument("--output", type=Path)
        if name == "propose":
            child.add_argument("--idempotency-key", required=True)
            child.add_argument("--qualify-nebius", action="store_true")
            child.add_argument("--nominal-ceiling-usd", type=float, default=.15)
    accept = commands.add_parser("accept")
    accept.add_argument("--receipt-sha", required=True)
    accept.add_argument("--idempotency-key", required=True)
    accept.add_argument("--nuisance-repeats", type=int, default=20, choices=range(1,21))
    accept.add_argument("--run", action="store_true", help="Run locally now; otherwise return the queued job")
    review = commands.add_parser("review")
    review.add_argument("--receipt-sha", required=True)
    review.add_argument("--decision", required=True, choices=("accept","reject"))
    review.add_argument("--reason", required=True)
    revalidate = commands.add_parser("revalidate")
    revalidate.add_argument("--original-receipt-sha", required=True)
    revalidate.add_argument("--output", type=Path)
    args = parser.parse_args()
    store = Store(args.data)
    if args.command == "preview":
        result = preview(store, args.campaign, args.source, args.provider)
    elif args.command == "propose":
        result = plan(store, args.campaign, args.source, args.provider, args.idempotency_key, allow_nebius=args.qualify_nebius, nominal_ceiling_usd=args.nominal_ceiling_usd)
    elif args.command == "review":
        result = review_plan(store, args.receipt_sha, args.decision, args.reason)
    elif args.command == "revalidate":
        result = revalidate_retained_response(store, args.original_receipt_sha)
    else:
        receipt = store.read_artifact(args.receipt_sha)
        if receipt.get("status") != "validated":
            raise ValueError("Only a validated exact-source proposal can be accepted")
        manager = Incidents(store)
        request = {k: receipt[k] for k in ("campaign_id", "source_episode_id", "factor", "value")}
        request.update(nuisance_repeats=args.nuisance_repeats, planner_receipt_sha=args.receipt_sha)
        result, new = manager.create(request, args.idempotency_key)
        if args.run and new:
            manager.run(result["id"])
            result = manager.get(result["id"])
    output = getattr(args, "output", None)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
        print(json.dumps({"status": result.get("status", "preview"), "receipt_sha": result.get("receipt_sha"), "output": str(output.resolve()), "estimated_cost_usd": result.get("estimated_cost_usd"), "estimated_request_bound_usd": result.get("estimated_request_bound_usd")}))
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if result.get("status") == "rejected" else 0


if __name__ == "__main__":
    raise SystemExit(main())
