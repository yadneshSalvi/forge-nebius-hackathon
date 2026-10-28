"""Explicit local physics/base-training setup; never called by a GET endpoint."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control.store import Store, canonical
from engine.policy import bootstrap_base

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data", type=Path)
    args=parser.parse_args()
    store=Store(args.data)
    result=bootstrap_base(store.path/"base",n_demos=40,seed=17)
    index={"checkpoint_sha":store.artifact(result["checkpoint"]), "checkpoint_hash":result["checkpoint"]["checkpoint_hash"], "manifest_sha":store.artifact(result["manifest"]), "demo_shas":[store.artifact(d) for d in result["demos"]]}
    (store.path/"base"/"index.json").write_bytes(canonical(index))
    print(json.dumps({"base_ready":True,"demonstrations":len(result["demos"]),"checkpoint_sha":index["checkpoint_sha"],"training":result["checkpoint"]["training"]},indent=2))

if __name__=="__main__":main()
