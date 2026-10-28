import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import pytest
import engine
from control.lineage import register_final_exposure
from control.final_eval import evaluation_source_lock
from control.sample import pack,unpack
from control.store import Store,Conflict,canonical,digest

@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    root=tmp_path_factory.mktemp("sample-source");store=Store(root)
    base=engine.bootstrap_base(root/"base",n_demos=2,seed=17)
    base_sha=store.artifact(base["checkpoint"])
    index={"checkpoint_sha":base_sha,"checkpoint_hash":base["checkpoint"]["checkpoint_hash"],"manifest_sha":store.artifact(base["manifest"]),"demo_shas":[store.artifact(d) for d in base["demos"]]}
    (root/"base/index.json").write_bytes(canonical(index))
    config={"seed":1,"search_budget":2,"base_checkpoint_sha":base_sha,"base_index_sha":store.artifact(index),"task_sha":engine.TASK_SPEC_HASH}
    parent,_=store.create("Synthetic import fixture",config,"sample-parent-key")
    info=store.launch_info(parent);store.claim(parent,1,info["worker_token"],123)
    episode=engine.run_episode(engine.nominal_scenario(7),base["checkpoint"],trace=True)
    store.save_episode(parent,1,"fixture-identity",episode,{"id":parent+"-episode","success":episode["success"],"status":"completed"})
    call=store.provider_start(parent,1,"fixture",{"provider":"synthetic"})
    store.provider_finish(call,"ok",{"provider":"synthetic","status":"ok","usage":{"input_tokens":1}})
    store.finish(parent,1,"completed","report",{"report":{"label":"Synthetic fixture, not final evaluation"}})
    # A tiny synthetic exposure registry tests import protection; no final evaluator runs.
    evaluation=evaluation_source_lock()
    manifest={"schema":"synthetic-test-manifest","scenarios":[engine.nominal_scenario(77)],"evaluation_source_sha":evaluation["sha256"],"evaluation_source_files":evaluation["files"]}
    manifest_sha=store.artifact(manifest)
    final,_=store.create("Synthetic registry fixture",{"kind":"registered_evaluation","parent_campaign_id":parent,"seed":0,"search_budget":1,"task_sha":engine.TASK_SPEC_HASH,"registered_manifest_sha":manifest_sha,"base_checkpoint_sha":base_sha,"evaluation_source_sha":evaluation["sha256"],"evaluation_source_lock_sha":store.artifact(evaluation)},"sample-child-key")
    info=store.launch_info(final);store.claim(final,1,info["worker_token"],123)
    register_final_exposure(store,engine.TASK_SPEC_HASH,"test-protocol",manifest_sha,[base_sha])
    store.finish(final,1,"completed","report",{"report":{"label":"Synthetic registry only"}})
    supplement,_=store.create("Synthetic supplemental replay",{"kind":"challenge","parent_campaign_id":parent,"seed":1,"search_budget":2},"sample-supplement-key")
    info=store.launch_info(supplement);store.claim(supplement,1,info["worker_token"],123)
    for i in range(2):store.save_episode(supplement,1,f"supplement-{i}",episode,{"id":supplement+f"-e{i}","status":"completed","success":episode["success"]})
    store.finish(supplement,1,"completed","report",{"report":{"label":"Synthetic replay fixture"}})
    with store.transaction() as db:
        row=store._row(db,parent);payload=json.loads(row["payload"])
        payload["registered_report"]={"evaluation_campaign_id":final,"label":"Synthetic registry only"}
        payload["supplementary_reproductions"]=[{"campaign_id":supplement,"scope":"Synthetic import fixture"}]
        db.execute("UPDATE campaigns SET payload=? WHERE id=?",(canonical(payload).decode(),parent))
    png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=")
    folder=root/"renders"/parent;folder.mkdir(parents=True);(folder/"source.png").write_bytes(png)
    (root/".env").write_text("API_KEY=never-package-this\n")
    archive=root.parent/(root.name+".tar.xz");receipt=pack(store,parent,archive)
    return {"source":store,"parent":parent,"final":final,"supplement":supplement,"manifest_sha":manifest_sha,"base_sha":base_sha,"archive":archive,"receipt":receipt,"png":png}

