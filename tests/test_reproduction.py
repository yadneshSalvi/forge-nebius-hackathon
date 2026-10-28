import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import zipfile

import pytest

import engine
from control.export import export_campaign
from control.lineage import source_lock
from control.store import Store, canonical, digest
from engine.policy import _demo_payload
from scripts.reproduce import Bundle, ReproductionError, _compare, verify_bundle


def reseal_file(root, relative):
    path=root/"checksums.json"
    checks=json.loads(path.read_bytes())
    checks[relative]=hashlib.sha256((root/relative).read_bytes()).hexdigest()
    path.write_bytes(canonical(checks))


def add_object(root, value):
    raw=canonical(value);sha=hashlib.sha256(raw).hexdigest()
    name=f"objects/{sha}.json"
    (root/name).write_bytes(raw)
    reseal_file(root,name)
    return sha


@pytest.fixture(scope="module")
def portable_bundle(tmp_path_factory):
    data=tmp_path_factory.mktemp("repro-original-data")
    base=engine.bootstrap_base(data/"base",n_demos=12,seed=17)
    store=Store(data)
    base_sha=store.artifact(base["checkpoint"])
    index={"checkpoint_sha":base_sha,"checkpoint_hash":base["checkpoint"]["checkpoint_hash"],"manifest_sha":store.artifact(base["manifest"]),"demo_shas":[store.artifact(d) for d in base["demos"]]}
    config={"search_budget":12,"seed":17,"task_sha":engine.TASK_SPEC_HASH,"source_sha":source_lock()["sha256"],"base_checkpoint_sha":base_sha}
    cid,_=store.create("Portable physics test",config,"portable-test")
    info=store.launch_info(cid);store.claim(cid,1,info["worker_token"],123)
    scene=engine.normalize_scenario({"seed":2,"parameters":{"obstacle_height":.17}})
    compact=engine.run_episode(scene,base["checkpoint"],trace=False)
    rich=engine.run_episode(scene,base["checkpoint"],trace=True)
    assert rich["success"] is False and compact["metrics"]==rich["metrics"]
    for ident,episode in [("compact-first",compact),("recorded-failure",rich)]:
        summary={"id":ident,"success":False,"status":"completed","checkpoint_hash":base["checkpoint"]["checkpoint_hash"],"trace_available":episode["trace"]["recorded"]}
        store.save_episode(cid,1,ident,episode,summary)
    expert_scene=engine.normalize_scenario({"seed":82,"split":"training","family":"corrective","parameters":{"obstacle_height":.14}})
    demo=engine.collect_demonstration(expert_scene,trace=True)
    demo_sha=store.artifact(demo)
    store.progress(cid,1,"curriculum",1,1,"Ready",{"base_index_sha":store.artifact(index),"source_lock_sha":store.artifact(source_lock()),"curriculum":{"demonstrations":[{"arm":"minimized","trajectory_sha":demo_sha,"success":True}]}})
    exported=export_campaign(store,cid)
    destination=tmp_path_factory.mktemp("exported-reproduction")
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:archive.extractall(destination)
    # The standalone command must not depend on any original SQLite/object paths.
    shutil.rmtree(data)
    return {"root":destination,"base_sha":base_sha,"demo_sha":demo_sha,"failure":rich}


@pytest.fixture
def bundle_copy(portable_bundle,tmp_path):
    target=tmp_path/"bundle"
    shutil.copytree(portable_bundle["root"],target)
    return target


def test_verifies_exported_objects_and_replays_offline(portable_bundle,monkeypatch):
    def deny_network(*args,**kwargs):raise AssertionError("offline reproduction tried to use a network connection")
    monkeypatch.setattr(socket,"create_connection",deny_network)
    bundle=verify_bundle(portable_bundle["root"])
    assert bundle.report["valid"] and bundle.report["demonstrations"]==13
    assert bundle.report["dense_oracle_audits"]==2
    result=bundle.rerun_sample()
    assert result["matches"] and result["success"] is False
    assert result["artifact_sha"]==hashlib.sha256(canonical(portable_bundle["failure"])).hexdigest()
    assert result["terminal_reason"]=="protected_contact" and result["physics_steps"]==4700
    assert bundle.rerun_demo()["matches"]


