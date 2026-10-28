"""Browser boundaries stay independent of compute and provider availability."""
from fastapi.testclient import TestClient

from control import main
from control.store import Store


def test_read_only_gets_and_rejected_mutations_never_launch(tmp_path, monkeypatch):
    local = Store(tmp_path)
    monkeypatch.setattr(main, "store", local)
    monkeypatch.setattr(main.providers, "status", lambda: [])
    launched = []
    monkeypatch.setattr(main.supervisor, "start", lambda cid: launched.append(cid))
    # No lifespan context: this in-process client must not recover or stop the
    # application's independently running production worker.
    client = TestClient(main.app)
    for path in ("/api/health", "/api/bootstrap", "/api/campaigns"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert local.list_campaigns() == [] and launched == []

    rejected = client.post("/api/campaigns", json={}, headers={"Origin": "https://unrelated.example", "Idempotency-Key": "not-allowed-origin"})
    assert rejected.status_code == 403
    rejected = client.post("/api/campaigns", content="{}", headers={"Origin": "http://127.0.0.1:4401", "Content-Type": "text/plain", "Idempotency-Key": "wrong-content-type"})
    assert rejected.status_code == 415
    assert client.post("/api/campaigns", json={}).status_code == 400
    assert client.post("/api/campaigns", json={"unknown": True}, headers={"Idempotency-Key": "unknown-input-field"}).status_code == 422
    assert local.list_campaigns() == [] and launched == []
