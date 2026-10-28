"""Isolated local incident process. No provider, inference or training calls."""
import argparse
from .incident import Incidents
from .store import Store

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    Incidents(Store(args.data)).run(args.id)
