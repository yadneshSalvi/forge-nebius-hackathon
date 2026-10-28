"""Bounded local campaign worker; stale generations cannot commit results."""
import os
import sys
import traceback
from .store import Store, FenceLost, PauseRequested
from .runner import RunContext
from .lineage import source_lock

def main():
    cid,generation,token=sys.argv[1],int(sys.argv[2]),sys.argv[3]
    store=Store()
    try:
        store.claim(cid,generation,token,os.getpid())
        ctx=RunContext(store,cid,generation)
        if ctx.config["source_sha"]!=source_lock()["sha256"]:raise ValueError("Scientific source lock changed; create a new campaign")
        if ctx.campaign["operation"]=="challenge":
            from .challenge import challenge
            challenge(ctx)
        elif ctx.campaign["operation"]=="train":
            from .training import train
            train(ctx)
        else:
            from .discovery import discover
            discover(ctx)
    except PauseRequested as exc:
        state=store.get(cid,detail=False)
        store.finish(cid,generation,"paused",state["stage"],error=str(exc))
    except FenceLost:
        print("Generation fenced; no partial task verdict committed",flush=True)
    except Exception as exc:
        traceback.print_exc()
        try:
            state=store.get(cid,detail=False)
            store.finish(cid,generation,"failed",state["stage"],error=f"{type(exc).__name__}: {exc}"[:1000])
        except FenceLost:pass

if __name__=="__main__":main()
