"""Same-origin, idempotent incident routes; GETs inspect or export only."""
from typing import Literal
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from .incident import Incidents

class IncidentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    campaign_id: str = Field(min_length=1, max_length=80)
    source_episode_id: str = Field(min_length=1, max_length=100)
    factor: Literal["obstacle_height", "friction", "payload_yaw", "tray_offset_y"]
    value: float = Field(allow_inf_nan=False)
    nuisance_repeats: int = Field(default=1, ge=1, le=20)
    planner_receipt_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

def routes(store_getter, require_key):
    router = APIRouter()
    def manager():
        return Incidents(store_getter())
    @router.get("/api/incidents/context")
    def context(campaign_id: str):
        return manager().context(campaign_id)
    @router.get("/api/incidents")
    def listing():
        return manager().list()
    @router.post("/api/incidents", status_code=201)
    def create(body: IncidentRequest, idempotency_key: str | None = Header(default=None)):
        key = require_key(idempotency_key)
        current = manager()
        job, created = current.create(body.model_dump(), key)
        if created:
            current.launch(job["id"])
        return current.get(job["id"])
    @router.get("/api/incidents/{iid}")
    def detail(iid: str):
        return manager().get(iid)
    @router.post("/api/incidents/{iid}/cancel")
    def cancel(iid: str, body: EmptyBody, idempotency_key: str | None = Header(default=None)):
        return manager().cancel(iid, require_key(idempotency_key))
    @router.get("/api/incidents/{iid}/episodes/{trial}/{branch}")
    def episode(iid: str, trial: int, branch: Literal["original", "intervention"]):
        return manager().episode(iid, trial, branch)
    @router.get("/api/incidents/{iid}/export")
    def export(iid: str):
        return Response(manager().export(iid), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="forge-{iid}-incident.zip"'})
    return router
