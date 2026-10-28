"""Install hash-verified recorded evidence without network, inference or physics."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control.sample import unpack
from control.store import ROOT,Store

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,default=ROOT/"evidence/recorded-sample.tar.xz")
    parser.add_argument("--data",type=Path)
    parser.add_argument("--sha256")
    args=parser.parse_args()
    try:print(json.dumps(unpack(args.archive,Store(args.data),args.sha256),sort_keys=True))
    except (OSError,ValueError,KeyError,EOFError) as exc:
        print(json.dumps({"imported":False,"error":str(exc)}));return 1
    return 0

if __name__=="__main__":raise SystemExit(main())
