from engine import FACTOR_SPEC
from control.acquisition import curriculum_candidates,coverage
from control.protocol import embargo

def test_two_cluster_pairing_preserves_backgrounds_and_budgets():
    nominal={k:v["nominal"] for k,v in FACTOR_SPEC.items()}
    bounds=[{"source_params":{**nominal,"obstacle_height":.17},"minimized_params":{**nominal,"obstacle_height":.115}},{"source_params":{**nominal,"friction":.16},"minimized_params":{**nominal,"friction":.24}}]
    left=curriculum_candidates("source",FACTOR_SPEC,{},12477,80,boundaries=bounds)
    right=curriculum_candidates("minimized",FACTOR_SPEC,{},12477,80,boundaries=bounds)
    assert len(left)==len(right)==80
    assert len(coverage(FACTOR_SPEC))==7
    for i,(a,b) in enumerate(zip(left,right)):
        key="obstacle_height" if i%2==0 else "friction"
        assert a["seed"]==b["seed"]
        assert all(a["parameters"][k]==b["parameters"][k] for k in FACTOR_SPEC if k!=key)
        assert not embargo(a["parameters"]) and not embargo(b["parameters"])
    assert max(right[i]["parameters"]["obstacle_height"] for i in range(0,16,2))==.17
    assert min(right[i]["parameters"]["friction"] for i in range(1,16,2))==.16
    assert len({x["parameters"]["payload_yaw"] for x in right[:16]})>=4
