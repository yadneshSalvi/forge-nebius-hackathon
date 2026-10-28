#!/usr/bin/env python3
"""Inspect/prepare a pinned GPU package. No downloads or paid jobs are automatic."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.groot.contract import guard_simulator_setup, launch_plan, load_contract, pin_backbone_cache, preflight, prepare_workspace, verify_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect")
    plan = sub.add_parser("launch-plan")
    plan.add_argument("--workspace", type=Path, required=True)
    plan.add_argument("--forge-root", type=Path, help="Forge checkout path on the future GPU host")
    plan.add_argument("--output", type=Path)
    probe = sub.add_parser("preflight")
    probe.add_argument("--source-root", type=Path)
    probe.add_argument("--checkpoint-root", type=Path)
    probe.add_argument("--cache-root", type=Path)
    probe.add_argument("--output", type=Path)
    pin = sub.add_parser("pin-backbone-cache")
    pin.add_argument("--cache-root", type=Path, required=True)
    prepare = sub.add_parser("prepare-workspace")
    prepare.add_argument("--workspace", type=Path, required=True)
    setup = sub.add_parser("setup-simulator")
    setup.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        result = load_contract()
    elif args.command == "launch-plan":
        result = launch_plan(args.workspace, args.forge_root or Path(__file__).resolve().parents[1])
    elif args.command == "pin-backbone-cache":
        result = pin_backbone_cache(args.cache_root)
    elif args.command == "prepare-workspace":
        result = prepare_workspace(args.workspace)
    elif args.command == "setup-simulator":
        guard_simulator_setup(args.source_root)
        if not verify_source(args.source_root)["ok"]:
            raise ValueError("Pinned source verification failed; setup not invoked")
        subprocess.run(["bash", "gr00t/eval/sim/LIBERO/setup_libero.sh"], cwd=args.source_root, check=True)
        result = {"status":"simulation_dependencies_installed", "qualified":False}
    else:
        result = preflight(args.source_root, args.checkpoint_root, args.cache_root)
    rendered = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if getattr(args, "output", None):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
        print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "qualified": False}))
    else:
        print(rendered, end="")
    if args.command == "preflight" and not result["ready_for_runtime_probe"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
