"""Declared finite development coverage and same-expert curriculum proposals."""
from __future__ import annotations
import numpy as np
from .protocol import finite_pool, embargo, scenario
from .minimizer import values

def coverage(factors):
    nominal = {k:v["nominal"] for k,v in factors.items()}
    return [
        nominal,
        {**nominal,"obstacle_height":.17,"friction":.64,"payload_yaw":.09,"tray_offset_y":.02},
        {**nominal,"obstacle_height":.12,"friction":.20},
        {**nominal,"obstacle_height":.10,"payload_yaw":-.15},
        {**nominal,"tray_offset_y":-.03,"friction":.40},
        {**nominal,"obstacle_height":.045,"friction":.80},
        {**nominal,"friction":.16},
    ]

def curriculum_candidates(arm, factors, center, seed, count=80, boundaries=None):
    if arm == "random":
        return [scenario(c["parameters"], seed*1000+i, split="training",family="random_correction") for i,c in enumerate(finite_pool(factors,seed,count))]
    if arm in {"source","minimized"} and boundaries:
        return paired_boundary_candidates(arm,factors,boundaries,seed,count)
    rng=np.random.default_rng(seed)
    output=[]
    for i in range(count*10):
        p={}
        for name,spec in factors.items():
            grid=values(spec)
            nearest=min(range(len(grid)),key=lambda j:abs(grid[j]-center[name]))
            offset=int(rng.integers(-2,3))
            p[name]=grid[min(len(grid)-1,max(0,nearest+offset))]
        if embargo(p):continue
        output.append(scenario(p, seed*1000+i, split="training",family=f"{arm}_correction"))
        if len(output)==count:return output
    raise RuntimeError("Unable to fill a bounded valid curriculum proposal set")

def paired_boundary_candidates(arm,factors,boundaries,seed,count):
    """Both arms see identical backgrounds/seeds; only causal coordinates differ."""
    rng=np.random.default_rng(seed)
    grids={k:values(v) for k,v in factors.items()}
    output=[]
    accepted=[0]*len(boundaries)
    for attempt in range(count*40):
        cluster=len(output)%len(boundaries)
        boundary=boundaries[cluster]
        causal=[k for k,v in factors.items() if abs(boundary["minimized_params"][k]-v["nominal"])>1e-8]
        if not causal:raise ValueError("Measured non-nominal boundary required")
        background={k:float(rng.choice(grid)) for k,grid in grids.items()}
        paired={}
        for choice in ("source","minimized"):
            center=boundary[f"{choice}_params"]
            p=dict(background)
            for key in causal:
                direction=1 if center[key]>factors[key]["nominal"] else -1
                severity=sorted([v for v in grids[key] if (v-center[key])*direction>=-1e-8],reverse=direction<0)
                if not severity:raise ValueError("Source lies outside finite severity grid")
                n=len(severity)
                indices=[0,0,min(1,n-1),min(1,n-1),round((n-1)/3),round(2*(n-1)/3),max(0,n-2),n-1]
                p[key]=severity[indices[accepted[cluster]%8]]
            paired[choice]=p
        if any(embargo(p) for p in paired.values()):continue
        family=f"{arm}_boundary_{cluster}"
        output.append(scenario(paired[arm],seed*1000+attempt,split="training",family=family))
        accepted[cluster]+=1
        if len(output)==count:return output
    raise RuntimeError("Paired boundary coverage exhausted the finite valid proposal pool")
