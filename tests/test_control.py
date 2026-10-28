import gzip
import pytest
from control.store import Store, Conflict, FenceLost
from control.minimizer import reduce_counterexample
from control.statistics import paired

def campaign(tmp_path):
    s=Store(tmp_path)
    cid,_=s.create("test", {"search_budget":12,"seed":1}, "create-one")
    info=s.launch_info(cid)
    s.claim(cid,1,info["worker_token"],123)
    return s,cid

def test_idempotent_creation_and_fences(tmp_path):
    s,cid=campaign(tmp_path)
    assert s.create("test",{"search_budget":12,"seed":1},"create-one")== (cid,False)
    with pytest.raises(Conflict): s.create("changed",{"search_budget":12},"create-one")
    s.action(cid,"cancel",1,"cancel-one")
    with pytest.raises(FenceLost): s.progress(cid,1,"discovery",2,12,"stale")
    s.terminated(cid,2)
    assert s.get(cid)["status"]=="canceled"
    assert s.get(cid)["episodes"]==[]

def test_artifact_tamper_and_restart(tmp_path):
    s,cid=campaign(tmp_path)
    sha=s.artifact({"actual":1})
    assert s.read_artifact(sha)=={"actual":1}
    (tmp_path/"objects"/f"{sha}.json.gz").write_bytes(gzip.compress(b'{"actual":2}'))
    with pytest.raises(ValueError,match="mismatch"): s.read_artifact(sha)
    assert s.recover()[0]["id"]==cid
    assert s.get(cid)["status"]=="interrupted"
    with pytest.raises(FenceLost): s.finish(cid,1,"completed","report")

def test_nonmonotonic_minimization_and_paired_draws():
    factors={"height":{"min":0,"max":5,"step":1,"nominal":0}}
    seen=[]
    def evaluate(p,seed):
        seen.append((p["height"],seed))
        return {"valid":True,"success":p["height"] not in {2,5},"id":str((p,seed))}
    params,steps,result=reduce_counterexample({"height":5},factors,evaluate,[11,12,13,14,15])
    assert params=={"height":2}  # crosses successful 3/4; no monotonic inference
    assert result["locally_minimal"]
    for v in {x[0] for x in seen}: assert {seed for height,seed in seen if height==v}=={11,12,13,14,15}
    params,steps,result=reduce_counterexample({"height":5},factors,evaluate,[11,12,13,14,15],max_candidates=1)
    assert not result["locally_minimal"]

def test_finite_n_noninferiority_does_not_degenerate():
    small=paired([True]*20,[True]*20)
    large=paired([True]*200,[True]*200)
    assert small["nominal_lower_95"] < -.03
    assert -.03 < large["nominal_lower_95"] < 0
    assert small["delta_interval"][0]<0<small["delta_interval"][1]

def test_global_holdout_exposure_ignores_labels_and_order(tmp_path):
    from control.lineage import register_final_exposure
    s=Store(tmp_path)
    a={"scenario_id":"a","parameters":{"x":1.},"seed":1,"family":"old"}
    b={"scenario_id":"b","parameters":{"x":2.},"seed":2,"family":"old"}
    first=s.artifact({"scenarios":[a,b],"label":"initial"})
    changed=s.artifact({"scenarios":[{**b,"family":"renamed"},{**a,"scenario_id":"renamed"}],"label":"retitled"})
    assert register_final_exposure(s,"task","protocol",first,["weights-a"])["kind"]=="first_registered_confirmation"
    assert register_final_exposure(s,"task","new-protocol",changed,["weights-a"])["kind"]=="reproduction"
    with pytest.raises(Conflict):register_final_exposure(s,"task","protocol",changed,["weights-b"])
    subset=s.artifact({"scenarios":[a]})
    with pytest.raises(Conflict):register_final_exposure(s,"task","protocol",subset,["weights-b"])
