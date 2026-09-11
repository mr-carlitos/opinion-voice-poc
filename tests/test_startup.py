from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.graph import Folder, ServiceError
from app.grounding import Corpus
from app.main import app


@pytest.fixture(autouse=True)
def no_cloud_connections(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            tenant_id="",
            graph_client_id="",
            project_endpoint="",
            voice_endpoint="",
            input_url="",
            output_url="",
            input_drive_id="",
            input_folder_id="",
            output_drive_id="",
            output_folder_id="",
            graph_auth_mode="delegated",
            graph_application_credentials_file="",
        ),
    )
    monkeypatch.setattr(main, "auth", None)
    monkeypatch.setattr(main, "foundry", None)


def test_app_lives_but_cloud_workflows_fail_closed():
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        readiness = client.get("/api/readiness")
        assert readiness.status_code == 503
        assert readiness.json()["ready"] is False
        assert client.post("/api/sessions", json={}).status_code == 403
        client.get("/")
        headers = {"Origin": "http://testserver", "X-Local-Client": "1"}
        assert client.post("/api/sessions", headers=headers, json={}).status_code == 503
        assert client.post("/api/exports", headers=headers, json={}).status_code == 409
        assert client.get("/.env").status_code == 404
        assert client.get("/.env.agenticrulingradar").status_code == 404


def test_untrusted_hosts_are_rejected():
    with TestClient(app, base_url="http://untrusted.example") as client:
        assert client.get("/healthz").status_code == 400


@pytest.mark.parametrize("fail_corpus", [False, True])
def test_session_startup_closes_graph_scope_and_reports_stage_timings(monkeypatch, fail_corpus):
    source = Folder("drive", "input", "https://demo.sharepoint.com/sites/Demo/Documents/Input")
    output = Folder("drive", "output", "https://demo.sharepoint.com/sites/Demo/Documents/Output")
    mock_settings = SimpleNamespace(
        issues=lambda: [],
        input_url=source.url,
        input_drive_id="drive",
        input_folder_id="input",
        output_url=output.url,
        output_drive_id="drive",
        output_folder_id="output",
    )
    owner = {"id": "synthetic", "displayName": "Synthetic"}
    seen = []

    class Connection:
        def __init__(self, auth):
            assert auth.owner == owner

        def __enter__(self):
            seen.append("open")
            return self

        def __exit__(self, *args):
            seen.append("closed")

        def resolve_folder(self, url, **kwargs):
            assert seen[-1] == "open"
            return source if url == source.url else output

    def load(graph, folder):
        assert seen == ["open"]
        assert folder is source
        if fail_corpus:
            raise ServiceError("synthetic source failure")
        return Corpus("[]", {}, {}, {})

    foundry = Mock()
    foundry.create_conversation.return_value = "conversation"
    monkeypatch.setattr(main, "settings", mock_settings)
    monkeypatch.setattr(main, "auth", SimpleNamespace(owner=owner))
    monkeypatch.setattr(main, "Graph", Connection)
    monkeypatch.setattr(main, "load_corpus", load)
    monkeypatch.setattr(main, "foundry", foundry)
    monkeypatch.setattr(main, "sessions", {})
    if fail_corpus:
        with pytest.raises(ServiceError, match="synthetic source failure"):
            main.create_session()
        foundry.configure_agent.assert_not_called()
        assert main.sessions == {}
    else:
        result = main.create_session()
        assert set(result["startup_seconds"]) == {
            "folders",
            "corpus",
            "agent",
            "conversation",
            "total",
        }
        assert all(value >= 0 for value in result["startup_seconds"].values())
        assert result["session_id"] in main.sessions
        foundry.create_conversation.assert_called_once()
    assert seen == ["open", "closed"]
