"""Loopback-only control API. GET requests never start compute."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import json
import re
from typing import Literal
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse, Response, FileResponse
from pydantic import BaseModel, ConfigDict, Field
from engine.spec import task_spec, runtime_lock, FACTOR_SPEC
from .store import Store, Conflict, FenceLost, ROOT, digest
from .supervisor import Supervisor
from .lineage import source_lock
from .protocol import PROTOCOL, PROTOCOL_SHA, development_manifest
from . import providers

store = Store()
supervisor = Supervisor(store)

@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(supervisor.recover)
    async def monitor():
        while True:
            supervisor.reap()
            await asyncio.sleep(1)
    task = asyncio.create_task(monitor())
    yield
    task.cancel()
    await asyncio.to_thread(supervisor.shutdown)

app = FastAPI(title="FORGE local simulation control", version="1.0.0", lifespan=lifespan)

@app.middleware("http")
async def local_boundary(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin not in {"http://127.0.0.1:4401", "http://localhost:4401", "http://127.0.0.1:4402", "http://localhost:4402"}:
            return JSONResponse({"detail": "Mutation origin is not the local FORGE interface"}, status_code=403)
        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            return JSONResponse({"detail": "JSON mutation body required"}, status_code=415)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.exception_handler(Conflict)
async def conflict(request, exc): return JSONResponse({"detail": str(exc)}, status_code=409)

@app.exception_handler(KeyError)
async def absent(request, exc): return JSONResponse({"detail": "Evidence record not found"}, status_code=404)

@app.exception_handler(ValueError)
async def invalid(request, exc): return JSONResponse({"detail": str(exc)}, status_code=422)

class CreateCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(default="Boundary investigation", min_length=1, max_length=80)
    seed: int = Field(default=427, ge=0, le=1000000000)
    search_budget: Literal[12,24,36] = 24
    development_parent_id: str | None = None

class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_generation: int = Field(ge=1)

class Challenge(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    campaign_id: str
    seed: int = Field(ge=0,le=2**32-1)
    parameters: dict[str,float]

def require_key(value):
    if not value or not re.fullmatch(r"[a-zA-Z0-9:_-]{8,100}", value): raise HTTPException(400, "A unique Idempotency-Key header (8–100 characters) is required")
    return value

def base_index():
    path = store.path / "base" / "index.json"
    return json.loads(path.read_text()) if path.exists() else None

def enrich(campaign):
    recorded_lock = campaign.get("config", {}).get("source_sha")
    campaign["freshness"] = {"source_matches": recorded_lock == source_lock()["sha256"], "message": "Recorded evidence retains its original source lock; changes require a new campaign."}
    return campaign

@app.get("/api/health")
def health(): return {"status": "ok", "simulation_only": True, "base_ready": base_index() is not None}

@app.get("/api/bootstrap")
def bootstrap():
    campaigns = store.list_campaigns()
    keys = ("id","name","status","stage","generation","created_at","updated_at","progress","recorded","config","error")
    summaries = [{k: c.get(k) for k in keys} for c in campaigns]
    base = base_index()
    from .intervention_planner import provider_status
    routes = [p for p in providers.status() if p["purpose"] != "submission"] + provider_status(store)
    return {"task": task_spec(), "runtime": runtime_lock(), "protocol": PROTOCOL, "protocol_sha": PROTOCOL_SHA, "campaigns": summaries, "selected_campaign_id": summaries[0]["id"] if summaries else None, "providers": routes, "policies": [{"id":"base", "label":"Base waypoint MLP", "checkpoint_sha":base["checkpoint_sha"]}] if base else [], "base_ready":bool(base)}

@app.get("/api/campaigns")
def campaigns(): return [enrich(c) for c in store.list_campaigns()]

@app.get("/api/campaigns/{cid}")
def campaign(cid: str): return enrich(store.get(cid))

@app.post("/api/campaigns", status_code=201)
def create(body: CreateCampaign, idempotency_key: str | None = Header(default=None)):
    key = require_key(idempotency_key)
    base = base_index()
    if base is None: raise HTTPException(503, "Base checkpoint has not been prepared. Run scripts/bootstrap.py locally first.")
    if body.development_parent_id:
        prior=store.get(body.development_parent_id,detail=False)
        if prior["status"]!="completed" or not prior.get("report"):raise Conflict("Development parent must have a completed exploratory report")
    config = {**body.model_dump(exclude={"name"}), "task_sha":task_spec()["task_spec_hash"], "protocol_sha":PROTOCOL_SHA, "source_sha":source_lock()["sha256"], "base_checkpoint_sha":base["checkpoint_sha"], "live_models":True}
    config["source_lock_sha"]=store.artifact(source_lock())
    config["task_artifact_sha"]=store.artifact(task_spec())
    config["runtime_artifact_sha"]=store.artifact(runtime_lock())
    config["protocol_artifact_sha"]=store.artifact(PROTOCOL)
    config["base_index_sha"]=store.artifact(base)
    manifest = development_manifest(FACTOR_SPEC, body.seed)
    config["development_manifest_sha"] = store.artifact(manifest)
    cid, new = store.create(body.name, config, key)
    if new: supervisor.start(cid)
    return enrich(store.get(cid))

@app.post("/api/campaigns/{cid}/{action}")
async def action(cid: str, action: Literal["train","pause","cancel","resume"], body: Action, idempotency_key: str | None = Header(default=None)):
    key = require_key(idempotency_key)
    if action in {"train","resume"}:
        c = enrich(store.get(cid, detail=False))
        if not c["freshness"]["source_matches"]: raise Conflict("Simulation source changed since this campaign was frozen. Create a new campaign; the original evidence remains inspectable.")
    changed = store.action(cid, action, body.expected_generation, key)
    if changed:
        if action in {"train","resume"}: supervisor.start(cid)
        elif action == "cancel": await asyncio.to_thread(supervisor.cancel, cid)
    return enrich(store.get(cid))

@app.post("/api/challenges",status_code=201)
def create_challenge(body: Challenge,idempotency_key: str | None = Header(default=None)):
    from engine import normalize_scenario
    key=require_key(idempotency_key)
    parent=enrich(store.get(body.campaign_id,detail=False))
    nomination=parent.get("report",{}).get("nominations",{}).get("minimized")
    if nomination is None:raise Conflict("A frozen nominated policy is required before a challenge")
    if not parent["freshness"]["source_matches"]:raise Conflict("Source changed since nomination; use a current campaign")
    if set(body.parameters)!=set(FACTOR_SPEC):raise ValueError("All four registered parameters are required")
    scene=normalize_scenario({"split":"challenge","family":"judge_selected","seed":body.seed,"parameters":body.parameters})
    config={"kind":"challenge","parent_campaign_id":body.campaign_id,"seed":body.seed,"search_budget":2,"task_sha":task_spec()["task_spec_hash"],"protocol_sha":PROTOCOL_SHA,"source_sha":source_lock()["sha256"],"base_checkpoint_sha":parent["config"]["base_checkpoint_sha"],"revised_checkpoint_sha":nomination["checkpoint_sha"],"challenge_scenario":scene,"live_models":False}
    cid,new=store.create("Paired condition challenge",config,key)
    if new:supervisor.start(cid)
    return enrich(store.get(cid))

@app.get("/api/episodes/{episode_id}")
def episode(episode_id: str): return store.episode(episode_id)

@app.get("/api/artifacts/{sha}")
def artifact(sha: str):
    try: return store.read_artifact(sha)
    except FileNotFoundError: raise HTTPException(404,"Artifact not found")

@app.get("/api/campaigns/{cid}/export")
def export(cid: str):
    archived=store.get(cid,detail=False).get("frozen_export")
    if archived:
        import hashlib
        if not re.fullmatch(r"[a-zA-Z0-9_-]+\.zip",archived["filename"]):raise ValueError("Invalid archive name")
        path=store.path/"archives"/archived["filename"]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=archived["sha256"]:raise ValueError("Historical export integrity mismatch")
        return FileResponse(path,media_type="application/zip",filename=f"forge-{cid}-frozen.zip")
    from .export import export_campaign
    return Response(export_campaign(store,cid), media_type="application/zip", headers={"Content-Disposition":f'attachment; filename="forge-{cid}.zip"'})

@app.get("/api/campaigns/{cid}/images/{name}")
def image(cid: str,name: Literal["source.png","minimized.png"]):
    store.get(cid,detail=False)
    path=store.path/"renders"/cid/name
    if not path.is_file():raise HTTPException(404,"Rendered frame not available")
    return FileResponse(path,media_type="image/png")

# Additive diagnostics never modify the historical scientific evidence tables.
from .incident_api import routes as incident_routes
app.include_router(incident_routes(lambda: store, require_key))

@app.get("/api/intervention-plans")
def intervention_plans():
    from .intervention_planner import list_plans
    return list_plans(store)

@app.get("/api/integrations/groot")
def groot_qualification_contract():
    from integrations.groot.contract import digest, load_contract
    contract = load_contract()
    return {"contract": contract, "contract_sha256": digest(contract), "qualified": False}
