import copy
from types import SimpleNamespace
import pytest
from engine import TASK_SPEC_HASH
from control.final_eval import validate_registration,validate_evaluation_config,evaluation_source_lock
from control.lineage import source_lock
from control.protocol import PROTOCOL_SHA
from control.store import digest

def registration():
    # Synthetic schema fixtures only: never persisted, registered or simulated.
    source=source_lock()["sha256"]
    runs=[{"arm":arm,"seed":seed,"checkpoint_sha":digest({"mock_checkpoint":arm,"seed":seed})} for arm in ("random","source","minimized") for seed in (101,202,303,404,505)]
    nominees={arm:{"seed":404,"checkpoint_sha":next(r["checkpoint_sha"] for r in runs if r["arm"]==arm and r["seed"]==404)} for arm in ("random","source","minimized")}
    parent={"id":"mock-development","status":"completed","config":{"source_sha":source,"task_sha":TASK_SPEC_HASH,"protocol_sha":PROTOCOL_SHA,"base_checkpoint_sha":digest({"mock_base":True})},"training":{"status":"completed","runs":runs,"weights_frozen_at":"2025-01-01T00:00:00+00:00"},"report":{"nominations":nominees,"nominations_frozen_at":"2025-01-01T00:00:01+00:00"}}
    nominal={"obstacle_height":.065,"friction":.65,"payload_yaw":0.,"tray_offset_y":0.}
    scenes=[{"scenario_id":f"mock-case-{i}","split":"sealed","family":"nominal" if i<200 else "fresh_in_envelope","seed":i,"parameters":copy.deepcopy(nominal)} for i in range(500)]
    lock=evaluation_source_lock()
    manifest={"schema":"forge.root-registration/v1","parent_campaign_id":parent["id"],"task_spec_hash":TASK_SPEC_HASH,"protocol_sha":PROTOCOL_SHA,"source_sha":source,"evaluation_source_sha":lock["sha256"],"evaluation_source_files":lock["files"],"frozen_checkpoint_artifacts":sorted([parent["config"]["base_checkpoint_sha"]]+[r["checkpoint_sha"] for r in runs]),"frozen_training_runs":sorted(copy.deepcopy(runs),key=lambda r:(r["arm"],r["seed"])),"development_nominations":copy.deepcopy(nominees),"nominations_frozen_at":parent["report"]["nominations_frozen_at"],"registered_at":"2025-01-01T00:00:02+00:00","scenarios":scenes}
    return manifest,parent

def evaluation_config(manifest,parent):
    return {"kind":"registered_evaluation","parent_campaign_id":parent["id"],"task_sha":manifest["task_spec_hash"],"protocol_sha":manifest["protocol_sha"],"source_sha":manifest["source_sha"],"base_checkpoint_sha":parent["config"]["base_checkpoint_sha"],"registered_manifest_sha":digest(manifest),"evaluation_source_sha":manifest["evaluation_source_sha"],"workers":4}

def test_frozen_registration_validation():
    manifest,parent=registration()
    validate_registration(manifest,parent)
    assert len(evaluation_source_lock()["files"])==6
    changed=copy.deepcopy(manifest);changed["scenarios"][1]["seed"]=0
    with pytest.raises(ValueError,match="Repeated physical"):validate_registration(changed,parent)
    changed=copy.deepcopy(manifest);changed["scenarios"][0]["parameters"]["obstacle_height"]=.16
    with pytest.raises(ValueError,match="Nominal"):validate_registration(changed,parent)
    parent["report"]["nominations"]={}
    with pytest.raises(ValueError,match="nominations"):validate_registration(manifest,parent)

