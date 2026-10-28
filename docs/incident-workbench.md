# Incident replay and controlled scene forks

The workcell starts with the robot scene, a rendered inspection camera, the recorded failure and a direct **Fork incident** action. Existing playback, contact seeking, boundary selection, telemetry and reduction evidence remain available. The camera comes from the real MuJoCo renderer; it is not an input to the current learned gantry policy.

## What the intervention means

Every job chooses one eligible source episode from a completed development counterexample and binds its artifact, task, checkpoint, scientific sources, adapter sources and runtime. It changes exactly one of four registered scene factors: protected-object height, shared scene friction, payload yaw or tray offset. All other factors, the reset nuisance draw and the policy checkpoint are paired.

This is an **initial-scene reset**, not restoration of an arbitrary mid-episode state. The source-seed original branch must reproduce the recorded source observations, actions, scene, metrics and oracle. Height legitimately changes the protected object's center to `height/2`; yaw changes the payload quaternion. The allowed change is checked explicitly, and unchanged state coordinates and initial velocities must match.

The policy reads eight instrumented values once at reset and emits learned lift/closure targets for the fixed gantry controller. Height and friction change both physics and those observations; tray offset also changes the controller's target. An intervention therefore measures the total scene effect, including the policy's response. It does not isolate a geometric or visual mechanism, and it does not establish that the model's proposed explanation is uniquely correct.

Each job freezes 1–20 new nuisance seeds before execution, plus the original source seed as a separately labeled anchor. The anchor is excluded from the diagnostic denominator. Fresh pairs use independent nuisance draws and share each draw across branches. Previous jobs' draws at the same source condition are avoided. Completed pairs, failed attempts, partial episodes and cancellation history remain recorded. Incomplete attempts never become task failures or successes.

## Actual completed NVIDIA proposal

The included job `inc-657a996d965c43a3a8f9` starts from original source `fg-a7f42769f2-e65489d5a6f28fa`. Nebius Token Factory's exact returned model was `nvidia/Nemotron-3-Ultra-550b-a55b`. It selected protected-object height **170 → 65 mm**, the clearance/contact hypothesis, lateral alignment as a competing explanation, one actual policy-input name and seven supplied metric keys. Readable rationale is rendered from bounded mechanism templates; arbitrary model prose cannot add imaginary sensors.

The reviewed proposal executed **42 actual MuJoCo episodes**: 20 fresh original/intervention pairs and one source-seed anchor. The fresh original scene succeeded 0/20 times; the intervention succeeded 20/20, producing 20 rescues and no observed regressions. The conservative paired 95% difference interval is **+60.648 to +100 percentage points**, using simultaneous Clopper–Pearson bounds on rescue and regression probabilities. The finite sample does not justify certainty about future draws. These are post-final diagnostics, excluded from training, nomination and the registered report.

The first manual UI qualification used a different source, the minimized 115 mm boundary, with five fresh pairs at 60 mm. Its observed result was also 0/5 → 5/5, but the same conservative interval crosses zero; the UI correctly reports that evidence as inconclusive. This smaller qualification is retained in local history, not pooled into the NVIDIA proposal's denominator.

The registered 8,000-outcome study is unchanged: the minimized nominee scored 297/300 shifted successes, base 104/300, and both random/source nominees 300/300. Its decision remains **do not promote**. Changing a scene is not evidence that trained policy weights improved.

## Requests, rejection and accounting

The workflow is deliberately separate: preview the exact measured context, make one explicitly selected provider request, validate its typed proposal, record an acceptance/rejection review, then execute the accepted intervention. GET requests only read evidence. There is no automatic paid inference button, fallback model, retry or unvalidated model-to-simulator path.

The retained [receipt recording](../evidence/incident-planner-receipts.json) includes every intervention-planning attempt:

| Attempt | Actual request | Local disposition | Estimated USD |
| --- | --- | --- | ---: |
| Fireworks Ultra v1 | `chatcmpl-47416f763db145f2bbd12cfcbc5873c7` | Initial development schema passed; not executed | 0.0040596 |
| Nebius Ultra v1 | `chatcmpl-a068878d5a5f8efb` | Separate review rejected unsupported sensor claims; not executed | 0.0058020 |
| Fireworks Ultra v2 | `chatcmpl-2c9a38cf364248cfb09e5ad220ea1f95` | Exact input/finite-mechanism role passed development qualification | 0.0081696 |
| Nebius Ultra v2 | `chatcmpl-81c4ad5960e1ff6f` | Original validation rejected seven references under a five-reference cap; receipt unchanged | 0.0062800 |
| Local v2.1 validation | Same retained Nebius v2 response | Unique references bounded by the supplied metric namespace; accepted and executed | 0.0000000 |

