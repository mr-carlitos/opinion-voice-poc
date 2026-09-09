from fastapi.testclient import TestClient

from app.main import app


def test_app_lives_but_cloud_workflows_fail_closed():
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        readiness = client.get("/api/readiness")
        assert readiness.status_code == 503
        assert readiness.json()["ready"] is False
        assert client.post("/api/sessions", json={}).status_code == 503
        assert client.post("/api/exports", json={}).status_code == 503
        assert client.get("/.env").status_code == 404


def test_untrusted_hosts_are_rejected():
    with TestClient(app, base_url="http://untrusted.example") as client:
        assert client.get("/healthz").status_code == 400
