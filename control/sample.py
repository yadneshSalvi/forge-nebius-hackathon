"""Lossless offline evidence packaging; never runs inference, physics or an API.

Raw scientific objects stay exact. Inactive launch tokens/PIDs are omitted;
the imported primary campaign is marked recorded for the application.
"""
from __future__ import annotations
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
from .store import ACTIVE, ROOT, Store, canonical, digest
from .export import referenced_hashes

CID=re.compile(r"fg-[a-f0-9]{10}\Z")
SHA=re.compile(r"[a-f0-9]{64}\Z")
ALLOWED=re.compile(r"(?:objects/[a-f0-9]{64}\.json|campaigns/fg-[a-f0-9]{10}\.json|metadata/sql\.json|base/(?:index\.json|base-checkpoint\.json|base-demonstrations\.json|base-manifest\.json|base-acquisition-attempts\.jsonl)|renders/fg-[a-f0-9]{10}/(?:source|minimized)\.png)\Z")
COLUMNS={
 "campaigns":"id name config status stage generation created_at updated_at progress payload recorded operation pid worker_token error".split(),
 "events":"seq campaign_id generation created_at kind data".split(),
 "episodes":"id campaign_id identity_key artifact_sha summary created_at".split(),
 "mutations":"key request_sha campaign_id action created_at".split(),
 "attempts":"campaign_id generation operation token status started_at ended_at pid reason".split(),
 "provider_calls":"id campaign_id generation purpose status started_at ended_at receipt_sha summary".split(),
 "final_exposures":"key task_sha protocol_sha manifest_sha checkpoint_hashes exposed_at".split(),
 "final_cases":"task_sha case_sha checkpoint_hashes exposed_at".split(),
}
KEYS={"campaigns":("id",),"events":("seq",),"episodes":("id",),"mutations":("key",),"attempts":("campaign_id","generation"),"provider_calls":("id",),"final_exposures":("key",),"final_cases":("task_sha","case_sha")}
NON_OBJECT_SHAS={"source_sha","protocol_sha","task_sha","config_sha","request_sha","case_sha","evaluation_source_sha"}
EVAL_FILES=("control/final_eval.py","control/final_report.py","control/final_worker.py","control/statistics.py","control/lineage.py","scripts/run_registered_evaluation.py")

def _eval_collect(value,state):
    if isinstance(value,dict):
        if value.get("schema") in {"forge.episode/v1","forge.numpy-waypoint-mlp/v1","forge.expert/v1","forge.demonstration/v1"}:return
        if "evaluation_source_sha" in value:
            claim=value["evaluation_source_sha"]
            if not isinstance(claim,str) or not SHA.fullmatch(claim):raise ValueError("Malformed evaluation digest")
            state["claims"].add(claim)
        if "evaluation_source_lock_sha" in value:
            lock=value["evaluation_source_lock_sha"]
            if not isinstance(lock,str) or not SHA.fullmatch(lock):raise ValueError("Malformed evaluation lock artifact")
            state["locks"].add(lock)
        if "evaluation_source_files" in value:state["maps"].append(value["evaluation_source_files"])
        for child in value.values():
            if isinstance(child,(dict,list)):_eval_collect(child,state)
    elif isinstance(value,list):
        for child in value:
            if isinstance(child,(dict,list)):_eval_collect(child,state)

def _eval_validate(state,load):
    if not any(state.values()):return
    files={name:_hash_file(ROOT/name) for name in EVAL_FILES};sha=digest(files)
    if state["claims"]!={sha} or (not state["locks"] and not state["maps"]):raise ValueError("Evaluation source digest has no matching file-map lock")
    if any(value!=files for value in state["maps"]):raise ValueError("Evaluation source file-map mismatch")
    for lock in state["locks"]:
        if load(lock)!={"files":files,"sha256":sha}:raise ValueError("Evaluation source lock mismatch")