def rewrite_archive(sample,tmp_path,mutate):
    members=[]
    with tarfile.open(sample["archive"],"r:xz") as archive:
        for member in archive:members.append((copy.copy(member),archive.extractfile(member).read()))
    mutate(members)
    path=tmp_path/"tampered.tar.xz"
    with tarfile.open(path,"w:xz") as archive:
        for info,raw in members:info.size=len(raw);archive.addfile(info,io.BytesIO(raw))
    path.with_suffix(path.suffix+".sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest()+"  "+path.name+"\n")
    return path

def test_lossless_offline_roundtrip_and_idempotence(sample,tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"run_episode",lambda *a,**k:pytest.fail("Importer invoked physics"))
    destination=Store(tmp_path/"imported")
    result=unpack(sample["archive"],destination)
    assert result["imported"] and result["campaign_ids"]==[sample["parent"],sample["final"],sample["supplement"]]
    expected=sample["source"].get(sample["parent"]);expected["recorded"]=True
    assert destination.get(sample["parent"])==expected
    assert destination.get(sample["final"])==sample["source"].get(sample["final"])
    for i in range(2):assert destination.episode(sample["supplement"]+f"-e{i}")["evidence_hash"]
    for path in sample["source"].path.joinpath("base").iterdir():
        if path.is_file():assert (destination.path/"base"/path.name).read_bytes()==path.read_bytes()
    assert (destination.path/"renders"/sample["parent"]/"source.png").read_bytes()==sample["png"]
    assert not (destination.path/".env").exists()
    assert unpack(sample["archive"],destination)["already_present"]
    assert result["network_requests"]==result["physics_runs"]==0

def test_import_preserves_global_exposure_rejection(sample,tmp_path):
    destination=Store(tmp_path/"exposure");unpack(sample["archive"],destination)
    with pytest.raises(Conflict,match="different adaptive checkpoints"):
        register_final_exposure(destination,engine.TASK_SPEC_HASH,"test-protocol",sample["manifest_sha"],["a"*64])
    with sample["source"].connect() as a,destination.connect() as b:
        for table in ("final_exposures","final_cases"):
            assert [dict(r) for r in a.execute("SELECT * FROM "+table)]==[dict(r) for r in b.execute("SELECT * FROM "+table)]

def test_archive_is_deterministic_and_excludes_runtime_secrets(sample,tmp_path):
    second=tmp_path/"second.tar.xz"
    assert pack(sample["source"],sample["parent"],second)["sha256"]==sample["receipt"]["sha256"]
    with tarfile.open(second,"r:xz") as archive:
        assert all(".env" not in m.name for m in archive)
    assert b"never-package-this" not in second.read_bytes()

def test_refuses_active_or_conflicting_target(sample,tmp_path):
    target=Store(tmp_path/"active");target.create("active",{"search_budget":1},"active-idempotency")
    with pytest.raises(ValueError,match="active"):unpack(sample["archive"],target)
    target=Store(tmp_path/"conflict");unpack(sample["archive"],target)
    with target.transaction() as db:db.execute("UPDATE campaigns SET name='changed' WHERE id=?",(sample["parent"],))
    with pytest.raises(ValueError,match="conflict"):unpack(sample["archive"],target)

@pytest.mark.parametrize("kind",["traversal","duplicate","symlink","missing"])
def test_unsafe_tar_members_leave_no_partial_install(sample,tmp_path,kind):
    def mutate(members):
        if kind=="traversal":members.append((tarfile.TarInfo("../escape"),b"bad"))
        elif kind=="duplicate":members.append(copy.deepcopy(members[1]))
        elif kind=="symlink":
            info=tarfile.TarInfo("base/evil");info.type=tarfile.SYMTYPE;info.linkname="/tmp/escape";members.append((info,b""))
        else:members.pop()
    archive=rewrite_archive(sample,tmp_path,mutate);target=Store(tmp_path/"target")
    with pytest.raises(ValueError):unpack(archive,target)
    assert target.list_campaigns()==[] and not list((target.path/"objects").iterdir())

def test_outer_hash_and_rehashed_inner_checkpoint_tamper(sample,tmp_path):
    target=Store(tmp_path/"target")
    with pytest.raises(ValueError,match="SHA-256"):unpack(sample["archive"],target,"0"*64)
    def mutate(members):
        value=sample["source"].read_artifact(sample["base_sha"]);value["weights"]["w1"][0][0]+=.01
        raw=canonical(value);sha=hashlib.sha256(raw).hexdigest();name=f"objects/{sha}.json"
        manifest=json.loads(members[0][1]);manifest["checksums"][name]=sha;members[0]=(members[0][0],canonical(manifest))
        members.append((tarfile.TarInfo(name),raw))
    archive=rewrite_archive(sample,tmp_path,mutate)
    with pytest.raises(ValueError,match="checkpoint inner hash"):unpack(archive,target)
    assert target.list_campaigns()==[]

def test_exposure_registry_cannot_be_dropped_after_resigning(sample,tmp_path):
    def mutate(members):
        manifest=json.loads(members[0][1])
        for i,(info,raw) in enumerate(members):
            if info.name=="metadata/sql.json":
                value=json.loads(raw);value["tables"]["final_cases"]=[];raw=canonical(value);members[i]=(info,raw)
                manifest["checksums"][info.name]=hashlib.sha256(raw).hexdigest()
        members[0]=(members[0][0],canonical(manifest))
    archive=rewrite_archive(sample,tmp_path,mutate);target=Store(tmp_path/"target")
    with pytest.raises(ValueError,match="exposure"):unpack(archive,target)
    assert target.list_campaigns()==[]

def test_standalone_import_has_no_api_dependency(sample,tmp_path):
    env={k:v for k,v in os.environ.items() if not k.endswith("API_KEY")}
    target=tmp_path/"cli"
    result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/"scripts/import_recorded_sample.py"),"--archive",str(sample["archive"]),"--data",str(target)],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    report=json.loads(result.stdout);assert report["imported"] and report["physics_runs"]==0

def test_evaluation_digest_requires_a_bound_snapshot(sample,tmp_path):
    def mutate(members):
        value={"evaluation_source_sha":"0"*64};raw=canonical(value);sha=hashlib.sha256(raw).hexdigest();name=f"objects/{sha}.json"
        manifest=json.loads(members[0][1]);manifest["checksums"][name]=sha;members[0]=(members[0][0],canonical(manifest));members.append((tarfile.TarInfo(name),raw))
    archive=rewrite_archive(sample,tmp_path,mutate)
    with pytest.raises(ValueError,match="Evaluation source"):unpack(archive,Store(tmp_path/"bad-evaluation"))

def test_target_symlink_rejected_without_writes(sample,tmp_path):
    target=Store(tmp_path/"target");outside=tmp_path/"outside";outside.mkdir();(target.path/"base").symlink_to(outside)
    with pytest.raises(ValueError,match="symlink"):unpack(sample["archive"],target)
    assert not list(outside.iterdir()) and target.list_campaigns()==[]
