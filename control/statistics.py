"""Paired outcomes with finite-sample, conservative binomial bounds."""
from __future__ import annotations
import math
import numpy as np
from scipy.stats import beta

def wilson(successes, total, z=1.959963984540054):
    if not total: return [0.0, 1.0]
    p = successes / total
    d = 1 + z*z / total
    center = (p + z*z/(2*total))/d
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/d
    return [max(0, center-half), min(1, center+half)]

def cp_lower(k, n, tail):
    return 0.0 if k == 0 else float(beta.ppf(tail, k, n-k+1))

def cp_upper(k, n, tail):
    return 1.0 if k == n else float(beta.ppf(1-tail, k+1, n-k))

def paired(base, revised):
    if len(base) != len(revised) or not len(base): raise ValueError("Nonempty paired outcomes required")
    b, r = np.asarray(base, dtype=bool), np.asarray(revised, dtype=bool)
    n = len(b)
    rescue, regression = int((~b & r).sum()), int((b & ~r).sum())
    counts = {"rescued": rescue, "regressed": regression, "both_success": int((b & r).sum()), "both_failure": int((~b & ~r).sum())}
    # Four marginal one-sided tails sum to .05; interval is conservative even
    # at zero discordances. It does not assume independent policy outcomes.
    interval = [cp_lower(rescue,n,.0125)-cp_upper(regression,n,.0125), cp_upper(rescue,n,.0125)-cp_lower(regression,n,.0125)]
    lower = cp_lower(rescue,n,.025)-cp_upper(regression,n,.025)
    return {"paired": counts, "delta": (rescue-regression)/n, "delta_interval": interval,
            "nominal_lower_95": lower, "total": n,
            "interval_method": "Conservative paired difference: simultaneous Clopper–Pearson bounds on rescue and regression probabilities; one-sided 95% nominal gate uses Bonferroni tails .025."}

def summarize(outcomes):
    valid = [o for o in outcomes if o.get("valid", True)]
    successes = sum(bool(o["success"]) for o in valid)
    return {"successes": successes, "total": len(valid), "scheduled": len(outcomes), "invalid": len(outcomes)-len(valid), "rate": successes/len(valid) if valid else 0, "interval": wilson(successes,len(valid)), "interval_method": "Wilson 95%, conditional on this frozen checkpoint and valid registered scenario draws"}

def seed_cluster_interval(base, revised_runs, bootstrap_seed=91027, draws=1000):
    """Descriptive hierarchical bootstrap, retaining paired scenario indices.

    Not used for promotion/non-inferiority. With finite training seeds, this is
    explicitly a descriptive method estimate, not a robot-safety certificate.
    """
    b = np.asarray(base, dtype=float)
    r = np.asarray(revised_runs, dtype=float)
    if r.ndim != 2 or r.shape[1] != len(b): raise ValueError("Scenario alignment mismatch")
    rng = np.random.default_rng(bootstrap_seed)
    estimates = []
    for _ in range(draws):
        seeds = rng.integers(0, len(r), len(r))
        scenarios = rng.integers(0, len(b), len(b))
        estimates.append(float((r[seeds][:, scenarios]-b[scenarios]).mean()))
    return [float(x) for x in np.quantile(estimates, [.025, .975])]
