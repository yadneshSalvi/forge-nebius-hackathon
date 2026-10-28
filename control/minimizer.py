"""Finite non-monotonic counterexample reduction; no bisection assumption."""
from __future__ import annotations
import math

def objective(parameters, factors):
    changed, magnitude = 0, 0.0
    for name, spec in factors.items():
        delta = abs(parameters[name] - spec["nominal"])
        changed += delta > 1e-8
        magnitude += delta / (spec["max"] - spec["min"])
    return int(changed), round(magnitude, 9)

def values(spec):
    n = int(math.floor((spec["max"] - spec["min"]) / spec["step"] + 1e-8))
    return sorted(set([round(spec["min"] + i * spec["step"], 9) for i in range(n + 1)] + [spec["nominal"], spec["max"]]))

def neighborhood(parameters, factors):
    """All smaller-objective single-coordinate replacements, including reversals."""
    current = objective(parameters, factors)
    candidates = []
    for name, spec in factors.items():
        for value in values(spec):
            trial = {**parameters, name: value}
            if objective(trial, factors) < current:
                candidates.append((objective(trial, factors), name, value, trial))
    return sorted(candidates, key=lambda t: (t[0], t[1], t[2]))

def reduce_counterexample(parameters, factors, evaluate, paired_seeds, max_candidates=160, on_step=None):
    """evaluate(params, seed) -> {valid,success,id}. Preserve >=80% failure.

    Common nuisance draws are reused. A budget stop is never a local-minimum
    claim. Callers must perform separate fresh-draw confirmation.
    """
    current, steps, cache, count = dict(parameters), [], {}, 0
    threshold = math.ceil(len(paired_seeds) * 0.8)
    while True:
        accepted = None
        for _, factor, value, trial in neighborhood(current, factors):
            key = tuple(sorted(trial.items()))
            if key not in cache:
                if count >= max_candidates:
                    return current, steps, {"locally_minimal": False, "reason": "candidate budget exhausted", "candidates_tested": count, "paired_seeds": paired_seeds}
                cache[key] = [evaluate(trial, seed) for seed in paired_seeds]
                count += 1
            outcomes = cache[key]
            valid = sum(bool(o["valid"]) for o in outcomes)
            failures = sum(bool(o["valid"]) and not bool(o["success"]) for o in outcomes)
            preserve = valid == len(paired_seeds) and failures >= threshold
            step = {"factor": factor, "from_value": current[factor], "to_value": value,
                    "parameters": trial, "accepted": preserve, "failure_count": failures,
                    "valid_count": valid, "episode_ids": [o["id"] for o in outcomes],
                    "kind": "sign_reversal" if (current[factor]-factors[factor]["nominal"])*(value-factors[factor]["nominal"]) < 0 else "reduction",
                    "objective": list(objective(trial, factors))}
            steps.append(step)
            if on_step: on_step(step, count)
            if preserve:
                accepted = trial
                break
        if accepted is None: break
        current = accepted
    return current, steps, {"locally_minimal": True, "reason": "every smaller single-coordinate grid substitution rejected", "candidates_tested": count, "paired_seeds": paired_seeds, "failure_threshold": threshold, "neighborhood": "All single-factor registered-grid substitutions with a lower (changed factors, normalized L1 magnitude) objective. Includes non-adjacent points and sign reversals; no monotonicity assumption."}