@pytest.mark.parametrize("mutation",["checkpoint","base","duplicate_seed","empty_runs","parent"])
def test_mutated_development_freeze_rejected(mutation):
    manifest,parent=registration()
    if mutation=="checkpoint":parent["training"]["runs"][0]["checkpoint_sha"]=digest({"changed":True})
    elif mutation=="base":parent["config"]["base_checkpoint_sha"]=digest({"changed_base":True})
    elif mutation=="duplicate_seed":parent["training"]["runs"][-1]=copy.deepcopy(parent["training"]["runs"][0])
    elif mutation=="empty_runs":parent["training"]["runs"]=[{}]*15
    else:parent["id"]="different-parent"
    with pytest.raises(ValueError):validate_registration(manifest,parent)

def test_swapped_mapping_cannot_hide_inside_same_checkpoint_set():
    manifest,parent=registration()
    runs=manifest["frozen_training_runs"]
    runs[0]["checkpoint_sha"],runs[1]["checkpoint_sha"]=runs[1]["checkpoint_sha"],runs[0]["checkpoint_sha"]
    with pytest.raises(ValueError,match="mapping"):validate_registration(manifest,parent)
    manifest,parent=registration()
    manifest["frozen_checkpoint_artifacts"][0]=digest({"unregistered_artifact":True})
    with pytest.raises(ValueError,match="artifact set"):validate_registration(manifest,parent)

def test_changed_nominee_is_not_selected_from_current_parent():
    manifest,parent=registration()
    run=next(r for r in parent["training"]["runs"] if r["arm"]=="minimized" and r["seed"]==101)
    parent["report"]["nominations"]["minimized"]={"seed":101,"checkpoint_sha":run["checkpoint_sha"]}
    with pytest.raises(ValueError,match="nominations changed"):validate_registration(manifest,parent)
    manifest,parent=registration()
    manifest["development_nominations"]["minimized"]["seed"]=101
    with pytest.raises(ValueError,match="nominations changed"):validate_registration(manifest,parent)

@pytest.mark.parametrize("kind",["changed","after_registration","naive","future_registration"])
def test_nomination_freeze_time_is_bound_and_ordered(kind):
    manifest,parent=registration()
    if kind=="changed":parent["report"]["nominations_frozen_at"]="2025-01-01T00:00:01.5+00:00"
    elif kind=="after_registration":
        manifest["nominations_frozen_at"]=parent["report"]["nominations_frozen_at"]="2025-01-01T00:00:03+00:00"
    elif kind=="naive":
        manifest["nominations_frozen_at"]=parent["report"]["nominations_frozen_at"]="2025-01-01T00:00:01"
    else:manifest["registered_at"]="2999-01-01T00:00:02+00:00"
    with pytest.raises(ValueError):validate_registration(manifest,parent)

def test_evaluation_and_scientific_source_locks_are_bound():
    manifest,parent=registration()
    manifest["evaluation_source_sha"]=digest({"different_evaluator":True})
    with pytest.raises(ValueError,match="evaluation source"):validate_registration(manifest,parent)
    manifest,parent=registration()
    manifest["evaluation_source_files"]["control/final_eval.py"]=digest({"changed_file":True})
    manifest["evaluation_source_sha"]=digest(manifest["evaluation_source_files"])
    with pytest.raises(ValueError,match="evaluation source"):validate_registration(manifest,parent)
    manifest,parent=registration()
    manifest["source_sha"]=parent["config"]["source_sha"]=digest({"changed_science":True})
    with pytest.raises(ValueError,match="Scientific implementation"):validate_registration(manifest,parent)

def test_shifted_labels_match_the_declared_disjoint_regions():
    manifest,parent=registration()
    manifest["scenarios"][200]["family"]="invented-family"
    with pytest.raises(ValueError,match="family"):validate_registration(manifest,parent)
    manifest,parent=registration()
    manifest["scenarios"][200]["parameters"].update(obstacle_height=.16,friction=.20)
    with pytest.raises(ValueError,match="region"):validate_registration(manifest,parent)
    manifest["scenarios"][200]["family"]="tall_low_friction"
    validate_registration(manifest,parent)
    manifest["scenarios"][201]["family"]="yaw_offset_composition"
    with pytest.raises(ValueError,match="region"):validate_registration(manifest,parent)
    manifest["scenarios"][201]["parameters"].update(payload_yaw=.15,tray_offset_y=.03)
    validate_registration(manifest,parent)

