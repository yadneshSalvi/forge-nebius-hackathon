# GR00T / LIBERO worker qualification package

Status on 28 October 2026: **implemented launch and capture tooling; GPU runtime not qualified**. No GR00T inference, LIBERO rollout, training, model download, hardware trial or independent engineer study has been performed by Forge. The local gantry remains the working adapter. Its historical evidence and failed promotion gate are unchanged.

The machine-readable source is [qualification.json](../integrations/groot/qualification.json). The local [preflight record](../evidence/groot-local-preflight.json) is deliberately blocked: this Mac is not the specified CUDA worker. Unit tests exercise malformed observations, incompatible horizons, missing weights, tampering and unsafe setup paths with synthetic arrays. They are not policy-performance evidence.

## Exact upstream identities

| Component | Frozen identity | State |
| --- | --- | --- |
| NVIDIA Isaac-GR00T code | `944fe70c4fd54e3fcb80a7d7258a328f9c061176` | Primary source and key file digests inspected |
| Official LIBERO submodule | `8f1084e3132a39270c3a13ebe37270a43ece2a01` | Commit bound by NVIDIA's tree |
| `nvidia/GR00T-N1.7-LIBERO` | `2ea293aa20ba7cf5bbf3ba17a5fbcb1a01cbfe21`, nested `libero_10` | Seven inference-file digests locked; weights not downloaded |
| `nvidia/Cosmos-Reason2-2B` backbone | `9ce19a195e423419c349abfc86fd07178b230561` | Gated access and accepted terms not verified; weights not downloaded |
| Official example dataset reference | `IPEC-COMMUNITY/libero_10_no_noops_1.0.0_lerobot` at `e1a223d30b896c1613f270a2bfc63d382b3de7e1` | Reference only; no download or Forge corrective data |