The first Nebius response invented heightmaps, contact-normal and proximity-sensor inputs. Its model receipt remains immutable, with a separate rejection record. The revised context supplies the exact observation/action arrays and names, factor-to-scene/input mappings and contact phase. The v2 response supplied seven real metric references; the local v2.1 correction removed only the arbitrary five-reference limit. Unknown, duplicate or excessive references still fail. Candidate, mechanism, task and oracle contracts did not change. The same raw response hash binds the original rejected receipt to the new acceptance; **no third Nebius inference occurred**.

There were two actual Nebius requests costing an estimated **$0.012082** and two Fireworks requests costing **$0.0122292** for this role. Estimates use recorded tokens and qualified rates, not invoices. The local revalidation is never counted as another provider call or as an unknown-cost request. Review was performed by the automated orchestrator, not an independent human engineer.

For development, inspect a request without running inference:

```sh
.venv/bin/python scripts/plan_intervention.py preview \
  --campaign fg-a7f42769f2 \
  --source fg-a7f42769f2-e65489d5a6f28fa \
  --provider fireworks --output artifacts/intervention-preview.json
```

The CLI's `propose`, `review` and `accept` commands remain separate. `propose --provider nebius` additionally requires `--qualify-nebius` and a bounded nominal admission ceiling. An uncertain or rejected attempt is retained and cannot be silently retried under the same idempotency key. `accept --run` uses the recorded review and current exact source context before any physics.

## Portable regression test and recording import

The [2,179,312-byte test ZIP](../evidence/nebius-incident-test.zip) has SHA-256 `af6d2ead51ac44bf087569f51fb84a294fa2c85af802620c72ca21cb14d454df`. It contains the exact source and checkpoint, the predeclared schedule, every attempted episode, policy observations/actions, oracle/aggregate evidence, three dense oracle traces, frozen source files, the accepted proposal/review and the original metered provider receipt. Fresh pairs retain compact initial/final traces and full measured aggregates; dense traces are confined to the source and anchor exemplars to keep the package small.

Each job snapshots its source code at creation. Completed ZIPs are frozen and cached, so a later adapter fix cannot change the archive or strand earlier evidence. Checksums and local source identities establish consistency with the supplied recording; they are not third-party signatures or remote attestation.

Extract into a fresh directory and install its small `requirements.txt` in Python **3.11.6**: MuJoCo **3.3.7**, NumPy **2.2.6**, SciPy **1.15.3**. From any working directory, without the server, original database or provider keys:

```sh
python /absolute/incident/scripts/incident_reproduce.py --bundle /absolute/incident --verify
python /absolute/incident/scripts/incident_reproduce.py --bundle /absolute/incident --rerun --all-pairs
python /absolute/incident/scripts/incident_reproduce.py --bundle /absolute/incident --rerun --checkpoint /absolute/compatible.json
```

Verification checks file/source bindings before importing bundled code, reconstructs dense oracles, validates the source reset and policy inference, checks all paired scene deltas and recomputes the diagnostic statistics. Reproduction defaults to the anchored pair; `--all-pairs` executes all 42 episodes. `--output /absolute/result.json` writes a report outside the unchanged bundle. An alternate checkpoint must be data-only JSON compatible with the exact task/controller, input/output names, normalization and finite tensor schema. Its outcomes are a new diagnostic, not expected to match the original policy.

The application recording can be restored after the original starter:

```sh
.venv/bin/python scripts/import_recorded_sample.py
.venv/bin/python scripts/import_incident_recording.py
```

Both commands support `--data /absolute/isolated-data`. The add-on accepts only the exact included archive/receipts, requires the matching completed parent/source/checkpoint, refuses active or conflicting work and leaves original campaign rows unchanged. Repeated import does not duplicate requests or cost. It performs no model request, training or physics run.

## Local API and pending work

`GET /api/incidents/context?campaign_id=…` lists eligible sources and factor bounds. `POST /api/incidents` accepts `campaign_id`, `source_episode_id`, `factor`, `value`, `nuisance_repeats` and an optional accepted `planner_receipt_sha`. Mutations require JSON, a valid local Origin and an Idempotency-Key. Job detail, paired episode, cancellation and ZIP endpoints live beneath `/api/incidents/{id}`. `GET /api/intervention-plans` is read-only. The UI preserves drafts through reconnection and retains all completed/canceled history.

The [official GR00T/LIBERO package](groot-worker-qualification.md) is the next adapter, not the policy used by these results. CUDA execution, closed-loop interface qualification, actual corrective trajectories, training/reload, remote operations, hardware transfer and independent engineer validation remain pending. A drawer incident is only a candidate until a real competent policy produces one.