def test_signed_zero_and_missing_factor_cannot_hide_physical_cases():
    manifest,parent=registration()
    manifest["scenarios"][1]["seed"]=0
    manifest["scenarios"][1]["parameters"]["payload_yaw"]=-0.0
    with pytest.raises(ValueError,match="Repeated physical"):validate_registration(manifest,parent)
    manifest,parent=registration()
    del manifest["scenarios"][200]["parameters"]["payload_yaw"]
    with pytest.raises(ValueError,match="all four factors"):validate_registration(manifest,parent)

@pytest.mark.parametrize("field",["base_checkpoint_sha","parent_campaign_id","evaluation_source_sha","registered_manifest_sha"])
def test_resumed_job_configuration_cannot_substitute_frozen_inputs(field):
    manifest,parent=registration();config=evaluation_config(manifest,parent)
    validate_evaluation_config(manifest,parent,config)
    config[field]=digest({"substitution":field})
    with pytest.raises(ValueError,match="configuration"):validate_evaluation_config(manifest,parent,config)

def test_worker_rejects_changed_config_before_exposure_or_physics(monkeypatch):
    import control.final_eval as evaluation
    manifest,parent=registration();config=evaluation_config(manifest,parent)
    config["base_checkpoint_sha"]=digest({"wrong_base":True})
    class FakeStore:
        def get(self,*args,**kwargs):return parent
        def read_artifact(self,*args):return manifest
    monkeypatch.setattr(evaluation,"RunContext",lambda *args:SimpleNamespace(config=config))
    def forbidden(*args,**kwargs):pytest.fail("invalid freeze reached exposure/physics")
    monkeypatch.setattr(evaluation,"register_final_exposure",forbidden)
    monkeypatch.setattr(evaluation,"_physical_job",forbidden)
    with pytest.raises(ValueError,match="configuration"):evaluation.run_registered(FakeStore(),"mock-job",1)

def test_final_never_nominates_from_final_results():
    from control.final_report import make_final_report
    from control.store import digest
    runs=[{"arm":a,"seed":s,"checkpoint_sha":f"{a}-{s}"} for a in ("random","source","minimized") for s in (101,202,303,404,505)]
    nominations={a:{"seed":404,"checkpoint_sha":f"{a}-404"} for a in ("random","source","minimized")}
    scenes=[{"scenario_id":str(i),"family":"nominal" if i<200 else "shifted","seed":i,"parameters":{}} for i in range(500)]
    rows=[]
    for s in scenes:
        for p in [{"arm":"base","seed":None,"checkpoint_sha":"base"}]+runs:
            rows.append({"scenario_id":s["scenario_id"],"family":s["family"],"arm":p["arm"],"training_seed":p["seed"],"checkpoint_sha":p["checkpoint_sha"],"episode_id":f"{s['scenario_id']}-{p['arm']}-{p['seed']}","success":True,"valid":True,"terminal_reason":"success","metrics":{"forbidden_contact_steps":0}})
    class Storage:
        def artifact(self,v):return digest(v)
    class Context:
        cid="test-final";store=Storage();config={"registered_manifest_sha":"manifest","evaluation_source_sha":"source","workers":4}
    parent={"id":"parent","training":{"runs":runs},"report":{"nominations":nominations,"nominations_frozen_at":"before-final","limitations":[]}}
    report=make_final_report(Context(),parent,{"scenarios":scenes},rows,{"kind":"first_registered_confirmation"})
    assert report["nominations"]==nominations
    assert report["decision"]=="do_not_promote"
    assert report["promotion_checks"]["nominal_one_sided_95_lower_above_minus_three_points"]
    assert not report["promotion_checks"]["at_least_ten_points_above_both_nominated_comparators"]