def test_standalone_cli_from_unrelated_directory(portable_bundle,tmp_path):
    env={k:v for k,v in os.environ.items() if not k.endswith("API_KEY") and k!="PYTHONPATH"}
    env.update(PYTHONNOUSERSITE="1",PYTHONDONTWRITEBYTECODE="1",FORGE_DATA_DIR=str(tmp_path/"nonexistent-data"))
    command=[sys.executable,str(portable_bundle["root"]/"scripts/reproduce.py"),"--bundle",str(portable_bundle["root"]),"--verify","--rerun-sample","--rerun-demo"]
    completed=subprocess.run(command,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert completed.returncode==0,completed.stdout+completed.stderr
    report=json.loads(completed.stdout)
    assert report["verification"]["valid"]
    assert report["rerun_sample"]["matches"] and report["rerun_demo"]["matches"]
    assert not (tmp_path/"nonexistent-data").exists()
    assert not list(portable_bundle["root"].rglob("__pycache__"))


@pytest.mark.parametrize("bad_name",["../escape.json","/tmp/escape.json","engine/../escape.json","C:/escape.json","engine\\escape.json"])
def test_path_traversal_is_rejected(bundle_copy,bad_name):
    checks=json.loads((bundle_copy/"checksums.json").read_bytes());checks[bad_name]="0"*64
    (bundle_copy/"checksums.json").write_bytes(canonical(checks))
    with pytest.raises(ReproductionError,match="unsafe"):Bundle(bundle_copy).verify_files()


def test_missing_unexpected_and_symlink_files_rejected(bundle_copy,tmp_path):
    requirements=bundle_copy/"requirements.txt";raw=requirements.read_bytes()
    requirements.unlink()
    with pytest.raises(ReproductionError,match="file set"):Bundle(bundle_copy).verify_files()
    requirements.write_bytes(raw)
    extra=bundle_copy/"unlisted.txt";extra.write_text("not exported")
    with pytest.raises(ReproductionError,match="unexpected"):Bundle(bundle_copy).verify_files()
    extra.unlink();requirements.unlink()
    external=tmp_path/"requirements.txt";external.write_bytes(raw)
    requirements.symlink_to(external)
    with pytest.raises(ReproductionError,match="symlink"):Bundle(bundle_copy).verify_files()


def test_object_inner_sha_checked_even_after_outer_manifest_rewritten(bundle_copy,portable_bundle):
    relative=f"objects/{portable_bundle['base_sha']}.json"
    p=json.loads((bundle_copy/relative).read_bytes());p["weights"]["w1"][0][0]+=.01
    (bundle_copy/relative).write_bytes(canonical(p));reseal_file(bundle_copy,relative)
    with pytest.raises(ReproductionError,match="object SHA"):verify_bundle(bundle_copy)


def test_missing_object_reference_rejected_even_if_removed_from_manifest(bundle_copy,portable_bundle):
    relative=f"objects/{portable_bundle['base_sha']}.json"
    (bundle_copy/relative).unlink()
    checks=json.loads((bundle_copy/"checksums.json").read_bytes());del checks[relative]
    (bundle_copy/"checksums.json").write_bytes(canonical(checks))
    with pytest.raises(ReproductionError,match="referenced artifact"):verify_bundle(bundle_copy)


def test_scientific_source_cannot_be_replaced_by_resealing_checksums(bundle_copy):
    path=bundle_copy/"engine/spec.py";path.write_bytes(path.read_bytes()+b"\n# changed source\n")
    reseal_file(bundle_copy,"engine/spec.py")
    with pytest.raises(ReproductionError,match="source lock"):Bundle(bundle_copy).verify_files()


def test_demo_binding_checked_after_correct_hashes_recomputed(bundle_copy,portable_bundle):
    demo=json.loads((bundle_copy/f"objects/{portable_bundle['demo_sha']}.json").read_bytes())
    demo["target"][0]+=.02
    demo["demo_id"]="demo_"+engine.content_hash(_demo_payload(demo))[:20]
    add_object(bundle_copy,demo)
    with pytest.raises(ValueError,match="source episode"):verify_bundle(bundle_copy)


def test_dense_oracle_checked_after_all_envelope_hashes_recomputed(bundle_copy,portable_bundle):
    episode=copy.deepcopy(portable_bundle["failure"])
    episode["metrics"]["forbidden_contact_points"]=0
    episode["evidence_hash"]=engine.episode_evidence_hash(episode)
    add_object(bundle_copy,episode)
    with pytest.raises(ReproductionError,match="reconstruction"):verify_bundle(bundle_copy)


def test_terminal_reason_cannot_contradict_rehashed_geometry(bundle_copy,portable_bundle):
    episode=copy.deepcopy(portable_bundle["failure"])
    episode["terminal_reason"]="success"
    episode["evidence_hash"]=engine.episode_evidence_hash(episode)
    add_object(bundle_copy,episode)
    with pytest.raises(ReproductionError,match="terminal geometry"):verify_bundle(bundle_copy)


def test_duplicate_checksum_keys_and_self_entry_rejected(bundle_copy):
    path=bundle_copy/"checksums.json";original=path.read_bytes()
    path.write_bytes(b'{"campaign.json":"'+b'0'*64+b'","campaign.json":"'+b'1'*64+b'"}')
    with pytest.raises(ReproductionError,match="duplicate JSON key"):Bundle(bundle_copy).verify_files()
    checks=json.loads(original);checks["checksums.json"]="0"*64;path.write_bytes(canonical(checks))
    with pytest.raises(ReproductionError,match="self-referential"):Bundle(bundle_copy).verify_files()


def test_tolerance_preserves_discrete_outcome_changes():
    assert not _compare({"height":.10},{"height":.10000001})
    assert _compare({"success":True},{"success":1})
    assert _compare({"points":500},{"points":501})
    assert _compare({"displacement":.003},{"displacement":.0031})

def attach_evaluation_snapshot(root):
    from scripts.reproduce import EVALUATION_FILES
    files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in EVALUATION_FILES}
    sha=hashlib.sha256(canonical(files)).hexdigest()
    lock_sha=add_object(root,{"files":files,"sha256":sha})
    report_sha=add_object(root,{"evaluation_source_sha":sha,"evaluation_source_files":files})
    relative="related_campaigns/fg-aaaaaaaaaa.json";(root/"related_campaigns").mkdir(exist_ok=True)
    (root/relative).write_bytes(canonical({"id":"fg-aaaaaaaaaa","config":{"kind":"registered_evaluation","evaluation_source_sha":sha,"evaluation_source_lock_sha":lock_sha},"report":{"artifact_sha":report_sha,"evaluation_source_sha":sha}}))
    reseal_file(root,relative)
    return sha,relative

