#!/usr/bin/env python3
"""Restore the included incident recording; no network, model call or physics."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control.incident import ACTIVE, Incidents
from control.store import Conflict, ROOT, Store, canonical, digest
from engine import content_hash

ARCHIVE = ROOT / "evidence/nebius-incident-test.zip"
ARCHIVE_SHA = "af6d2ead51ac44bf087569f51fb84a294fa2c85af802620c72ca21cb14d454df"
RECEIPTS = ROOT / "evidence/incident-planner-receipts.json"
RECEIPTS_SHA = "d76d284cad04f8bb8837e29735a65e6df3fce6996f06fd3966e7a6257540fe97"


def strict_json(raw):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate recording JSON key")
            value[key] = item
        return value
    def nonfinite(value):
        raise ValueError("Nonfinite recording JSON value")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def read_recording():
    if ARCHIVE.is_symlink() or not ARCHIVE.is_file() or ARCHIVE.stat().st_size > 8_000_000:
        raise ValueError("Included incident archive is missing, unsafe or oversized")
    raw = ARCHIVE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA:
        raise ValueError("Included incident archive checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if not 5 <= len(infos) <= 200 or sum(info.file_size for info in infos) > 100_000_000:
            raise ValueError("Incident archive exceeds its bounded recording size")
        if len({info.filename for info in infos}) != len(infos):
            raise ValueError("Duplicate incident archive path")
        for info in infos:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                    or str(path) != info.filename or info.is_dir()
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe incident archive path")
        files = {info.filename: archive.read(info) for info in infos}
    checksums = strict_json(files["checksums.json"])
    if set(checksums) != set(files) - {"checksums.json"} or any(hashlib.sha256(files[name]).hexdigest() != sha for name, sha in checksums.items()):
        raise ValueError("Incident file checksums disagree")
    job = strict_json(files["incident.json"])
    config = job["config"]
    if (job.get("schema") != "forge.incident/v1" or job.get("status") != "completed"
            or job.get("validity", {}).get("valid") is not True
            or content_hash(config) != job.get("config_sha")):
        raise ValueError("Only the included completed, bound incident may be restored")
    for name in ("scientific_source_lock", "adapter_lock"):
        lock = config[name]
        if content_hash(lock["files"]) != lock["sha256"] or any(checksums.get(path) != sha for path, sha in lock["files"].items()):
            raise ValueError("Included frozen source snapshot mismatch")
    if RECEIPTS.is_symlink() or not RECEIPTS.is_file() or RECEIPTS.stat().st_size > 200_000:
        raise ValueError("Included provider receipts are missing, unsafe or oversized")
    receipt_bytes = RECEIPTS.read_bytes()
    if hashlib.sha256(receipt_bytes).hexdigest() != RECEIPTS_SHA:
        raise ValueError("Included provider receipt checksum mismatch")
    records = strict_json(receipt_bytes)
    if records.get("schema") != "forge.recorded-intervention-receipts/v1" or len(records["records"]) != 5:
        raise ValueError("Unexpected recorded provider ledger")
    for entry in records["records"]:
        if digest(entry["artifact"]) != entry["receipt_sha"]:
            raise ValueError("Provider artifact identity mismatch")
        if entry["review"] and entry["review"].get("receipt_sha") != entry["receipt_sha"]:
            raise ValueError("Provider review identity mismatch")
    plans = {entry["receipt_sha"]: entry for entry in records["records"]}
    accepted = plans[config["planner_receipt_sha"]]
    if (canonical(accepted["artifact"]) != files["planner-receipt.json"]
            or canonical(accepted["review"]) != files["planner-review.json"]):
        raise ValueError("Incident and provider recording disagree")
    return raw, files, job, records["records"]


def _compatible(path, raw):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise Conflict("Recording destination contains a symlink")
    if not path.exists():
        return False
    if not path.is_file():
        raise Conflict("Recording destination is not a file")
    if path.suffixes[-2:] == [".json", ".gz"]:
        equal = gzip.decompress(path.read_bytes()) == gzip.decompress(raw)
    else:
        equal = path.read_bytes() == raw
    if not equal:
        raise Conflict("Recording conflicts with retained local evidence: " + path.name)
    return True


def unpack(store):
    archive, files, job, records = read_recording()
    config = job["config"]
    store.path = store.path.resolve()
    manager = Incidents(store)
    with manager.locked():
        if any(row["status"] in {"queued", "running", "pause_requested", "cancel_requested"} for row in store.list_campaigns()) or any(row["status"] in ACTIVE for row in manager.list()):
            raise Conflict("Stop active local work before importing the recording")
        try:
            parent = store.get(config["campaign_id"], detail=False)
        except KeyError as exc:
            raise ValueError("Import the matching recorded starter first") from exc
        if (parent["status"] != "completed"
                or parent["config"].get("source_sha") != config["scientific_source_lock"]["sha256"]
                or parent["config"].get("task_sha") != config["task_spec_hash"]
                or parent["config"].get("base_checkpoint_sha") != config["checkpoint_sha"]):
            raise Conflict("Recorded parent, task or checkpoint does not match this incident")
        with store.connect() as connection:
            row = connection.execute("SELECT artifact_sha FROM episodes WHERE campaign_id=? AND id=?", (config["campaign_id"], config["source_episode_id"])).fetchone()
        if row is None or row["artifact_sha"] != config["source_artifact_sha"]:
            raise Conflict("Recorded source does not belong to the matching parent")
        for name, sha in (("source.json", config["source_artifact_sha"]), ("checkpoint.json", config["checkpoint_sha"])):
            if canonical(store.read_artifact(sha)) != files[name]:
                raise Conflict("Original source/checkpoint evidence differs from the recording")

        destination = manager.path / job["id"]
        if not destination.name.startswith("inc-") or destination.name != job["id"] or "/" in job["id"]:
            raise ValueError("Invalid incident recording id")
        wanted = {"job.json": files["incident.json"], "frozen-export.zip": archive,
                  "frozen-export.json": canonical({"filename": "frozen-export.zip", "sha256": ARCHIVE_SHA,
                                                   "bytes": len(archive), "job_sha256": digest(job)})}
        wanted["source.json.gz"] = gzip.compress(files["source.json"], compresslevel=6, mtime=0)
        for name in ("task.json", "checkpoint.json", "planner-receipt.json", "planner-review.json", "planner-original-receipt.json"):
            wanted[name] = files[name]
        for name, raw in files.items():
            if name.startswith("episodes/"):
                wanted[PurePosixPath(name).name + ".gz"] = gzip.compress(raw, compresslevel=6, mtime=0)
        for name in {*manager.snapshot_files(config), "LICENSE", "engine/ASSET_LICENSE.txt"}:
            wanted["sources/" + name] = files[name]
        if destination.exists():
            if not destination.is_dir():
                raise Conflict("Incident recording destination exists and is not a directory")
            for name, raw in wanted.items():
                if not _compatible(destination / name, raw):
                    raise Conflict("Existing incident is incomplete; refusing to overwrite it")

        metadata = {}
        for entry in records:
            sha, artifact = entry["receipt_sha"], entry["artifact"]
            folder = store.path / ("intervention-plans" if artifact.get("count_as_provider_call", True) else "intervention-plan-derivations")
            matches = [path for path in folder.glob("*.json") if strict_json(path.read_bytes()).get("receipt_sha") == sha]
            if len(matches) > 1:
                raise Conflict("Provider recording already has duplicate receipt metadata")
            target = matches[0] if matches else folder / ("recorded-" + sha + ".json")
            metadata[target] = canonical({**artifact, "receipt_sha": sha})
            if entry["review"]:
                metadata[store.path / "intervention-plan-reviews" / (sha + ".json")] = canonical(entry["review"])
        for path, raw in metadata.items():
            _compatible(path, raw)
        if shutil.disk_usage(store.path).free < 32 * 1024 * 1024:
            raise Conflict("Insufficient disk space for the bounded incident recording")

        # Validate all collisions before any additive evidence write. The job
        # appears only after its complete staged directory has been installed.
        for entry in records:
            if store.artifact(entry["artifact"]) != entry["receipt_sha"]:
                raise ValueError("Provider artifact changed while importing")
        for path, raw in metadata.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(raw)
        already_present = destination.exists()
        if not already_present:
            temporary = Path(tempfile.mkdtemp(prefix=".recording-", dir=manager.path))
            try:
                for name, raw in wanted.items():
                    path = temporary / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        return {"imported": not already_present, "already_present": already_present, "incident_id": job["id"],
                "archive_sha256": ARCHIVE_SHA, "actual_provider_requests": 4, "local_revalidations": 1,
                "new_model_calls": 0, "new_physics_episodes": 0, "original_campaigns_modified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(unpack(Store(args.data)), sort_keys=True))
    except (OSError, ValueError, KeyError, Conflict, zipfile.BadZipFile) as exc:
        print(json.dumps({"imported": False, "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
