"""Package an already completed campaign and its registered confirmation offline."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control.sample import pack
from control.store import ROOT,Store

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign",required=True)
    parser.add_argument("--data",type=Path)
    parser.add_argument("--output",type=Path,default=ROOT/"evidence/recorded-sample.tar.xz")
    args=parser.parse_args()
    try:print(json.dumps(pack(Store(args.data),args.campaign,args.output),sort_keys=True))
    except (OSError,ValueError,KeyError) as exc:
        print(json.dumps({"packed":False,"error":str(exc)}));return 1
    return 0

if __name__=="__main__":raise SystemExit(main())
