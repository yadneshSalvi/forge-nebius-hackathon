"""Portable evidence archive with explicit files and verified inner hashes."""
import hashlib
import io
import re
import zipfile
from .store import ROOT, canonical

def referenced_hashes(value):
    found = set()
    if isinstance(value, dict):
        for v in value.values(): found |= referenced_hashes(v)
    elif isinstance(value, list):
        for v in value: found |= referenced_hashes(v)
    elif isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value): found.add(value)
    return found

def export_campaign(store, cid):
    campaign = store.get(cid)
    files = {"campaign.json": canonical(campaign)}
    queue = list(referenced_hashes(campaign))
    related_ids={campaign.get("registered_report",{}).get("evaluation_campaign_id")}
    related_ids.update(item.get("campaign_id") for item in campaign.get("supplementary_reproductions",[]))
    for related in sorted(ident for ident in related_ids if ident and ident!=cid):
        detail=store.get(related)
        files[f"related_campaigns/{related}.json"]=canonical(detail)
        queue.extend(referenced_hashes(detail))
    seen = set()
    while queue:
        sha = queue.pop()
        if sha in seen: continue
        seen.add(sha)
        path = store.path / "objects" / f"{sha}.json.gz"
        if not path.exists(): continue  # Source/checkpoint internal hashes can be non-object hashes.
        obj = store.read_artifact(sha)  # Every object is verified before exporting.
        files[f"objects/{sha}.json"] = canonical(obj)
        queue.extend(referenced_hashes(obj)-seen)
    for folder in ("engine", "control"):
        for path in sorted((ROOT/folder).glob("*.py")):
            if not path.name.startswith("_pilot"): files[str(path.relative_to(ROOT))] = path.read_bytes()
    for relative in ("requirements.txt", "LICENSE", "engine/ASSET_LICENSE.txt", "engine/README.md", "docs/methodology.md", "docs/runtime-and-reproduction.md", "scripts/reproduce.py", "scripts/run_registered_evaluation.py", "scripts/replay_regression.py"):
        path = ROOT/relative
        if path.is_file(): files[relative] = path.read_bytes()
    for name in ("source.png","minimized.png"):
        path=store.path/"renders"/cid/name
        if path.is_file():files[f"renders/{name}"]=path.read_bytes()
    files["REPRODUCE.md"] = b"# FORGE evidence bundle\n\nThis archive contains only simulation evidence and the authored local implementation. No credentials are required to replay frozen policies.\n\nCreate a Python 3.11 environment, install requirements.txt, then run:\n\n    python scripts/reproduce.py --bundle . --verify\n    python scripts/reproduce.py --bundle . --rerun-sample\n\nThe first command checks every manifest/object hash; the second performs fresh local MuJoCo physics with the frozen task, scenario and learned weights. Model planning calls are separately receipted and are not byte-reproducible.\n\nEvery pose is in SI units; quaternions are WXYZ. Browser interpolation is not physics. Partial/interrupted episodes are never task verdicts. Deployment, Isaac, GR00T and physical hardware were not run.\n"
    checksums = {name: hashlib.sha256(content).hexdigest() for name,content in sorted(files.items())}
    files["checksums.json"] = canonical(checksums)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name, content in sorted(files.items()): archive.writestr(name,content)
    return buffer.getvalue()
