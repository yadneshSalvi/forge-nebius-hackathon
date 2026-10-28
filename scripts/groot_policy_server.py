#!/usr/bin/env python3
"""GPU-only official policy wrapper with identity binding and deterministic reset."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import random
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.groot.contract import canonical, digest, load_contract, preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Server identity output already exists; use a new attempt path")
    contract = load_contract()
    report = preflight(args.source_root, args.checkpoint_root, args.cache_root, contract)
    if not report["ready_for_runtime_probe"]:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+"\n")
        raise SystemExit("GPU preflight failed; no policy was loaded")
    sys.path.insert(0, str(args.source_root.resolve()))
    import numpy as np
    import torch
    from gr00t.policy.gr00t_policy import Gr00tPolicy, Gr00tSimPolicyWrapper
    from gr00t.policy.server_client import PolicyServer

    # Same official model and simulation adapter as the documented server.
    raw = Gr00tPolicy(embodiment_tag="LIBERO_PANDA", model_path=str(args.checkpoint_root/"libero_10"), device="cuda:0", strict=True)
    policy = Gr00tSimPolicyWrapper(raw, strict=True)
    identity = {"schema":"forge.groot-server/v1", "server_instance":uuid.uuid4().hex,
        "contract_sha256":digest(contract), "preflight":report,
        "forge_adapter_lock":report["forge_adapter_lock"],
        "source_revision":contract["source"]["revision"],
        "checkpoint_revision":contract["checkpoint"]["revision"],
        "checkpoint_files":report["checks"]["checkpoint"]["files"],
        "model_class":type(raw.model).__name__,
        "parameter_count":sum(p.numel() for p in raw.model.parameters()),
        "embodiment":"LIBERO_PANDA", "device":str(next(raw.model.parameters()).device),
        "host":"127.0.0.1", "port":5555, "qualified":False,
        "scope":"Actual model loaded; closed-loop, training, replay and operations gates remain separate."}
    if identity["model_class"] != "Gr00tN1d7" or identity["device"] != "cuda:0":
        raise ValueError("Loaded model/device does not match the qualified candidate contract")
    identity["identity_sha256"] = digest(identity)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(identity))

    def reset_seed(seed):
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("Seed must be uint32")
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        policy.reset()
        states = {"python":repr(random.getstate()), "numpy":np.random.get_state()[1].tolist(),
                  "torch_cpu":torch.get_rng_state().tolist(),
                  "torch_cuda":[s.tolist() for s in torch.cuda.get_rng_state_all()]}
        return {"seed":seed, "server_instance":identity["server_instance"], "rng_state":states,
                "rng_sha256":digest(states), "deterministic_replay_qualified":False}

    with PolicyServer(policy, host="127.0.0.1", port=5555, api_token=os.environ.get("FORGE_GR00T_API_TOKEN")) as server:
        server.register_endpoint("forge_identity", lambda: identity, requires_input=False)
        server.register_endpoint("forge_reset", reset_seed)
        server.run()


if __name__ == "__main__":
    main()
