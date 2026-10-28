# FORGE local API contract

The API binds to `127.0.0.1:4402`; the interface uses port 4401. JSON names use snake_case. GET requests inspect state and never start simulation, training or inference.

## Reading evidence

- `GET /api/health`: status, simulation_only and base_ready.
- `GET /api/bootstrap`: frozen task, runtime, protocol, campaign summaries, provider identities and base checkpoint. Provider configuration is a boolean; credentials are never returned.
- `GET /api/campaigns` and `/api/campaigns/{id}`: summaries or full progress, events, attempts, episodes, provider calls and completed stage payloads. Unfinished stages have no invented results. `freshness.source_matches` compares recorded scientific source with current files.
- `GET /api/episodes/{id}`: exact verified engine artifact plus UI id, artifact_sha and metadata hash-scope description. Rich episodes retain raw 500 Hz states/contacts and 25 Hz frames. Compact episodes identify `trace.recorded: false`; their endpoint samples are not full motion recordings.
- `GET /api/artifacts/{sha}`: SHA-256-verified JSON, never arbitrary paths.
- `GET /api/campaigns/{id}/images/source.png` or `minimized.png`: actual MuJoCo frames sent to the visual model.
- `GET /api/campaigns/{id}/export`: canonical manifests, policies, demo lineage, episodes, provider receipts, sources and checksums. A v2 parent includes its linked registered evaluation. A frozen historical archive is served unchanged after verifying its saved SHA.

The interface retains the last good response during network loss and labels it disconnected. A healthy empty store shows setup instructions.

## Mutations and lifecycle

All mutations require JSON and an Idempotency-Key of 8–100 letters/digits/colon/underscore/hyphen. Browser Origin headers must identify the local interface. Exact duplicate requests do not repeat work; conflicting keys return 409.

- `POST /api/campaigns` accepts `{name?, seed?, search_budget?: 12|24|36, development_parent_id?}`. It freezes task, protocol, source, base and development manifest, then starts bounded discovery, reduction and expert acquisition. A development parent must have a completed exploratory report. Live creation uses the explicit NVIDIA routes; unavailable credentials fail visibly without substitution.
- `POST /api/campaigns/{id}/train` accepts `{expected_generation}`. From a ready curriculum it trains three arms × five seeds and runs development evaluation. It does not open the final set.
- `POST /api/campaigns/{id}/pause`, `/cancel`, `/resume` accept the generation body. Pause stops at an episode boundary. Cancel advances the fence and confirms local process termination. Resume retains inputs and accepted evidence, advances generation and restarts the incomplete phase. Late generations cannot commit outcomes.
- `POST /api/challenges` accepts `{campaign_id, seed, parameters}` with all four SI factors: obstacle_height, friction, payload_yaw, tray_offset_y. Values must stay inside the registered bounds; UI controls use declared steps and include nominal friction 0.65. A separate campaign executes base and the nominated minimized checkpoint with the same nuisance seed and rich traces. The challenge payload includes both IDs/outcomes and `retraining: false`. It is not sealed statistical evidence.

Only one campaign owns the local worker. Statuses distinguish queued, running, pause_requested, paused, cancel_requested, canceled, interrupted, failed, ready and completed. Partial attempts are excluded from task denominators. Remote completion can remain unconfirmed after local inference cancellation.

## Stage payloads

`counterexample` binds source/reduced IDs and parameters, evaluated reduction steps, factor counts, normalized magnitudes, local-minimum qualification and fresh confirmation. V2 `secondary_boundaries` contains the distinct measured grasp boundary with the same shape. Each microscope selector uses its own source/reduced IDs.

`curriculum` lists arm budgets, accepted/rejected expert demonstrations and actual acquisition episodes. Every accepted demo references a complete successful expert trajectory. `paired_acquisition_sha` binds v2 source/minimized pairs, cluster allocation and shared background draws. Each receives eight corrections from each of two clusters; random retains broad sampling.

`training.runs` holds 15 actual checkpoints with arm, seed, checkpoint/base hashes, examples, steps, losses, duration and weight displacement. Checkpoint content hashes include elapsed-time metadata; compare final_weights_hash for deterministic tensor reproduction.

`report` is exploratory development, with paired scenario/seed rows, all seed results, families, actual rescues/regressions, budgets and three development-only nominations. V1 and v2 are distinct immutable campaigns; the negative v1 result is retained.

`registered_report` on a parent is the separate final result. Its evaluation_campaign_id points to the durable 8,000-row execution record. It binds the manifest, evaluation source and nominations, and reports nominal/shifted strata, comparator bounds, regressions and promotion_checks. The fixed 200/300 pooled summaries are descriptive and deliberately have null intervals. The UI can switch back to development history.

`model_evidence` contains actual validated NVIDIA responses and grounded input/image references. `provider_calls` retains final content, usage, request identity and failed attempts, excluding the separate reasoning_content field. Cost is an estimate from declared rates, not a billing statement.

## Independent final registration

Final evaluation uses an explicit local CLI:

```sh
.venv/bin/python scripts/run_registered_evaluation.py \
  --campaign DEVELOPMENT_CAMPAIGN --manifest /absolute/path/registration.json --workers 4
.venv/bin/python scripts/run_registered_evaluation.py --resume EVALUATION_CAMPAIGN
```

`--validate-only` checks without creating or exposing a run. The manifest binds the exact completed parent, 15 unique arm/seed/artifact mappings, all 16 artifacts, nominations and timestamp, scientific/evaluation source, task, protocol, and 500 parameters/seeds. CLI and worker validate before execution and resume. Resume skips accepted rows without redrawing cases.

Global exposure uses actual physical parameters/seeds and task, independently of labels/order. Exact checkpoint replay is identified as reproduction; exposed cases with different adaptive weights are rejected. The independent orchestrator generates the final manifest after source, weights and nominations freeze.