def test_final_export_evaluation_digest_is_verified_as_file_map(bundle_copy):
    sha,_=attach_evaluation_snapshot(bundle_copy)
    assert not (bundle_copy/f"objects/{sha}.json").exists()
    assert verify_bundle(bundle_copy).report["evaluation_source_sha"]==sha

@pytest.mark.parametrize("kind",["digest","file","lock","missing_real_object"])
def test_evaluation_digest_validation_does_not_waive_tampering(bundle_copy,kind):
    sha,relative=attach_evaluation_snapshot(bundle_copy)
    if kind=="digest":add_object(bundle_copy,{"evaluation_source_sha":"0"*64})
    elif kind=="file":
        path=bundle_copy/"control/final_eval.py";path.write_bytes(path.read_bytes()+b"\n# altered evaluation\n");reseal_file(bundle_copy,"control/final_eval.py")
    elif kind=="lock":
        related=json.loads((bundle_copy/relative).read_bytes())
        related["config"]["evaluation_source_lock_sha"]=add_object(bundle_copy,{"files":{},"sha256":sha})
        (bundle_copy/relative).write_bytes(canonical(related));reseal_file(bundle_copy,relative)
    else:add_object(bundle_copy,{"evaluation_source_sha":sha,"outcomes_sha":"f"*64})
    with pytest.raises(ReproductionError,match="evaluation source|referenced artifact"):verify_bundle(bundle_copy)
