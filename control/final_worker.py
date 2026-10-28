"""Dedicated frozen-evaluation process; independent from development dispatch."""
import os
import sys
import traceback
from .store import Store, FenceLost, PauseRequested

def main():
    cid,gen,token=sys.argv[1],int(sys.argv[2]),sys.argv[3]
    store=Store()
    try:
        store.claim(cid,gen,token,os.getpid())
        from .final_eval import run_registered
        run_registered(store,cid,gen)
    except PauseRequested as exc:
        store.finish(cid,gen,"paused","registered_evaluation",error=str(exc))
    except FenceLost:
        print("Evaluation generation fenced; incomplete outputs not accepted",flush=True)
    except Exception as exc:
        traceback.print_exc()
        try:store.finish(cid,gen,"failed","registered_evaluation",error=f"{type(exc).__name__}: {exc}"[:1000])
        except FenceLost:pass

if __name__=="__main__":main()
