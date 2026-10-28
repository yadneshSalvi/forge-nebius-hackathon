"""Pinned, offline-checkable GR00T contract. Never manufactures qualification."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

MANIFEST_PATH = Path(__file__).with_name("qualification.json")
FORGE_ROOT = Path(__file__).resolve().parents[2]


def adapter_lock(root=FORGE_ROOT):
    """Bind Forge's launch/capture code as well as the pinned upstream sources."""
    names = ("integrations/__init__.py", "integrations/groot/__init__.py",
             "integrations/groot/contract.py", "integrations/groot/qualification.json",
             "scripts/groot_qualify.py", "scripts/groot_policy_server.py",
             "scripts/groot_capture_episode.py")
    files = {name: file_hash(Path(root) / name) for name in names}
    return {"files": files, "sha256": digest(files)}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def load_contract(path=MANIFEST_PATH):
    value = json.loads(Path(path).read_text())
    if value.get("schema") != "forge.groot-qualification/v1":
        raise ValueError("Unsupported GR00T qualification contract")
    if value.get("status") != "not_qualified":
        raise ValueError("The source package cannot certify a worker runtime")
    roster = value["task_roster"]
    if len(roster) != 10 or len({t["environment"] for t in roster}) != 10:
        raise ValueError("The complete, unique LIBERO-10 roster is required")
    if sum(t["partition"] == "development" for t in roster) != 6:
        raise ValueError("Six development tasks must remain distinct from four held-out tasks")
    for source in [value["source"], value["checkpoint"], value["backbone"]]:
        if len(source["revision"]) != 40 or any(c not in "0123456789abcdef" for c in source["revision"]):
            raise ValueError("Every upstream revision must be an immutable commit")
    if value["checkpoint"]["subdirectory"] != "libero_10":
        raise ValueError("LIBERO-10 checkpoint must resolve its nested directory")
    if value["modality"]["action_horizon"] != 16 or value["modality"]["executed_action_steps"] != 8:
        raise ValueError("Checkpoint output horizon and execution horizon must stay distinct")
    return value


def file_hash(path, kind="sha256"):
    path = Path(path)
    hasher = hashlib.sha256() if kind == "sha256" else hashlib.sha1()
    if kind == "git_blob_sha1":
        hasher.update(f"blob {path.stat().st_size}\0".encode())
    elif kind != "sha256":
        raise ValueError("Unknown file hash kind")
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def verify_files(root, files):
    root = Path(root).resolve()
    checks = []
    for item in files:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe contract file path")
        path = root / relative
        expected = item.get("sha256", item.get("hash"))
        check = {"path": relative.as_posix(), "expected": expected, "ok": False}
        if not path.is_file():
            check["reason"] = "missing"
        elif "bytes" in item and path.stat().st_size != item["bytes"]:
            check["reason"] = "size_mismatch"
        else:
            check["actual"] = file_hash(path, item.get("hash_kind", "sha256"))
            check["ok"] = check["actual"] == expected
            if not check["ok"]:
                check["reason"] = "hash_mismatch"
        checks.append(check)
    return {"ok": bool(checks) and all(x["ok"] for x in checks), "files": checks}


def _git_revision(root):
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=10, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def verify_source(root, contract=None):
    contract = contract or load_contract()
    source = contract["source"]
    result = verify_files(root, [{"path": p, "sha256": sha} for p, sha in source["files"].items()])
    result["revision"] = _git_revision(root)
    result["expected_revision"] = source["revision"]
    sub = source["libero_submodule"]
    result["libero_revision"] = _git_revision(Path(root) / sub["path"])
    result["expected_libero_revision"] = sub["revision"]
    clean = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=10, check=False)
    result["tracked_source_clean"] = clean.returncode == 0 and not clean.stdout.strip()
    result["ok"] &= result["revision"] == source["revision"] and result["libero_revision"] == sub["revision"] and result["tracked_source_clean"]
    return result


def verify_checkpoint(root, contract=None):
    """Root is the model repository directory, not a guessed flat checkpoint."""
    contract = contract or load_contract()
    result = verify_files(root, contract["checkpoint"]["files"])
    result["resolved_model_path"] = str(Path(root).resolve() / contract["checkpoint"]["subdirectory"])
    return result


def backbone_snapshot(cache_root, contract=None):
    contract = contract or load_contract()
    repo_cache = Path(cache_root) / "hub" / ("models--" + contract["backbone"]["repository"].replace("/", "--"))
    return repo_cache, repo_cache / "snapshots" / contract["backbone"]["revision"]


