"""Registered development protocol. Final scenarios are controlled separately."""
from __future__ import annotations
import numpy as np
from .minimizer import values
from .store import digest

TRAINING_SEEDS = [101, 202, 303, 404, 505]
TRAINING_BUDGET = {"examples": 24, "retained_nominal": 8, "corrective": 16, "steps": 600, "batch_size": 24, "learning_rate": .004}
ARMS = {"random": "Random curriculum", "source": "Source neighborhood", "minimized": "Minimized curriculum"}

def embargo(parameters):
    """Never enters base/adaptation/search/planner/development validation."""
    if parameters["obstacle_height"] >= .145 - 1e-8 and parameters["friction"] <= .28 + 1e-8:
        return "tall_obstacle_low_friction"
    if abs(parameters["payload_yaw"]) >= .12 - 1e-8 and abs(parameters["tray_offset_y"]) >= .025 - 1e-8:
        return "yaw_offset_composition"
    return None

PROTOCOL = {
    "id": "forge-local-protocol-v2", "scope": "Original Cartesian gantry; MuJoCo simulation only",
    "development_revision": "V1 is retained. Its local-jitter minimized curriculum missed two low-friction grasps and one tall-obstacle transfer. V2 uses two separately measured failure clusters with broad background coverage. Development validation is reused; final evaluation remains untouched.",
    "curriculum_v2": "Add an isolated nominal-height friction=.16 coverage control. Reduce clearance and grasp failures separately. Source/minimized arms each receive 8 successful corrections per cluster, with paired noncausal-factor and nuisance draws. Minimized causal coordinates sample four near-boundary and four increasingly severe values; source coordinates use the same rule centered on original unreduced sources. Backgrounds must be inside development regions for both arms. Both retain the same 8 nominal demos, 600 Adam updates and 5 seeds. Random receives 16 broad corrections. This isolates causal-coordinate placement, not the whole cost or value of minimization; V1-to-V2 gains also include second-cluster coverage.",
    "policy": "Instrumented-state MLP waypoint regression above fixed contact controller; no vision policy, GR00T, Isaac or robot hardware",
    "training_seeds": TRAINING_SEEDS, "training_budget": TRAINING_BUDGET, "arms": ARMS,
    "resource_claim": "Matched successful demonstration count, fixed initialization and optimizer-update budget only. Search, minimization, failed expert acquisition, CPU time and NVIDIA API usage are charged and reported separately; no matched total-compute claim.",
    "nomination": "Minimized arm is preselected. Choose its checkpoint with highest success count on frozen development-validation manifest, breaking ties by lowest training seed. Freeze nomination before any final outcomes.",
    "excluded_development_regions": ["obstacle_height >= 0.145 m AND friction <= 0.28", "abs(payload_yaw) >= 0.12 rad AND abs(tray_offset_y) >= 0.025 m"],
    "nominal_distribution": {"obstacle_height": [.055,.075], "friction": [.55,.75], "payload_yaw": [-.03,.03], "tray_offset_y": [-.005,.005]},
    "minimization": {"objective": ["changed_factor_count", "normalized_L1_magnitude"], "paired_nuisance_draws": 5, "failure_threshold": 4, "max_candidate_sets": 160, "fresh_confirmation_draws": 20, "neighborhood": "every lower-objective single-coordinate registered-grid substitution, including sign reversals and jumps across non-monotonic successes"},
    "final_evaluation": "Root registers fresh nominal, in-envelope and embargo-composition scenarios; no final access before checkpoint/training freeze. >=200 IID nominal pairs for nominated checkpoint. Global manifest exposure registry prevents adaptive reuse.",
    "promotion_gate": "Exploratory reports never qualify promotion. Registered simulation candidate requires a paired 95% lower improvement bound above zero on shifted scenarios, >=10 percentage-point gain over the strongest matched training comparator, and one-sided conservative 95% nominal difference lower bound > -0.03. Any observed critical protected contact blocks promotion pending investigation. Hardware remains unqualified.",
    "invalids": "Invalid reset scenes and infrastructure failures before simulation are separately enumerated. Partial/interrupted attempts are excluded from task verdicts. Policy-caused numerical failure remains non-success. One infrastructure retry with identical immutable inputs is permitted and both attempts retained.",
    "intervals": "Fixed-checkpoint rates: Wilson 95%. Paired difference: conservative simultaneous Clopper-Pearson rescue/regression bounds. Multi-seed method summaries: scenario/seed clustered descriptive bootstrap, never used for non-inferiority.",
}
PROTOCOL_SHA = digest(PROTOCOL)

def finite_pool(factors, seed, count=48):
    rng = np.random.default_rng(seed)
    names = list(factors)
    grids = {k: values(v) for k,v in factors.items()}
    seen, output = set(), []
    for _ in range(20000):
        p = {k: float(rng.choice(grids[k])) for k in names}
        key = tuple(p.values())
        if key in seen or embargo(p): continue
        seen.add(key)
        output.append({"candidate_id": f"candidate-{len(output):03d}", "parameters": p})
        if len(output) >= count: return output
    raise RuntimeError("Finite candidate pool exhausted")

def scenario(parameters, seed, split="development", family="coverage"):
    if split == "development" and embargo(parameters): raise ValueError("Embargoed compositional region cannot enter development")
    result = {"split": split, "family": family, "seed": int(seed) % (2**32), "parameters": {k: float(v) for k,v in parameters.items()}}
    result["scenario_id"] = "sc-"+digest(result)[:16]
    return result

def development_manifest(factors, seed):
    """Frozen at campaign creation, before model planning and adaptation."""
    rng = np.random.default_rng(seed+800000)
    scenes = []
    for i in range(24):
        p = {k: float(rng.uniform(*limits)) for k, limits in PROTOCOL["nominal_distribution"].items()}
        scenes.append(scenario(p, int(rng.integers(1,2**30)), split="validation", family="nominal"))
    pool = finite_pool(factors, seed+800001, 32)
    for p in pool:
        scenes.append(scenario(p["parameters"], int(rng.integers(1,2**30)), split="validation", family="in_envelope"))
    return {"label": "Exploratory development evaluation; reused during versioned development, never sealed", "protocol_sha": PROTOCOL_SHA, "scenarios": scenes, "generated_before_search": True,"previous_development_exposure":"V1 scenarios reused for the declared V2 refinement; final evaluation is separate"}
