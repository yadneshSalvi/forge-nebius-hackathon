"""Durable metadata, generation fences, and content-addressed evidence."""
from __future__ import annotations
import contextlib
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("FORGE_DATA_DIR", ROOT / "data"))
ACTIVE = {"queued", "running", "pause_requested", "cancel_requested"}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

class Conflict(Exception): pass
class FenceLost(Exception): pass
class PauseRequested(Exception): pass

class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else DATA
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "objects").mkdir(exist_ok=True)
        (self.path / "logs").mkdir(exist_ok=True)
        self.db = self.path / "forge.sqlite3"
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS campaigns (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL,
              status TEXT NOT NULL, stage TEXT NOT NULL, generation INTEGER NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              progress TEXT NOT NULL, payload TEXT NOT NULL, recorded INTEGER NOT NULL DEFAULT 0,
              operation TEXT NOT NULL, pid INTEGER, worker_token TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL,
              generation INTEGER NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS episodes (
              id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, identity_key TEXT NOT NULL,
              artifact_sha TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(campaign_id, identity_key));
            CREATE TABLE IF NOT EXISTS mutations (
              key TEXT PRIMARY KEY, request_sha TEXT NOT NULL, campaign_id TEXT NOT NULL,
              action TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (
              campaign_id TEXT NOT NULL, generation INTEGER NOT NULL,
              operation TEXT NOT NULL, token TEXT NOT NULL, status TEXT NOT NULL,
              started_at TEXT, ended_at TEXT, pid INTEGER, reason TEXT,
              PRIMARY KEY(campaign_id,generation));
            CREATE TABLE IF NOT EXISTS provider_calls (
              id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, generation INTEGER NOT NULL,
              purpose TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
              ended_at TEXT, receipt_sha TEXT, summary TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_campaign ON events(campaign_id,seq);
            CREATE INDEX IF NOT EXISTS episodes_campaign ON episodes(campaign_id);
            """)

    @contextlib.contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        try: yield c
        finally: c.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def artifact(self, value):
        raw = canonical(value)
        sha = hashlib.sha256(raw).hexdigest()
        path = self.path / "objects" / f"{sha}.json.gz"
        if not path.exists():
            temporary = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
            temporary.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
            os.replace(temporary, path)
        return sha

    def read_artifact(self, sha):
        if not re.fullmatch(r"[a-f0-9]{64}", sha): raise ValueError("Malformed artifact hash")
        raw = gzip.decompress((self.path / "objects" / f"{sha}.json.gz").read_bytes())
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("Artifact SHA-256 mismatch; evidence is quarantined")
        return json.loads(raw)

    def _event(self, c, cid, gen, kind, data):
        c.execute("INSERT INTO events(campaign_id,generation,created_at,kind,data) VALUES(?,?,?,?,?)",
                  (cid, gen, now(), kind, canonical(data).decode()))

    def _row(self, c, cid):
        row = c.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
        if row is None: raise KeyError(cid)
        return row

    def _guard(self, c, cid, gen):
        row = self._row(c, cid)
        if row["generation"] != gen or row["status"] not in {"queued", "running", "pause_requested"}:
            raise FenceLost("Worker generation is no longer current")
        return row

    def _decode(self, row):
        out = dict(row)
        for key in ("config", "progress", "payload"): out[key] = json.loads(out[key])
        out["recorded"] = bool(out["recorded"])
        out.update(out.pop("payload"))
        out.pop("worker_token", None)
        out.pop("pid", None)
        return out

    def list_campaigns(self):
        with self.connect() as c:
            return [self._decode(r) for r in c.execute("SELECT * FROM campaigns ORDER BY recorded DESC,created_at DESC")]

    def get(self, cid, detail=True):
        with self.connect() as c:
            out = self._decode(self._row(c, cid))
            if detail:
                out["events"] = [{**dict(r), "data": json.loads(r["data"])} for r in c.execute("SELECT * FROM events WHERE campaign_id=? ORDER BY seq", (cid,))]
                out["episodes"] = [json.loads(r["summary"]) for r in c.execute("SELECT summary FROM episodes WHERE campaign_id=? ORDER BY created_at,id", (cid,))]
                out["attempts"] = [dict(r) for r in c.execute("SELECT campaign_id,generation,operation,status,started_at,ended_at,reason FROM attempts WHERE campaign_id=? ORDER BY generation", (cid,))]
                out["provider_calls"] = [{**dict(r), "summary": json.loads(r["summary"])} for r in c.execute("SELECT * FROM provider_calls WHERE campaign_id=? ORDER BY started_at", (cid,))]
            return out

    def create(self, name, config, key, recorded=False):
        req = digest({"action": "create", "name": name, "config": config})
        with self.transaction() as c:
            old = c.execute("SELECT * FROM mutations WHERE key=?", (key,)).fetchone()
            if old:
                if old["request_sha"] != req: raise Conflict("Idempotency key has different inputs")
                return old["campaign_id"], False
            active = c.execute("SELECT id FROM campaigns WHERE status IN ('queued','running','pause_requested','cancel_requested')").fetchone()
            if active: raise Conflict(f"Campaign {active['id']} owns the local worker")
            cid, token, stamp = f"fg-{uuid.uuid4().hex[:10]}", uuid.uuid4().hex, now()
            operation = config["kind"] if config.get("kind") in {"challenge","registered_evaluation"} else "discover"
            stage = operation if operation!="discover" else "planning"
            c.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                cid, name, canonical(config).decode(), "queued", stage, 1, stamp, stamp,
                canonical({"completed": 0, "total": config["search_budget"], "message": "Queued for local execution"}).decode(),
                "{}", int(recorded), operation, None, token, None))
            c.execute("INSERT INTO attempts(campaign_id,generation,operation,token,status) VALUES(?,?,?,?,?)", (cid, 1, operation, token, "queued"))
            c.execute("INSERT INTO mutations VALUES(?,?,?,?,?)", (key, req, cid, "create", stamp))
            self._event(c, cid, 1, "created", {"config_sha": digest(config), "operation": operation})
            return cid, True

    def action(self, cid, action, expected_generation, key):
        req = digest({"campaign_id": cid, "action": action, "expected_generation": expected_generation})
        with self.transaction() as c:
            old = c.execute("SELECT * FROM mutations WHERE key=?", (key,)).fetchone()
            if old:
                if old["request_sha"] != req: raise Conflict("Idempotency key has different inputs")
                return False
            row = self._row(c, cid)
            if row["generation"] != expected_generation: raise Conflict("Campaign changed; refresh before acting")
            status, stage, gen, op = row["status"], row["stage"], row["generation"], row["operation"]
            if action == "pause":
                if status not in {"queued", "running"}: raise Conflict("Only an active campaign can pause")
                status = "pause_requested"
            elif action == "cancel":
                if status not in ACTIVE | {"paused", "interrupted"}: raise Conflict("No active compute to cancel")
                gen += 1
                status = "cancel_requested"
            elif action in {"resume", "train"}:
                allowed = {"paused", "interrupted", "failed", "canceled"} if action == "resume" else {"ready"}
                if status not in allowed: raise Conflict("Action not available in current campaign state")
                active = c.execute("SELECT id FROM campaigns WHERE id<>? AND status IN ('queued','running','pause_requested','cancel_requested')", (cid,)).fetchone()
                if active: raise Conflict("Another campaign owns the local worker")
                gen += 1
                status = "queued"
                if action == "train": stage, op = "training", "train"
            else: raise ValueError("Unknown action")
            token = uuid.uuid4().hex if action in {"resume", "train"} else row["worker_token"]
            c.execute("UPDATE campaigns SET status=?,stage=?,generation=?,operation=?,worker_token=?,updated_at=?,error=NULL WHERE id=?", (status, stage, gen, op, token, now(), cid))
            if action in {"resume", "train"}:
                c.execute("INSERT INTO attempts(campaign_id,generation,operation,token,status) VALUES(?,?,?,?,?)", (cid, gen, op, token, "queued"))
            c.execute("INSERT INTO mutations VALUES(?,?,?,?,?)", (key, req, cid, action, now()))
            self._event(c, cid, gen, action, {"status": status, "previous_generation": expected_generation})
            return True

    def launch_info(self, cid):
        with self.connect() as c:
            row = self._row(c, cid)
            return {k: row[k] for k in ("id", "generation", "worker_token", "operation", "pid", "status")}

    def claim(self, cid, gen, token, pid):
        with self.transaction() as c:
            row = self._guard(c, cid, gen)
            if row["worker_token"] != token or row["status"] not in {"queued", "pause_requested"}: raise FenceLost("Attempt already claimed or stale")
            c.execute("UPDATE campaigns SET status=CASE WHEN status='pause_requested' THEN status ELSE 'running' END,pid=?,updated_at=? WHERE id=?", (pid, now(), cid))
            c.execute("UPDATE attempts SET status='running',started_at=?,pid=? WHERE campaign_id=? AND generation=?", (now(), pid, cid, gen))
            self._event(c, cid, gen, "worker_started", {"operation": row["operation"]})

    def boundary(self, cid, gen):
        with self.connect() as c:
            row = self._guard(c, cid, gen)
            if row["status"] == "pause_requested": raise PauseRequested("Paused at a completed episode boundary")

    def canceled(self, cid, gen):
        with self.connect() as c:
            row = self._row(c, cid)
            return row["generation"] != gen or row["status"] in {"cancel_requested", "canceled", "interrupted"}

    def progress(self, cid, gen, stage, completed, total, message, patch=None):
        with self.transaction() as c:
            row = self._guard(c, cid, gen)
            payload = json.loads(row["payload"])
            payload.update(patch or {})
            progress = {"completed": completed, "total": total, "message": message}
            c.execute("UPDATE campaigns SET stage=?,progress=?,payload=?,updated_at=? WHERE id=?", (stage, canonical(progress).decode(), canonical(payload).decode(), now(), cid))
            self._event(c, cid, gen, "progress", {"stage": stage, **progress})

    def save_episode(self, cid, gen, identity, episode, summary):
        sha = self.artifact(episode)
        summary = {**summary, "artifact_sha": sha}
        with self.transaction() as c:
            self._guard(c, cid, gen)
            old = c.execute("SELECT id FROM episodes WHERE campaign_id=? AND identity_key=?", (cid, identity)).fetchone()
            if old: return old["id"]
            episode_id = summary.get("id", episode.get("id", episode.get("episode_id")))
            c.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?)", (episode_id, cid, identity, sha, canonical(summary).decode(), now()))
            return episode_id

    def existing_episode(self, cid, identity):
        with self.connect() as c:
            row = c.execute("SELECT artifact_sha FROM episodes WHERE campaign_id=? AND identity_key=?", (cid, identity)).fetchone()
            return self.read_artifact(row["artifact_sha"]) if row else None

    def episode(self, episode_id):
        with self.connect() as c:
            row = c.execute("SELECT artifact_sha FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if row is None: raise KeyError(episode_id)
            result = self.read_artifact(row["artifact_sha"])
            return {**result, "id": episode_id, "artifact_sha": row["artifact_sha"], "evidence_hash_scope": "Exact raw engine artifact; API id and artifact_sha are display metadata"}

    def finish(self, cid, gen, status, stage, patch=None, error=None):
        if status not in {"ready", "completed", "paused", "failed"}: raise ValueError("Unsupported completion")
        with self.transaction() as c:
            row = self._guard(c, cid, gen)
            payload = json.loads(row["payload"])
            payload.update(patch or {})
            c.execute("UPDATE campaigns SET status=?,stage=?,payload=?,error=?,pid=NULL,updated_at=? WHERE id=?", (status, stage, canonical(payload).decode(), error, now(), cid))
            c.execute("UPDATE attempts SET status=?,ended_at=?,reason=? WHERE campaign_id=? AND generation=?", (status, now(), error, cid, gen))
            self._event(c, cid, gen, "worker_finished", {"status": status, "stage": stage, "error": error})

    def terminated(self, cid, gen, reason="Local worker termination confirmed"):
        with self.transaction() as c:
            row = self._row(c, cid)
            if row["generation"] != gen or row["status"] != "cancel_requested": raise Conflict("Cancellation state changed")
            c.execute("UPDATE campaigns SET status='canceled',pid=NULL,updated_at=? WHERE id=?", (now(), cid))
            c.execute("UPDATE attempts SET status='interrupted',ended_at=?,reason=? WHERE campaign_id=? AND status IN ('queued','running')", (now(), reason, cid))
            c.execute("UPDATE provider_calls SET status='local_cancellation_remote_unconfirmed',ended_at=? WHERE campaign_id=? AND status='running'", (now(), cid))
            self._event(c, cid, gen, "termination_confirmed", {"reason": reason})

    def recover(self):
        orphaned = []
        with self.transaction() as c:
            for row in c.execute("SELECT * FROM campaigns WHERE status IN ('queued','running','pause_requested','cancel_requested')").fetchall():
                orphaned.append({k: row[k] for k in ("id", "pid", "worker_token", "generation")})
                c.execute("UPDATE campaigns SET status='interrupted',generation=generation+1,pid=NULL,updated_at=?,error=? WHERE id=?", (now(), "Control service restarted. Prior generation fenced; resume restarts the incomplete phase.", row["id"]))
                c.execute("UPDATE attempts SET status='interrupted',ended_at=?,reason=? WHERE campaign_id=? AND status IN ('queued','running')", (now(), "Control service restart", row["id"]))
                c.execute("UPDATE provider_calls SET status='interrupted_remote_unconfirmed',ended_at=? WHERE campaign_id=? AND status='running'", (now(), row["id"]))
                self._event(c, row["id"], row["generation"] + 1, "recovered", {"previous_generation": row["generation"], "partial_outcomes": "excluded"})
        return orphaned

    def provider_start(self, cid, gen, purpose, summary):
        ident = f"call-{uuid.uuid4().hex[:12]}"
        with self.transaction() as c:
            self._guard(c, cid, gen)
            c.execute("INSERT INTO provider_calls VALUES(?,?,?,?,?,?,?,?,?)", (ident, cid, gen, purpose, "running", now(), None, None, canonical(summary).decode()))
        return ident

    def provider_finish(self, ident, status, receipt):
        sha = self.artifact(receipt)
        summary = {k: receipt.get(k) for k in ("provider", "model", "status", "request_hash", "request_id", "usage", "elapsed_seconds", "estimated_cost_usd", "error")}
        with self.transaction() as c:
            c.execute("UPDATE provider_calls SET status=?,ended_at=?,receipt_sha=?,summary=? WHERE id=?", (status, now(), sha, canonical(summary).decode(), ident))
        return sha