def pin_backbone_cache(cache_root, contract=None):
    """Pin upstream's revision-less backbone lookup in an isolated, verified cache."""
    contract = contract or load_contract()
    repo_cache, snapshot = backbone_snapshot(cache_root, contract)
    result = verify_files(snapshot, contract["backbone"]["files"])
    if not result["ok"]:
        raise ValueError("Pinned backbone files are absent or changed; no cache reference was written")
    ref = repo_cache / "refs" / "main"
    revision = contract["backbone"]["revision"]
    if ref.exists() and ref.read_text().strip() != revision:
        raise ValueError("This cache already tracks another backbone revision; use a fresh isolated cache")
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text(revision)
    return {"status": "cache_pinned", "revision": revision, "snapshot": str(snapshot), "qualified": False}


def prepare_workspace(workspace):
    workspace = Path(workspace).resolve()
    if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
        raise ValueError("GPU preparation requires an empty dedicated workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    marker = {"schema": "forge.groot-workspace/v1", "contract_sha256": digest(load_contract()), "workspace": str(workspace)}
    (workspace/".forge-groot-workspace.json").write_bytes(canonical(marker))
    return {"status": "empty_workspace_prepared", "workspace": str(workspace), "qualified": False}


def guard_simulator_setup(source_root, *, account_home=None):
    source_root = Path(source_root).resolve()
    marker = source_root.parent/".forge-groot-workspace.json"
    if not marker.is_file() or json.loads(marker.read_text()).get("contract_sha256") != digest(load_contract()):
        raise ValueError("Source must live in a dedicated prepared Forge GPU workspace")
    simulation = source_root/"gr00t/eval/sim/LIBERO/libero_uv"
    config = Path(account_home or Path.home())/".libero"
    if simulation.exists() or config.exists() or simulation.is_symlink() or config.is_symlink():
        raise ValueError("Upstream setup would replace an existing simulation environment or .libero config; use a fresh disposable GPU account/container")
    return {"status": "setup_paths_clear", "qualified": False}


def validate_observation(observation, contract=None):
    """Validate actual flat simulation-policy input, with explicit batch/time axes."""
    import numpy as np
    spec = (contract or load_contract())["modality"]
    expected = set(spec["video_keys"] + spec["state_keys"] + [spec["language_key"]])
    if set(observation) != expected:
        raise ValueError("Observation keys do not match the pinned LIBERO_PANDA interface")
    for key in spec["video_keys"]:
        array = observation[key]
        if not isinstance(array, np.ndarray) or array.dtype != np.uint8 or array.shape != tuple(spec["video_shape"]):
            raise ValueError(f"{key} must be uint8 [1,1,256,256,3] RGB")
    for key, dimension in zip(spec["state_keys"], spec["state_dimensions"]):
        array = observation[key]
        if not isinstance(array, np.ndarray) or array.dtype != np.float32 or array.shape != (1, 1, dimension) or not np.isfinite(array).all():
            raise ValueError(f"{key} must be finite float32 [1,1,{dimension}]")
    text = observation[spec["language_key"]]
    if not isinstance(text, (list, tuple)) or len(text) != 1 or not isinstance(text[0], str) or not text[0].strip() or len(text[0]) > 512:
        raise ValueError("Exactly one nonempty, bounded task instruction is required")
    return {"valid": True, "policy_interface_only": True, "camera_orientation_qualified": False}


def validate_action(action, contract=None):
    import numpy as np
    spec = (contract or load_contract())["modality"]
    if set(action) != set(spec["action_keys"]):
        raise ValueError("Action keys do not match the pinned LIBERO_PANDA interface")
    for key in spec["action_keys"]:
        array = action[key]
        if not isinstance(array, np.ndarray) or array.dtype != np.float32 or array.shape != (1, spec["action_horizon"], 1) or not np.isfinite(array).all():
            raise ValueError(f"{key} must be finite float32 [1,16,1]")
    # Do not silently clamp, rescale, or discard a model's proposed actions.
    return {"valid": True, "proposed_horizon": 16, "execution_horizon": 8}


def launch_plan(workspace, forge_root, contract=None):
    contract = contract or load_contract()
    workspace, forge_root = Path(workspace).resolve(), Path(forge_root).resolve()
    source = workspace / "Isaac-GR00T"
    model = workspace / "checkpoints" / "GR00T-N1.7-LIBERO"
    cache = workspace / "hf-cache"
    sim_python = source / "gr00t/eval/sim/LIBERO/libero_uv/.venv/bin/python"
    base_env = {"HF_HOME": str(cache), "GIT_LFS_SKIP_SMUDGE": "1"}
    offline = {"HF_HOME": str(cache), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "MUJOCO_GL": "egl", "PYOPENGL_PLATFORM": "egl"}
    steps = []
    def add(name, argv, cwd=workspace, env=None, note=""):
        steps.append({"name": name, "argv": [str(x) for x in argv], "cwd": str(cwd), "environment": env or {}, "note": note, "executed": False})
    add("prepare_empty_workspace", ["python3", forge_root/"scripts/groot_qualify.py", "prepare-workspace", "--workspace", workspace], workspace.parent, note="Refuses a nonempty path; creates a dedicated workspace marker before any clone/install.")
    add("clone", ["git", "clone", "--no-checkout", contract["source"]["repository"], source], env=base_env)
    add("source_revision", ["git", "checkout", "--detach", contract["source"]["revision"]], source, base_env)
    add("libero_submodule", ["git", "submodule", "update", "--init", "external_dependencies/LIBERO"], source, base_env)
    add("server_dependencies", ["uv", "sync", "--locked", "--python", "3.12"], source, base_env, "GPU host only; FFmpeg4–7 and EGL system libraries must already be installed.")
    add("simulation_dependencies", [source/".venv/bin/python", forge_root/"scripts/groot_qualify.py", "setup-simulator", "--source-root", source], source, base_env, "Guard refuses an existing simulation venv or account .libero config before invoking upstream. Capture resolved simulation pip freeze afterwards.")
    add("download_checkpoint", ["uv", "run", "--no-sync", "hf", "download", contract["checkpoint"]["repository"], "--revision", contract["checkpoint"]["revision"], "--include", *[x["path"] for x in contract["checkpoint"]["files"]], "--local-dir", model], source, base_env, "Only the seven inference files; no optimizer states or other suites. Model terms apply.")
    add("download_backbone", ["uv", "run", "--no-sync", "hf", "download", contract["backbone"]["repository"], "--revision", contract["backbone"]["revision"], "--include", *[x["path"] for x in contract["backbone"]["files"]]], source, base_env, "Requires the operator's already accepted gated model access; this package never accepts terms or authenticates an account.")
    add("pin_backbone", [source/".venv/bin/python", forge_root/"scripts/groot_qualify.py", "pin-backbone-cache", "--cache-root", cache], source)
    add("preflight", [source/".venv/bin/python", forge_root/"scripts/groot_qualify.py", "preflight", "--source-root", source, "--checkpoint-root", model, "--cache-root", cache, "--output", workspace/"preflight.json"], source, offline)
    add("server", [source/".venv/bin/python", forge_root/"scripts/groot_policy_server.py", "--source-root", source, "--checkpoint-root", model, "--cache-root", cache, "--output", workspace/"server-identity.json"], source, offline, "Loads the official Gr00tPolicy+Gr00tSimPolicyWrapper, adds bound identity/seed endpoints, and binds only127.0.0.1:5555. Own process group; remote use requires authenticated SSH. Optional FORGE_GR00T_API_TOKEN never enters receipts.")
    for task in contract["task_roster"]:
        for seed in task["qualification_nominal_seeds"]:
            add(f"capture_task_{task['index']}_seed_{seed}", [sim_python, forge_root/"scripts/groot_capture_episode.py", "--source-root", source, "--preflight", workspace/"preflight.json", "--task-index", str(task["index"]), "--seed", str(seed), "--output", workspace/f"episodes/nominal-{task['index']}-{seed}"], source, offline, "One frozen nominal qualification reset. Retain every attempt; no discovered incident or final score is implied.")
        add(f"official_nominal_comparison_{task['index']}", [sim_python, "gr00t/eval/rollout_policy.py", "--n-episodes", "20", "--policy-client-host", "127.0.0.1", "--policy-client-port", "5555", "--max-episode-steps", "720", "--env-name", task["environment"], "--n-action-steps", "8", "--n-envs", "1", "--seed", str(task["qualification_nominal_seeds"][0]), "--video-dir", workspace/f"official-nominal-videos/task-{task['index']}"], source, offline, "Separate official-driver compatibility comparison. Its autoreset schedule is not substituted for the explicit Forge seed ledger.")
    return {"schema": "forge.groot-launch-plan/v1", "contract_sha256": digest(contract), "forge_adapter_lock": adapter_lock(), "status": "not_executed", "minimum_checkpoint_and_backbone_bytes": sum(x["bytes"] for x in contract["checkpoint"]["files"] + contract["backbone"]["files"]), "workspace": str(workspace), "steps": steps, "training": "Pending valid corrections, dataset/license review, GPU qualification, measured recipe and a new independent evaluation registration. No training job is implied."}


def preflight(source_root=None, checkpoint_root=None, cache_root=None, contract=None):
    contract = contract or load_contract()
    report = {"schema": "forge.groot-preflight/v1", "contract_sha256": digest(contract), "forge_adapter_lock": adapter_lock(), "qualified": False, "checks": {}, "execution_claim": "Preflight only; no action-model inference or task episode"}
    checks = report["checks"]
    checks["platform"] = {"ok": platform.system() == "Linux" and platform.machine() == "x86_64", "system": platform.system(), "machine": platform.machine()}
    checks["python"] = {"ok": sys.version_info[:2] == (3, 12), "version": platform.python_version()}
    checks["source"] = verify_source(source_root, contract) if source_root else {"ok": False, "reason": "Source checkout not supplied"}
    checks["checkpoint"] = verify_checkpoint(checkpoint_root, contract) if checkpoint_root else {"ok": False, "reason": "Pinned checkpoint not supplied"}
    if cache_root:
        repo_cache, snapshot = backbone_snapshot(cache_root, contract)
        checks["backbone"] = verify_files(snapshot, contract["backbone"]["files"])
        ref = repo_cache / "refs/main"
        checks["backbone"]["pinned_lookup"] = ref.is_file() and ref.read_text().strip() == contract["backbone"]["revision"]
        checks["backbone"]["ok"] &= checks["backbone"]["pinned_lookup"]
    else:
        checks["backbone"] = {"ok": False, "reason": "Verified isolated backbone cache not supplied"}
    checks["cuda"] = {"ok": False, "reason": "CUDA PyTorch unavailable"}
    report["gpu_driver"] = {"available": False}
    if shutil.which("nvidia-smi"):
        driver = subprocess.run(["nvidia-smi", "--query-gpu=uuid,name,driver_version,memory.total", "--format=csv,noheader"], capture_output=True, text=True, timeout=15, check=False)
        report["gpu_driver"] = {"available": driver.returncode == 0, "devices_csv": driver.stdout[:4000]}
    if importlib.util.find_spec("torch"):
        try:
            import torch
            devices = [{"name": torch.cuda.get_device_name(i), "memory_gib": round(torch.cuda.get_device_properties(i).total_memory / 2**30, 3)} for i in range(torch.cuda.device_count())]
            checks["cuda"] = {"ok": torch.cuda.is_available() and torch.__version__.split("+")[0] == "2.9.0" and torch.version.cuda == "12.8" and bool(devices) and devices[0]["memory_gib"] >= 16, "torch": torch.__version__, "cuda": torch.version.cuda, "devices": devices, "selected_device": "cuda:0", "selected_device_index": 0}
        except Exception as exc:
            checks["cuda"]["reason"] = type(exc).__name__ + ": " + str(exc)[:300]
    checks["offline_runtime"] = {"ok": os.environ.get("HF_HUB_OFFLINE") == "1" and os.environ.get("TRANSFORMERS_OFFLINE") == "1", "reason": "Execution must resolve only the verified local model/cache files"}
    report["ready_for_runtime_probe"] = all(x["ok"] for x in checks.values())
    report["status"] = "ready_for_runtime_probe" if report["ready_for_runtime_probe"] else "blocked"
    report["pending_gates"] = [x["id"] for x in contract["gates"]]
    report["preflight_sha256"] = digest(report)
    return report


def read_preflight(path, contract=None):
    report = json.loads(Path(path).read_text())
    unsigned = {k: v for k, v in report.items() if k != "preflight_sha256"}
    if digest(unsigned) != report.get("preflight_sha256"):
        raise ValueError("Preflight evidence hash mismatch")
    if report.get("schema") != "forge.groot-preflight/v1" or report.get("contract_sha256") != digest(contract or load_contract()):
        raise ValueError("Preflight does not bind this source contract")
    required = {"platform", "python", "source", "checkpoint", "backbone", "cuda", "offline_runtime"}
    if not report.get("ready_for_runtime_probe") or set(report.get("checks", {})) != required or not all(c.get("ok") is True for c in report["checks"].values()):
        raise ValueError("GPU preflight gates have not passed")
    if report.get("forge_adapter_lock") != adapter_lock():
        raise ValueError("Forge launch/capture adapter changed after preflight")
    return report