These are read from the [pinned NVIDIA LIBERO guide](https://github.com/NVIDIA/Isaac-GR00T/blob/944fe70c4fd54e3fcb80a7d7258a328f9c061176/examples/LIBERO/README.md), [checkpoint tree](https://huggingface.co/nvidia/GR00T-N1.7-LIBERO/tree/2ea293aa20ba7cf5bbf3ba17a5fbcb1a01cbfe21/libero_10), and [backbone page](https://huggingface.co/nvidia/Cosmos-Reason2-2B). The checkpoint files total **6,914,934,160 bytes**. The required pinned backbone files add **4,888,970,298 bytes**, before environments, data, training states or evidence. Do not download them onto the current nearly full workstation.

The source repository is Apache-2.0; the LIBERO code license is MIT. Model weights use the [NVIDIA Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/), with separate backbone access. Preserve any third-party asset notices. The checked dataset metadata did not provide an explicit license field; its applicable terms and source demonstration provenance remain an acquisition gate. Forge does not redistribute model weights or accept model terms on the operator's behalf.

## Interface details that must not drift

The pinned [simulator wrapper](https://github.com/NVIDIA/Isaac-GR00T/blob/944fe70c4fd54e3fcb80a7d7258a328f9c061176/gr00t/eval/sim/LIBERO/libero_env.py) and checkpoint processor jointly define this interface:

- Two actual RGB inputs: `video.image` and `video.wrist_image`, `uint8 [1,1,256,256,3]`. The wrapper reverses **both** image axes from `agentview_image` and `robot0_eye_in_hand_image`.
- Eight scalar state dimensions: end-effector x/y/z, three orientation coordinates, and two gripper joint positions. Despite their `roll/pitch/yaw` names, the orientation coordinates are **axis-angle**, converted from an XYZW quaternion, not Euler angles.
- One exact instruction string under `annotation.human.action.task_description`.
- Seven float32 action components, each `[1,16,1]`. The checkpoint's general model horizon is 40, but its LIBERO modality emits 16. Execute the first **8** per observation, matching the official client.
- The wrapper maps the proposed gripper value through `-sign(2*a-1)`: 0 becomes close (+1), 1 becomes open (-1), and 0.5 remains zero. It does not justify interpreting the other six components directly as meters or Euler angles. Capture the loaded `OSC_POSE` controller's actual scaling/frame configuration.

The gantry uses MuJoCo 3.3.7, Python 3.11 and NumPy 2.2.6. The separate LIBERO simulation island pins MuJoCo **3.3.1**, Python **3.12**, NumPy **1.26.4**. The selected dGPU route uses CUDA 12.8 and PyTorch 2.9.0. NVIDIA recommends at least 16 GB VRAM for inference and 40 GB or more for training. These upstream recommendations are not a measured Forge capacity result. The [installation guide](https://github.com/NVIDIA/Isaac-GR00T/blob/944fe70c4fd54e3fcb80a7d7258a328f9c061176/README.md#installation) also requires FFmpeg 4–7 for the pinned torchcodec and EGL libraries for headless rendering.

## Generate a concrete launch plan

On the development machine, this writes commands only; it does not provision a host, authenticate, download or run a model:

```sh
.venv/bin/python scripts/groot_qualify.py launch-plan \
  --workspace /srv/forge-groot \
  --forge-root /srv/forge \
  --output artifacts/groot-launch-plan.json
```

Copy the Forge source package to `/srv/forge` on an actually authorized GPU host, or generate the plan there using its real paths. Each step has an exact argv, working directory, environment and `executed: false`. Use the source order; do not run unrelated steps concurrently.

The first step refuses a nonempty workspace and creates a contract-bound marker. Before invoking NVIDIA's setup script, `setup-simulator` refuses an existing `libero_uv` environment or account `.libero` configuration. The upstream script deletes both paths; Forge only permits it in a fresh disposable GPU environment. No existing account configuration is removed by the guard.

The plan pins source and LIBERO commits, uses the checked `uv.lock`, downloads only the seven LIBERO inference files and the required backbone files, then verifies every byte digest. The isolated Hugging Face cache has its backbone `main` reference explicitly bound to the frozen revision because upstream loads that backbone without a revision argument. A different pre-existing reference is refused. Inference subsequently uses `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` so it cannot silently fetch a newer backbone.

The policy server is the actual upstream `Gr00tPolicy` wrapped by `Gr00tSimPolicyWrapper`. Forge's thin launcher adds a source/checkpoint/device identity endpoint and explicit policy RNG seeding. It selects **visible `cuda:0`** and requires that device to have at least 16 GiB, recording its name and memory alongside the driver inventory. The launch plan, preflight, server and capture records also bind Forge's own adapter files; changing them invalidates an earlier preflight. These local identities are reproducibility records, not remote attestation.

The server binds **127.0.0.1:5555 only**. The upstream server has reset/kill endpoints and no authentication by default; do not expose it publicly. Keep simulation and inference on the worker, and use authenticated SSH for remote control. Optional `FORGE_GR00T_API_TOKEN` stays server-side and is never written to evidence. Authenticated remote job management and recovery remain unqualified gates.

## Capture the nominal qualification roster

The contract freezes all ten official LIBERO-10 tasks, six for future Forge adaptation and four for adaptation-held-out transfer/retention. Each has 20 explicit nominal seeds; the generated plan enumerates all **200 individual capture commands**, with unique attempt paths. It also provides a separate official-driver comparison for each of the ten tasks. The official driver's autoresets are not substituted for Forge's explicit seed ledger.

`groot_capture_episode.py` records:

- Checked policy-server identity, code/checkpoint references and initial policy RNG state.
- Exact initial simulator state, actual camera observations and proprioception at every policy query, and instruction text.
- The complete proposed 16-step chunk, each environment command recomputed through the pinned gripper transformation, control-step simulator states, and stock LIBERO predicate values. The command is not a measured actuator torque. A separate `last_solver_actuator_control` records `sim.data.ctrl` after each environment step; direct command capture and closed-loop compatibility still require the GPU qualification run.
- Actual attempt status, elapsed time, all partial files and file/evidence digests. Existing attempts cannot be overwritten. Changed server identities fence the attempt.

A 720-step task timeout is a task failure. A returned invalid action is a policy failure. Canceled and incomplete infrastructure attempts have null success and must remain separate from statistical denominators. Runtime exception attribution still requires inspection before any study; the collector does not decide a release. It records control-step states, not an independently reconstructed contact oracle. Enhanced Forge contact/release predicates are a future protocol and must never be labeled the published LIBERO metric.

Initial-state replay is a qualification target. **Mid-episode simulator/controller/policy restoration is not supported or claimed.** Captured state alone is not proof of deterministic restoration. A genuine passing and failing episode must be independently replayed through the same pinned adapter before enabling incident forks.

The bowl-and-drawer task is only the first **candidate** in a frozen priority order. It is not a discovered failure. Qualify nominal competence first; the proposed gate is at least 16/20 nominal successes. Register valid perturbation ranges and collision/feasibility checks before searching development evidence. Select a replacement only using the fixed development priority rule, never final tests. The supplied model has already seen LIBERO; the four tasks are held out from Forge adaptation, not necessarily upstream training.

## Training smoke test and the later scientific study

After worker qualification and permissioned, executed corrective trajectories exist, the pinned official launcher provides the concrete reload test below. `corrections/` is a required LeRobot dataset path with real action trajectories and the verified modality file; it is not included in this package.

```sh
NUM_GPUS=1 MAX_STEPS=20 GLOBAL_BATCH_SIZE=8 SAVE_STEPS=20 USE_WANDB=0 \
  uv run --no-sync bash examples/finetune.sh \
  --base-model-path /srv/forge-groot/checkpoints/GR00T-N1.7-LIBERO/libero_10 \
  --dataset-path /srv/forge-groot/corrections \
  --embodiment-tag LIBERO_PANDA \
  --output-dir /srv/forge-groot/training-smoke \
  --state-dropout-prob 0.2 \
  --save-only-model
```

This is a proposed smoke budget, not a tuned recipe, efficiency claim or promised memory fit. Capture the real optimizer/parameter configuration, failed acquisition attempts, data/retention lineage, package versions, actual resource use and action-tensor hashes before/after. Confirm that model tensors changed and that the saved policy reloads through the identical adapter. Configuration-file changes do not count as learning. Do not run the training smoke on final-evaluation cases.

Only after these gates should Forge execute matched correction arms, diagnostic ablations, independent acquisition/training replicates and a newly registered evaluation. Camera/configuration repair, broad random/diverse corrections, unreduced-source corrections and the privileged expert remain substantive comparators. The old 297/300 minimized nominee and its **do not promote** decision cannot be replaced or reinterpreted by the new integration.

Human engineer validation, independently supplied incidents, hardware transfer, the GPU worker, model access, adaptation, remote operations and a fresh study remain pending. No visual polish or static contract check closes those gates.
