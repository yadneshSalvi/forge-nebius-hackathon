"""Explicit bounded diagnostic CLI; no original campaign or ledger mutation."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control.incident import Incidents
from control.store import Store

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--source-episode", required=True)
    parser.add_argument("--factor", required=True)
    parser.add_argument("--value", required=True, type=float)
    parser.add_argument("--nuisance-repeats", type=int, default=20)
    parser.add_argument("--key", required=True)
    parser.add_argument("--planner-receipt-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manager = Incidents(Store())
    job, created = manager.create({"campaign_id": args.campaign, "source_episode_id": args.source_episode,
                                   "factor": args.factor, "value": args.value, "nuisance_repeats": args.nuisance_repeats,
                                   "planner_receipt_sha": args.planner_receipt_sha}, args.key)
    if created:
        manager.run(job["id"])
    result = manager.get(job["id"])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(manager.export(job["id"]))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "completed" else 1

if __name__ == "__main__":
    raise SystemExit(main())
