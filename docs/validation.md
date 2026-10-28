# Local validation record

Measured local simulation on macOS arm64, Python 3.11.6, MuJoCo 3.3.7, NumPy 2.2.6 and Node 22.22.3. This is not hardware qualification. Exact episodes, checkpoints and provider receipts are in the application export.

## Final registered result

The independent orchestrator generated 500 cases after all weights, nominations and computational sources were frozen: 200 IID nominal and 300 IID shifted-mixture draws. All 16 frozen checkpoints were paired, producing 8,000 outcomes. Independent code validated every row identity, coverage, artifact hash, paired bound and promotion gate.

| Preselected checkpoint | Nominal | Shifted mixture |
|---|---:|---:|
| Base | 200 / 200 | 104 / 300 |
| Random, seed 101 | 200 / 200 | 300 / 300 |
| Source, seed 101 | 200 / 200 | 300 / 300 |
| Minimized, seed 101 | 200 / 200 | 297 / 300 |

The minimized nominee gains 64.33 percentage points over base on shifted cases, with no observed base regression or protected contact. Its three remaining failures are two failed grasps and one placement outside the target; independent fresh replay confirmed all three. It is one point below both comparators and does not meet the registered ten-point comparator advantage. The correct decision is **do not promote**. The application preserves the failed gates and all missed cases; no policy was retuned on final labels. Pooled 200/300 rates are descriptive; nominal and shifted uncertainty are separate.

The conservative paired 95% difference interval is +56.37 to +70.49 points versus base, and −3.21 to +1.29 points versus each comparator. The nominal one-sided 95% lower difference bound is −1.83 points despite identical observed outcomes.

Across all five minimized seeds there is one actual base-to-revised regression, in non-nominated seed 404. A separately labeled post-final reproduction shows base success and that checkpoint's failed grasp on the identical case, with exactly matching saved metrics. It stays outside the frozen report, nomination and statistical denominators. Zero observed regressions applies only to the nominated checkpoint.

Final campaign: `fg-8a43e14455`. Manifest: `36d4c6d357dfaf725c6689182794b11e443515c53f9e2d6fa3010e71739aa969`. Report artifact: `f53692fb39722bace7af30ddb346b4f932cdfbda4e3032e4b6ba1541af8d72bd`.

## Versioned development

| Development result | V1 | V2 |
|---|---:|---:|
| Base, one checkpoint | 47 / 56 | 47 / 56 |
| Random, five seeds | 280 / 280 | 280 / 280 |
| Source, five seeds | 280 / 280 | 280 / 280 |
| Minimized, five seeds | 265 / 280 | 279 / 280 |
| Nominated minimized seed | 101, 53 / 56 | 101, 56 / 56 |
| Actual campaign physics episodes | 1,104 | 1,218 |
| Successful corrective examples | 48 | 48 |

V1 is `fg-3da83888e9`; v2 is `fg-a7f42769f2`. They share the task and 40-demonstration base. V2 changed acquisition before final generation: two measured clusters and matched source/minimized background coverage. The exposed development set was reused transparently. V1's negative result remains retained.

V1's nominated policy missed two low-friction grasps and a tall-obstacle transfer. V2 fixes these on development, although seed 404 still misses one of 56. This supports a development improvement, not superiority over the two perfect development comparators.

## Scientific and operational checks

The final offline Python suite passed **84 tests in 42.87 s**. Two dependency deprecation warnings concern Starlette's test client compatibility; neither affects the measured outcomes or running service.

Engine tests exercise contact pickup/release, oriented containment, continuous settling, protected movement/contact, successful expert binding, actual weight changes, deterministic weight hashes, tampered checkpoints and embargo rejection. Reduction crosses successful intermediate conditions to find a smaller failure; it assumes no monotonicity.

The independent orchestrator reconstructed nominal and failing episodes from 4,701 raw states, geometry/quaternions and per-point forces using separate SciPy calculations. The real failing source had 2,587 forbidden-contact steps and 5,182 above-threshold points. It also ran all 14 smaller primary-boundary neighbors with five nuisance draws each: all had 0/5 failures, supporting the stated one-coordinate local minimum.

Registration tests bind the completed parent, 15 arm/seed/artifact mappings, 16 artifacts, nominations/time, computational sources, regions and exposure history. Relabeling physical cases cannot create untouched data. Nominal finite-sample bounds remain nonzero even when all paired outcomes agree.

A real isolated worker test executes MuJoCo discovery through pause, resume, cancel, another resume and fresh-supervisor recovery. Accepted episodes survive; stale writes fail; the old process terminates; no model call occurs. Browser tests reject foreign Origins, non-JSON mutations, missing idempotency and unknown fields; GETs leave compute idle. Launcher tests cover occupied ports and termination of a child/grandchild listener.

## Portability and frontend

The final 78,695,128-byte starter restored three campaigns, 9,224 episode rows, 9,349 scientific objects, all 40 base demonstrations and all 500 exposure guards into a clean directory in 46.96 s, with credentials removed. Import ran no new physics or inference. Both supplemental 236-frame traces were restored, and an actual attempt to reuse the final cases with different checkpoints was rejected. The independent orchestrator also audited every starter file, its checksums and the absence of all nine configured credential values.

The frozen v1 bundle verified without its original data: 1,259 files, 1,221 objects, 16 checkpoints, 88 demonstrations including all 40 base examples, and 78 dense-oracle reconstructions. Fresh local physics reproduced its recorded failure with no differences. Tests cover unsafe paths, symlinks, missing data, source changes, rehashed demo tampering and inconsistent raw geometry/contact evidence.

The final v2 ZIP also passed a fresh-directory check launched outside the repository with no API credentials: 9,395 checksummed files, 9,349 canonical objects, 16 checkpoints, 88 demonstrations, 9,263 distinct episode records and 87 dense-oracle reconstructions. The bundled verifier checked the six-file evaluation source lock. Fresh 4,700-step base-failure and successful-expert replays both matched with no differences and no network requests. The recorded starter separately passed a clean offline import with all 500 exposure guards preserved.

Frontend checks cover all six routes at 320, 390, 768, 1280 and 1440 px with no horizontal overflow or page errors, and no axe violations at 390/1440 px. Keyboard replay, source/reduced binding, contact seeking, focus, offline reconnection and WebGL-disabled top-view/object inspection pass. Build, TypeScript and formatting checks pass. Headless playback measured 27.4 DOM state commits/s; this is not a GPU frame-time benchmark. Three current screenshots are in `docs/screenshots/`.

## Actual NVIDIA inference

| Version / provider | Calls | Input tokens | Output tokens | Estimated USD |
|---|---:|---:|---:|---:|
| V1 Fireworks Ultra | 1 | 11,215 | 4,737 | 0.0180978 |
| V1 Together Super VL | 1 | 1,420 | 1,227 | 0.0008265 |
| V2 Fireworks Ultra | 1 | 15,715 | 13,766 | 0.0424674 |
| V2 Together Super VL | 1 | 1,420 | 973 | 0.0006995 |

All four completions validated against local schemas and exact returned model identities. The planner changed finite trial selection; the visual model saw actual rendered frames. Costs are rate-based estimates, not invoices. Usage may count reasoning tokens; separate reasoning content is excluded. No Nebius completion, robot hardware, RTX/Isaac run, deployment or broad external study is claimed.
