"""Run freshness and global one-time final-manifest exposure registration."""
import hashlib
import json
from .store import ROOT, canonical, digest, now, Conflict

def source_lock():
    scientific = ("runner.py","minimizer.py","protocol.py","statistics.py","worker.py","acquisition.py","discovery.py","reduction.py","curriculum.py","paired_acquisition.py","training.py","evaluation.py","providers.py","challenge.py")
    paths = sorted((ROOT/"engine").glob("*.py")) + [ROOT/"control"/n for n in scientific]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists() and not p.name.startswith("_pilot")}
    return {"files": hashes, "sha256": digest(hashes)}

def register_final_exposure(store, task_sha, protocol_sha, manifest_sha, checkpoint_hashes):
    manifest = store.read_artifact(manifest_sha)
    cases = sorted(set(digest({"parameters":{k:(float(v) if float(v)!=0 else 0.0) for k,v in s["parameters"].items()},"seed":int(s["seed"])}) for s in manifest["scenarios"]))
    if len(cases)!=len(manifest["scenarios"]): raise ValueError("Final manifest repeats the same physical case")
    key = digest({"task": task_sha, "physical_cases": cases})
    hashes = sorted(checkpoint_hashes)
    with store.transaction() as c:
        c.execute("CREATE TABLE IF NOT EXISTS final_exposures (key TEXT PRIMARY KEY, task_sha TEXT, protocol_sha TEXT, manifest_sha TEXT, checkpoint_hashes TEXT, exposed_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS final_cases (task_sha TEXT, case_sha TEXT, checkpoint_hashes TEXT, exposed_at TEXT, PRIMARY KEY(task_sha,case_sha))")
        reused=0
        for case in cases:
            prior=c.execute("SELECT * FROM final_cases WHERE task_sha=? AND case_sha=?",(task_sha,case)).fetchone()
            if prior:
                if json.loads(prior["checkpoint_hashes"])!=hashes: raise Conflict("At least one physical final case was already exposed to different adaptive checkpoints")
                reused+=1
        old = c.execute("SELECT * FROM final_exposures WHERE key=?",(key,)).fetchone()
        if old:
            if json.loads(old["checkpoint_hashes"]) != hashes: raise Conflict("Final manifest already exposed to different checkpoints; register a new never-seen set")
            return {"kind": "reproduction", "exposed_at": old["exposed_at"], "registry_key": key}
        stamp = now()
        c.execute("INSERT INTO final_exposures VALUES(?,?,?,?,?,?)",(key,task_sha,protocol_sha,manifest_sha,canonical(hashes).decode(),stamp))
        for case in cases:
            c.execute("INSERT OR IGNORE INTO final_cases VALUES(?,?,?,?)",(task_sha,case,canonical(hashes).decode(),stamp))
        return {"kind": "partially_reused_extension" if reused else "first_registered_confirmation", "exposed_at": stamp, "registry_key": key,"reused_cases":reused,"new_cases":len(cases)-reused}