def _pairs(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise ValueError("Duplicate JSON key in recorded sample")
        out[key]=value
    return out

def _json(raw):
    return json.loads(raw,object_pairs_hook=_pairs,parse_constant=lambda value:(_ for _ in ()).throw(ValueError("Nonfinite recorded JSON")))

def _hash_file(path):
    with Path(path).open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()

def _engine_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def _no_credentials(value):
    if isinstance(value,dict):
        for key,child in value.items():
            name=key.lower().replace("-","_")
            if (name in {"authorization","api_key","access_token","refresh_token","password","private_key","secret"} or name.endswith("_api_key")) and child not in (None,""):
                raise ValueError("Credential field cannot enter a recorded sample")
            _no_credentials(child)
    elif isinstance(value,list):
        for child in value:
            if isinstance(child,(dict,list)):_no_credentials(child)

def _required_refs(value):
    if isinstance(value,dict):
        if value.get("schema") in {"forge.episode/v1","forge.numpy-waypoint-mlp/v1","forge.expert/v1","forge.demonstration/v1"}:return set()
        found=set()
        for key,child in value.items():
            if key.endswith("_sha") and key not in NON_OBJECT_SHAS and child is not None:
                if not isinstance(child,str) or not SHA.fullmatch(child):raise ValueError("Malformed recorded artifact reference")
                found.add(child)
            elif key.endswith("_shas"):
                if not isinstance(child,list) or not all(isinstance(x,str) and SHA.fullmatch(x) for x in child):raise ValueError("Malformed recorded artifact reference list")
                found.update(child)
            else:found.update(_required_refs(child))
        return found
    if isinstance(value,list):
        found=set()
        for child in value:
            if isinstance(child,(dict,list)):found.update(_required_refs(child))
        return found
    return set()

def _object_integrity(value):
    if not isinstance(value,dict):return
    schema=value.get("schema")
    if schema in {"forge.numpy-waypoint-mlp/v1","forge.expert/v1"}:
        if _engine_hash({k:v for k,v in value.items() if k!="checkpoint_hash"})!=value.get("checkpoint_hash"):raise ValueError("Recorded checkpoint inner hash mismatch")
        if schema=="forge.numpy-waypoint-mlp/v1" and _engine_hash(value.get("weights"))!=value.get("training",{}).get("final_weights_hash"):raise ValueError("Recorded checkpoint weight hash mismatch")
    elif schema=="forge.episode/v1":
        if _engine_hash({k:v for k,v in value.items() if k not in {"evidence_hash","timing"}})!=value.get("evidence_hash"):raise ValueError("Recorded episode inner hash mismatch")
    elif schema=="forge.demonstration/v1":
        episode=value.get("episode",{});_object_integrity(episode)
        fields=("scenario","observation","target","source_episode_id","source_episode_hash","task_spec_hash","expert_checkpoint_hash","oracle")
        if "demo_"+_engine_hash({k:value[k] for k in fields})[:20]!=value.get("demo_id"):raise ValueError("Recorded demonstration inner hash mismatch")
        bindings={"scenario":"scenario","observation":"policy_observation","target":"policy_action","oracle":"oracle","source_episode_id":"episode_id","source_episode_hash":"evidence_hash","task_spec_hash":"task_spec_hash"}
        if any(value.get(d)!=episode.get(e) for d,e in bindings.items()) or episode.get("status")!="completed" or episode.get("success") is not True:raise ValueError("Recorded demonstration source binding mismatch")

def _clean_row(table,row,primary=None,recorded=False):
    out=dict(row)
    if table=="campaigns":
        out["pid"]=None;out["worker_token"]=None
        if recorded and out["id"]==primary:out["recorded"]=1
    elif table=="attempts":out["pid"]=None;out["token"]="recorded-inactive"
    return out

def _public_campaign(row,tables):
    out=dict(row)
    for key in ("config","progress","payload"):out[key]=_json(out[key])
    out["recorded"]=bool(out["recorded"]);out.update(out.pop("payload"));out.pop("pid",None);out.pop("worker_token",None)
    cid=row["id"]
    out["events"]=[{**r,"data":_json(r["data"])} for r in sorted(tables["events"],key=lambda r:r["seq"]) if r["campaign_id"]==cid]
    out["episodes"]=[_json(r["summary"]) for r in sorted(tables["episodes"],key=lambda r:(r["created_at"],r["id"])) if r["campaign_id"]==cid]
    out["attempts"]=[{k:r[k] for k in ("campaign_id","generation","operation","status","started_at","ended_at","reason")} for r in sorted(tables["attempts"],key=lambda r:r["generation"]) if r["campaign_id"]==cid]
    out["provider_calls"]=[{**r,"summary":_json(r["summary"])} for r in sorted(tables["provider_calls"],key=lambda r:r["started_at"]) if r["campaign_id"]==cid]
    return out

def _case_keys(manifest):
    return sorted({digest({"parameters":{k:(float(v) if float(v)!=0 else 0.0) for k,v in s["parameters"].items()},"seed":int(s["seed"])}) for s in manifest["scenarios"]})

def _snapshot(store,cid):
    if not CID.fullmatch(cid):raise ValueError("Malformed primary campaign ID")
    with store.connect() as db:
        db.execute("BEGIN")
        primary=db.execute("SELECT * FROM campaigns WHERE id=?",(cid,)).fetchone()
        if primary is None:raise ValueError("Primary campaign not found")
        payload=_json(primary["payload"])
        related=payload.get("registered_report",{}).get("evaluation_campaign_id")
        ids=[cid]+([related] if related and related!=cid else [])
        ids.extend(item["campaign_id"] for item in payload.get("supplementary_reproductions",[]) if isinstance(item,dict) and item.get("campaign_id"))
        ids=list(dict.fromkeys(ids))
        if not all(isinstance(x,str) and CID.fullmatch(x) for x in ids):raise ValueError("Malformed related campaign ID")
        placeholders=",".join("?" for _ in ids)
        tables={name:[] for name in COLUMNS}
        tables["campaigns"]=[_clean_row("campaigns",r) for r in db.execute(f"SELECT * FROM campaigns WHERE id IN ({placeholders})",ids)]
        if {r["id"] for r in tables["campaigns"]}!=set(ids) or any(r["status"]!="completed" for r in tables["campaigns"]):raise ValueError("Only completed parent/related evidence can be packed")
        for name in ("events","episodes","mutations","attempts","provider_calls"):
            tables[name]=[_clean_row(name,r) for r in db.execute(f"SELECT * FROM {name} WHERE campaign_id IN ({placeholders})",ids)]
        existing={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        exposure_keys,case_keys=set(),set()
        for row in tables["campaigns"]:
            config=_json(row["config"])
            if config.get("kind")=="registered_evaluation":
                m=store.read_artifact(config["registered_manifest_sha"]);cases=_case_keys(m)
                exposure_keys.add(digest({"task":config["task_sha"],"physical_cases":cases}))
                case_keys.update((config["task_sha"],case) for case in cases)
        if exposure_keys:
            if not {"final_exposures","final_cases"}<=existing:raise ValueError("Registered evidence is missing its exposure registry")
            tables["final_exposures"]=[dict(r) for r in db.execute("SELECT * FROM final_exposures") if r["key"] in exposure_keys]
            tables["final_cases"]=[dict(r) for r in db.execute("SELECT * FROM final_cases") if (r["task_sha"],r["case_sha"]) in case_keys]
            if {r["key"] for r in tables["final_exposures"]}!=exposure_keys or {(r["task_sha"],r["case_sha"]) for r in tables["final_cases"]}!=case_keys:raise ValueError("Registered exposure registry is incomplete")
    for name in tables:tables[name].sort(key=lambda row:tuple(row[k] for k in KEYS[name]))
    return ids,tables

def _base_files(store,index):
    checkpoint=store.read_artifact(index["checkpoint_sha"])
    demos=[store.read_artifact(sha) for sha in index["demo_shas"]]
    manifest=store.read_artifact(index["manifest_sha"])
    expected={"index.json":index,"base-checkpoint.json":checkpoint,"base-demonstrations.json":demos,"base-manifest.json":manifest}
    files={}
    for name,value in expected.items():
        path=store.path/"base"/name
        if path.is_symlink():raise ValueError("Base-cache symlink rejected")
        if path.is_file():
            raw=path.read_bytes()
            if _json(raw)!=value:raise ValueError("Local base cache differs from the campaign's frozen base")
        else:raw=canonical(value)+(b"" if name=="index.json" else b"\n")
        files["base/"+name]=raw
    attempts=store.path/"base/base-acquisition-attempts.jsonl"
    if attempts.is_symlink():raise ValueError("Base acquisition symlink rejected")
    if attempts.is_file():
        raw=attempts.read_bytes();episodes=[_json(line) for line in raw.splitlines() if line.strip()]
    else:
        episodes=[d["episode"] for d in demos];raw=b"".join(canonical(e)+b"\n" for e in episodes)
    if [e["episode_id"] for e in episodes]!=[a["episode_id"] for a in manifest["attempts"]]:raise ValueError("Base acquisition history is incomplete or mismatched")
    for e in episodes:_object_integrity(e)
    files["base/base-acquisition-attempts.jsonl"]=raw
    return files

def pack(store,cid,output):
    ids,tables=_snapshot(store,cid)
    campaigns=[_public_campaign(next(r for r in tables["campaigns"] if r["id"]==campaign_id),tables) for campaign_id in ids]
    primary=campaigns[0];index_sha=primary.get("base_index_sha") or primary["config"].get("base_index_sha")
    index=store.read_artifact(index_sha)
    files={f"campaigns/{c['id']}.json":canonical(c) for c in campaigns}
    files["metadata/sql.json"]=canonical({"schema":"forge.recorded-sql/v1","tables":tables})
    files.update(_base_files(store,index))
    for campaign_id in ids:
        for name in ("source.png","minimized.png"):
            path=store.path/"renders"/campaign_id/name
            if path.is_symlink():raise ValueError("Render symlink rejected")
            if path.is_file():files[f"renders/{campaign_id}/{name}"]=path.read_bytes()
    refs=referenced_hashes(campaigns)|referenced_hashes(tables)|referenced_hashes(index)
    required=_required_refs(campaigns)|_required_refs(tables)|_required_refs(index)
    objects={};seen=set();queue=list(refs);evaluation={"claims":set(),"locks":set(),"maps":[]}
    _eval_collect(campaigns,evaluation)
    while queue:
        sha=queue.pop()
        if sha in seen:continue
        seen.add(sha);path=store.path/"objects"/f"{sha}.json.gz"
        if not path.is_file():continue
        if path.is_symlink():raise ValueError("Object symlink rejected")
        obj=store.read_artifact(sha);_object_integrity(obj);_no_credentials(obj);_eval_collect(obj,evaluation)
        objects[sha]=path;required.update(_required_refs(obj));queue.extend(referenced_hashes(obj)-seen)
    _eval_validate(evaluation,store.read_artifact)
    if required-set(objects):raise ValueError("Recorded evidence has missing referenced objects")
    for name,raw in files.items():
        if name.endswith(".json"):_no_credentials(_json(raw))
    checks={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
    checks.update({f"objects/{sha}.json":sha for sha in objects})
    manifest={"schema":"forge.recorded-sample/v1","primary_campaign_id":cid,"campaign_ids":ids,"checksums":checks,"scope":"Lossless scientific evidence and SQL lineage; inactive launch tokens/PIDs excluded; primary marked recorded on import"}
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    handle,temporary=tempfile.mkstemp(prefix=".forge-pack-",suffix=".tar.xz",dir=output.parent);os.close(handle)
    def add(archive,name,raw):
        info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o644;info.mtime=0
        archive.addfile(info,io.BytesIO(raw))
    try:
        with tarfile.open(temporary,"w:xz",preset=6) as archive:
            add(archive,"manifest.json",canonical(manifest))
            for name,raw in sorted(files.items()):add(archive,name,raw)
            for sha,path in sorted(objects.items()):
                raw=gzip.decompress(path.read_bytes())
                if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError("Object changed during sample packing")
                add(archive,f"objects/{sha}.json",raw)
        sha=_hash_file(temporary)
        if output.exists() and _hash_file(output)!=sha:raise ValueError("Refusing to overwrite a different recorded sample")
        os.replace(temporary,output)
    finally:Path(temporary).unlink(missing_ok=True)
    output.with_suffix(output.suffix+".sha256").write_text(sha+"  "+output.name+"\n")
    return {"path":str(output.resolve()),"sha256":sha,"bytes":output.stat().st_size,"objects":len(objects),"campaigns":len(campaigns),"exposure_cases":len(tables["final_cases"])}

def _validate_metadata(manifest,metadata,load_object,objects):
    ids=manifest.get("campaign_ids",[]);primary=manifest.get("primary_campaign_id")
    if not isinstance(ids,list) or not 1<=len(ids)<=8 or len(ids)!=len(set(ids)) or primary not in ids or not all(isinstance(cid,str) and CID.fullmatch(cid) for cid in ids):raise ValueError("Malformed recorded campaign manifest")
    sql=_json(metadata.get("metadata/sql.json",b"{}"))
    if sql.get("schema")!="forge.recorded-sql/v1" or set(sql.get("tables",{}))!=set(COLUMNS):raise ValueError("Unsupported recorded SQL snapshot")
    tables=sql["tables"]
    for table,columns in COLUMNS.items():
        rows=tables[table]
        if not isinstance(rows,list) or any(not isinstance(row,dict) or set(row)!=set(columns) for row in rows):raise ValueError("Recorded SQL columns mismatch")
        keys=[tuple(row[k] for k in KEYS[table]) for row in rows]
        if len(keys)!=len(set(keys)):raise ValueError("Duplicate recorded SQL primary key")
        if table in {"events","episodes","mutations","attempts","provider_calls"} and any(row["campaign_id"] not in ids for row in rows):raise ValueError("SQL row references an unpackaged campaign")
    if {r["id"] for r in tables["campaigns"]}!=set(ids):raise ValueError("Recorded campaign SQL is incomplete")
    for row in tables["campaigns"]:
        if row["status"]!="completed" or row["pid"] is not None or row["worker_token"] is not None:raise ValueError("Active or credential-bearing campaign cannot be imported")
        if _public_campaign(row,tables)!=_json(metadata.get(f"campaigns/{row['id']}.json",b"{}")):raise ValueError("Campaign metadata and SQL disagree")
    if any(row["status"] in {"queued","running"} or row["token"]!="recorded-inactive" or row["pid"] is not None for row in tables["attempts"]):raise ValueError("Active attempt cannot be imported")
    if any(row["status"]=="running" for row in tables["provider_calls"]):raise ValueError("Active provider call cannot be imported")
    required=_required_refs(tables)
    for cid in ids:required.update(_required_refs(_json(metadata[f"campaigns/{cid}.json"])))
    index=_json(metadata.get("base/index.json",b"{}"));required.update(_required_refs(index))
    if required-set(objects):raise ValueError("Recorded sample is missing referenced objects")
    checkpoint=load_object(index["checkpoint_sha"]);demos=[load_object(s) for s in index["demo_shas"]]
    if [d["demo_id"] for d in demos]!=checkpoint.get("training",{}).get("demo_ids"):raise ValueError("Base demonstration lineage mismatch")
    expected={"base-checkpoint.json":checkpoint,"base-demonstrations.json":demos,"base-manifest.json":load_object(index["manifest_sha"])}
    for name,value in expected.items():
        if _json(metadata.get("base/"+name,b"null"))!=value:raise ValueError("Base-cache content mismatch")
    attempts=[_json(line) for line in metadata.get("base/base-acquisition-attempts.jsonl",b"").splitlines() if line.strip()]
    if [e["episode_id"] for e in attempts]!=[a["episode_id"] for a in expected["base-manifest.json"]["attempts"]]:raise ValueError("Base acquisition evidence is incomplete")
    for episode in attempts:_object_integrity(episode)
    exposures={r["key"]:r for r in tables["final_exposures"]};cases={(r["task_sha"],r["case_sha"]):r for r in tables["final_cases"]}
    expected_exposures,expected_cases=set(),set()
    for row in tables["campaigns"]:
        config=_json(row["config"])
        if config.get("kind")=="registered_evaluation":
            registered=load_object(config["registered_manifest_sha"]);physical=_case_keys(registered)
            key=digest({"task":config["task_sha"],"physical_cases":physical});expected_exposures.add(key)
            expected_cases.update((config["task_sha"],case) for case in physical)
            if key not in exposures:raise ValueError("Recorded final exposure registration is missing")
            owners=_json(exposures[key]["checkpoint_hashes"])
            if any(sha not in objects for sha in owners):raise ValueError("Exposed checkpoint artifacts are missing")
            for case in physical:
                item=cases.get((config["task_sha"],case))
                if item is None or _json(item["checkpoint_hashes"])!=owners:raise ValueError("Recorded physical-case exposure owner mismatch")
    if set(exposures)!=expected_exposures or set(cases)!=expected_cases:raise ValueError("Recorded final exposure registry is incomplete or has extra cases")
    return tables

def _target(root,name):
    path=root
    for part in Path(name).parts:
        path=path/part
        if path.is_symlink():raise ValueError("Import target symlink rejected")
    if not path.resolve().is_relative_to(root):raise ValueError("Unsafe import destination")
    return path

def _install(store,manifest,metadata,tables,staged,archive_sha):
    root=store.path.resolve();primary=manifest["primary_campaign_id"];ids=set(manifest["campaign_ids"])
    installed=[]
    try:
        with store.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS final_exposures (key TEXT PRIMARY KEY,task_sha TEXT,protocol_sha TEXT,manifest_sha TEXT,checkpoint_hashes TEXT,exposed_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS final_cases (task_sha TEXT,case_sha TEXT,checkpoint_hashes TEXT,exposed_at TEXT,PRIMARY KEY(task_sha,case_sha))")
            if db.execute("SELECT 1 FROM campaigns WHERE status IN ('queued','running','pause_requested','cancel_requested')").fetchone() or db.execute("SELECT 1 FROM provider_calls WHERE status='running'").fetchone() or db.execute("SELECT 1 FROM attempts WHERE status IN ('queued','running')").fetchone():raise ValueError("Cannot import while local work is active")
            existing={name:[dict(row) for row in db.execute(f"SELECT * FROM {name}")] for name in COLUMNS}
            fresh=not existing["campaigns"]
            if fresh and any(existing.values()):raise ValueError("Import requires an empty or identical database")
            if not fresh:
                if not ids<={r["id"] for r in existing["campaigns"]}:raise ValueError("Import requires empty database or identical existing campaigns")
                for name in COLUMNS:
                    keys={tuple(r[k] for k in KEYS[name]) for r in tables[name]}
                    actual=[r for r in existing[name] if (r.get("campaign_id") in ids if "campaign_id" in COLUMNS[name] else r["id"] in ids if name=="campaigns" else tuple(r[k] for k in KEYS[name]) in keys)]
                    normalize=lambda rows:sorted(canonical(_clean_row(name,r,primary,True)) for r in rows)
                    if normalize(actual)!=normalize(tables[name]):raise ValueError("Existing campaign or exposure metadata conflicts with the sample")
            destinations=[]
            for name,path in staged.items():
                relative=f"objects/{Path(name).stem}.json.gz" if name.startswith("objects/") else name
                destination=_target(root,relative)
                if destination.exists():
                    if not destination.is_file():raise ValueError("Existing import destination is not a file")
                    if name.startswith("objects/"):
                        if hashlib.sha256(gzip.decompress(destination.read_bytes())).hexdigest()!=Path(name).stem:raise ValueError("Existing object conflicts with the sample")
                    elif destination.read_bytes()!=path.read_bytes():raise ValueError("Existing base file or render conflicts with the sample")
                else:destinations.append((path,destination))
            for path,destination in destinations:
                destination.parent.mkdir(parents=True,exist_ok=True);os.replace(path,destination);installed.append(destination)
            if fresh:
                for name,columns in COLUMNS.items():
                    placeholders=",".join("?" for _ in columns)
                    for row in tables[name]:
                        row=_clean_row(name,row,primary,True)
                        db.execute(f"INSERT INTO {name} ({','.join(columns)}) VALUES ({placeholders})",[row[k] for k in columns])
            else:db.execute("UPDATE campaigns SET recorded=1 WHERE id=?",(primary,))
    except BaseException:
        for path in reversed(installed):path.unlink(missing_ok=True)
        raise
    return {"imported":fresh,"already_present":not fresh,"primary_campaign_id":primary,"campaign_ids":manifest["campaign_ids"],"objects":sum(n.startswith("objects/") for n in staged),"episodes":len(tables["episodes"]),"exposure_cases":len(tables["final_cases"]),"sha256":archive_sha,"network_requests":0,"physics_runs":0}

def unpack(path,store,expected_sha=None):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError("Recorded sample must be a regular archive file")
    if expected_sha is None:
        sidecar=path.with_suffix(path.suffix+".sha256")
        if sidecar.is_symlink() or not sidecar.is_file():raise ValueError("An expected SHA-256 or archive sidecar is required")
        fields=sidecar.read_text().split()
        if not fields:raise ValueError("Recorded archive SHA-256 sidecar is empty")
        expected_sha=fields[0]
    if not isinstance(expected_sha,str) or not SHA.fullmatch(expected_sha) or _hash_file(path)!=expected_sha:raise ValueError("Recorded sample archive SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix=".forge-import-",dir=store.path.parent) as temporary:
        stage=Path(temporary);metadata={};staged={};objects={};seen=set();total=0;required=set();evaluation={"claims":set(),"locks":set(),"maps":[]}
        with tarfile.open(path,"r:xz") as archive:
            iterator=iter(archive);first=next(iterator,None)
            if first is None or first.name!="manifest.json" or not first.isfile() or first.size>5_000_000:raise ValueError("Invalid recorded sample manifest")
            manifest_raw=archive.extractfile(first).read();manifest=_json(manifest_raw)
            if canonical(manifest)!=manifest_raw or manifest.get("schema")!="forge.recorded-sample/v1":raise ValueError("Unsupported or noncanonical recorded sample manifest")
            expected=manifest.get("checksums",{})
            if not isinstance(expected,dict) or not expected or len(expected)>30000 or any(not ALLOWED.fullmatch(name) or not isinstance(sha,str) or not SHA.fullmatch(sha) for name,sha in expected.items()):raise ValueError("Unsafe recorded sample checksum manifest")
            for member in iterator:
                if not member.isfile() or member.issparse() or not ALLOWED.fullmatch(member.name) or member.name not in expected or member.name in seen or member.size>50_000_000:raise ValueError("Unsafe, duplicate or unexpected recorded sample member")
                total+=member.size
                if total>2_000_000_000:raise ValueError("Recorded sample exceeds uncompressed bound")
                raw=archive.extractfile(member).read()
                if len(raw)!=member.size or hashlib.sha256(raw).hexdigest()!=expected[member.name]:raise ValueError("Recorded sample member checksum mismatch")
                seen.add(member.name)
                if member.name.startswith("objects/"):
                    sha=Path(member.name).stem;obj=_json(raw)
                    if sha!=expected[member.name] or canonical(obj)!=raw:raise ValueError("Recorded object filename/canonical hash mismatch")
                    _object_integrity(obj);_no_credentials(obj);required.update(_required_refs(obj));_eval_collect(obj,evaluation)
                    target=stage/(sha+".json.gz");target.write_bytes(gzip.compress(raw,compresslevel=6,mtime=0))
                    objects[sha]=target;staged[member.name]=target
                else:
                    if member.name.endswith(".json"):
                        value=_json(raw);_no_credentials(value);_eval_collect(value,evaluation)
                    metadata[member.name]=raw
                    if member.name.startswith(("base/","renders/")):
                        target=stage/"files"/member.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);staged[member.name]=target
        if seen!=set(expected):raise ValueError("Recorded sample is incomplete")
        if required-set(objects):raise ValueError("Recorded sample has missing referenced objects")
        def load_object(sha):
            if sha not in objects:raise ValueError("Recorded referenced artifact is missing")
            return _json(gzip.decompress(objects[sha].read_bytes()))
        _eval_validate(evaluation,load_object)
        tables=_validate_metadata(manifest,metadata,load_object,objects)
        if _hash_file(path)!=expected_sha:raise ValueError("Recorded archive changed during verification")
        return _install(store,manifest,metadata,tables,staged,expected_sha)
