# Measured simulation, bounded claims

FORGE discovers manipulation failures, reduces them to reproducible conditions, trains real corrective weights, and reports whether the repair survives comparison. It does not certify robot safety.

## Physics and learning

The original Cartesian gantry has three actuated translation axes and two sliding fingers. MuJoCo 3.3.7 integrates rigid-body contact, friction, gravity and actuator dynamics at 500 Hz. The 60 g payload is a free body: no weld, hidden attachment, teleportation or browser physics is used during execution. Geometry is authored here under MIT; MuJoCo is Apache-2.0.

The frozen predicate requires all eight oriented payload corners inside the tray, actual finger opening of at least 75 mm, a measured lift, two continuous settled seconds, protected-body translation/rotation within limits, and no prohibited contact point above 0.10 N at any physics step. Exact SI thresholds, permitted contacts, frames and nuisance distributions are in `engine/spec.py`. Model text cannot change the verdict.

A 650-parameter NumPy MLP (8 → 24 → 16 → 2) predicts lift height and finger-close position above a fixed motion controller. Inputs are privileged instrumented simulator measurements. This is not a vision policy, GR00T checkpoint or learned torque controller. The base uses 40 successful expert trajectories. Every adaptation starts from the same base weights and a freshly reset Adam optimizer.

Selected episodes retain raw 500 Hz states, actions and per-point protected contacts plus 25 Hz replay frames. Bulk evaluations retain complete per-step oracle aggregates and initial/final states. Endpoint-only records are identified and are not shown as full recorded motion. Browser interpolation is display only.

## Search and reduction

Height, friction, payload yaw and tray offset have registered finite grids. Nominal friction 0.65 is an explicit additional member outside the 0.16 + 0.04n lattice. Fixed coverage precedes an actual Fireworks NVIDIA Nemotron Ultra call: validated ranking of a finite candidate pool changes the ensuing trials. Every fifth adaptive slot remains coverage. Together NVIDIA Super VL inspects genuine MuJoCo render frames; its observations remain advisory.

A source needs at least four failures in five nuisance draws. Reduction minimizes changed-factor count, then normalized L1 magnitude. Every smaller single-coordinate grid replacement in the permitted development region is tested, including sign reversals and jumps across successful intermediate values. No monotonicity or global-minimum claim is made. Five paired nuisance draws are reused during reduction, followed by 20 fresh draws. A budget stop is not local minimality.

Nuisance seeds vary reset position/yaw, instrument noise, actuator gain and phase timing. Repeating an identical seed establishes deterministic repeatability; different seeds sample only the declared nuisance distribution.

## Versioned development

V1 reduced four changed factors to a single 115 mm obstacle-height condition, with 20/20 fresh failures. Its development results were:

| Policy | Successful executions | Denominator |
|---|---:|---|
| Base | 47 / 56 | One checkpoint |
| Random curriculum | 280 / 280 | 56 scenarios × 5 seeds |
| Source neighborhood | 280 / 280 | Same paired scenarios |
| Local minimized neighborhood | 265 / 280 | Same paired scenarios |

Minimization did not beat the comparators. The nominated policy missed two low-friction grasps and one tall-obstacle transfer. V1's exact source, evidence, weights and negative result are retained in a frozen export.

Before generating any final scenarios, V2 was registered as one refinement. It adds an isolated low-friction control and separately reduces clearance and grasp failures. Source and minimized arms receive eight corrections per cluster, with paired background parameters and nuisance draws. Only causal-coordinate placement differs: the minimized arm spans the measured boundary toward more severe values; the source control applies the same rule centered on unreduced sources. A pair is accepted only if both expert trajectories pass. Backgrounds must satisfy both arms' embargo constraints. Random keeps broad sampling.

This is a narrow comparison of causal-coordinate placement, not a claim that every V1-to-V2 gain comes from minimization. The whole-version change also adds a failure cluster and broader background coverage. The exposed development validation set is reused transparently; it is not a sealed test.

## Budgets and final registration

All training arms use 16 successful corrections plus the same eight retained nominal examples, 600 Adam updates, batch size 24 sampled with replacement, learning rate 0.004, and seeds 101/202/303/404/505. Acquisition failures, search, minimization, CPU time and inference usage are counted separately. This is matched training budget, not matched total compute. Campaign episode totals count additional campaign work; the shared 40-episode/1,000-update base adaptation has its own manifest.

Two compositional regions are excluded from all development search, planner input, demonstrations and validation: height ≥145 mm with friction ≤0.28; and |yaw| ≥0.12 rad with |tray offset| ≥25 mm. These are held-out combinations of the same task, not new object families or visual occlusions.

Each arm is nominated by development success count, with lowest training seed breaking ties. The independent orchestrator then registers 200 IID nominal cases and 300 IID draws from an equally weighted mixture of fresh in-envelope and the two embargoed regions. All 16 checkpoints are paired on the same 500 physical cases. Final data cannot feed the planner, curriculum or training.

The fixed 200/300 allocation is stratified: pooled rates are descriptive. Nominal and shifted intervals are separate. Fixed-checkpoint rates use Wilson intervals. Paired difference bounds combine conservative Clopper–Pearson rescue/regression bounds. The one-sided nominal bound remains nonzero when every outcome agrees. Five optimization seeds share a base and curriculum; they are not five independent environmental draws or acquired datasets.

Simulation promotion requires a positive shifted improvement lower bound over base; at least ten points above both preselected comparators with positive paired lower bounds; nominal one-sided 95% lower difference above −3 points; and no observed critical protected contact. Hardware stays unqualified. Disappointing results remain reported.

Global exposure records key physical parameters and nuisance seeds independently of labels/order. Retitling or reordering cases cannot create a fresh holdout. Exact frozen-checkpoint replay is labeled reproduction; reuse with different adaptive checkpoints is rejected.

## Operations and limitations

Immutable inputs, SQLite transactions, idempotency keys, generation fences and owned process groups protect accepted evidence. Interrupted trajectories have no task verdict. Local cancellation confirms worker termination; an interrupted HTTP request may leave remote completion unconfirmed in its ledger.

Exports contain task/runtime/source locks, scenes, full weights, successful-demo lineage, provider receipts, paired outcomes and offline reproduction code. Checkpoint hashes include elapsed-time metadata; deterministic comparisons use weight hashes and outputs. Provider receipts exclude the separate reasoning_content field.

No robot hardware, RTX/CUDA, Isaac, GR00T, deployment, user study or broad external benchmark is claimed. Fireworks/Together are the actual development providers. Nebius qualification remains separate and pending.
