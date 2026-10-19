from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.export import OpinionSummary
from app.graph import Folder, ServiceError
from app.grounding import Corpus
from app.sessions import Session


@pytest.fixture
def local_api(monkeypatch):
    owner = {"id": "synthetic-owner", "displayName": "Synthetic"}
    session = Session(
        owner,
        "owned-conversation",
        Corpus("[]", {}, {}, {}),
        Folder("drive", "output", "https://demo.sharepoint.com/sites/Demo/Docs/Output"),
    )
    monkeypatch.setattr(main, "sessions", {session.session_id: session})
    monkeypatch.setattr(main, "voice_sessions", set())
    monkeypatch.setattr(main, "auth", SimpleNamespace(owner=owner, start=Mock()))
    monkeypatch.setattr(main, "foundry", Mock())
    with TestClient(main.app, raise_server_exceptions=False) as client:
        client.get("/")
        client.headers.update({"Origin": "http://testserver", "X-Local-Client": "1"})
        yield client, session, f"/api/sessions/{session.session_id}"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "missing", ["cookie", "client", "origin", "foreign-origin", "https-origin"]
)
def test_every_mutation_requires_local_cookie_client_marker_and_exact_origin(
    local_api, method, missing
):
    client, _, _ = local_api
    if missing == "cookie":
        client.cookies.clear()
    elif missing == "client":
        del client.headers["X-Local-Client"]
    elif missing == "origin":
        del client.headers["Origin"]
    else:
        client.headers["Origin"] = (
            "http://foreign.example" if missing == "foreign-origin" else "https://testserver"
        )
    response = client.request(method, "/api/auth/start")
    assert response.status_code == 403
    main.auth.start.assert_not_called()


def test_index_cookie_and_public_responses_have_local_privacy_headers(local_api):
    client, _, _ = local_api
    response = client.get("/")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert main.browser_key not in response.text
    for path in ("/", "/healthz", "/static/microphone.js", "/missing"):
        response = client.get(path)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("configured", [False, True])
def test_sign_in_requires_configuration_and_returns_only_auth_result(
    local_api, monkeypatch, configured
):
    client, _, _ = local_api
    if configured:
        main.auth.start.return_value = {"status": "starting"}
    else:
        monkeypatch.setattr(main, "auth", None)
    response = client.post("/api/auth/start")
    assert response.status_code == (200 if configured else 503)
    if configured:
        assert response.json() == {"status": "starting"}


@pytest.mark.parametrize(
    "failure", [ServiceError("Synthetic provider failure"), RuntimeError("private")]
)
def test_exception_responses_do_not_dump_unexpected_service_details(local_api, failure):
    client, _, _ = local_api
    main.auth.start.side_effect = failure
    response = client.post("/api/auth/start")
    assert response.status_code == 502
    if isinstance(failure, ServiceError):
        assert response.json() == {"message": "Synthetic provider failure"}
    else:
        assert "RuntimeError" in response.json()["message"]
        assert "private" not in response.text


@pytest.mark.parametrize("identity", ["missing-session", "different-owner", "signed-out"])
def test_session_routes_do_not_expose_other_owners_state(local_api, identity):
    client, _, base = local_api
    if identity == "missing-session":
        base = "/api/sessions/does-not-exist"
    else:
        main.auth.owner = None if identity == "signed-out" else {"id": "other"}
    assert client.get(base + "/draft").status_code == 404
    assert client.delete(base).status_code == 404
    main.foundry.delete_conversation.assert_not_called()


def test_session_deletion_requires_stopped_voice_and_preserves_saved_files(local_api):
    client, session, base = local_api
    session.voice_connected = True
    assert client.delete(base).status_code == 409
    main.foundry.delete_conversation.assert_not_called()
    session.voice_connected = False
    main.voice_sessions.add(session.session_id)
    response = client.delete(base)
    assert response.status_code == 200
    assert "SharePoint-Dateien bleiben" in response.json()["message"]
    assert session.session_id not in main.sessions
    assert session.session_id not in main.voice_sessions
    main.foundry.delete_conversation.assert_called_once_with(session.conversation_id)


def test_failed_conversation_deletion_retains_local_recovery_state(local_api):
    client, session, base = local_api
    main.foundry.delete_conversation.side_effect = ServiceError("Synthetic unavailable")
    assert client.delete(base).status_code == 502
    assert main.sessions[session.session_id] is session


def test_session_limit_rejects_start_before_contacting_services(local_api, monkeypatch):
    client, session, _ = local_api
    monkeypatch.setattr(main, "settings", SimpleNamespace(issues=lambda: []))
    monkeypatch.setattr(main, "sessions", {str(index): session for index in range(3)})
    graph = Mock()
    monkeypatch.setattr(main, "Graph", graph)
    assert client.post("/api/sessions", json={}).status_code == 409
    graph.assert_not_called()
    main.foundry.create_conversation.assert_not_called()


def test_edit_without_validator_does_not_replace_reviewed_draft(local_api, monkeypatch):
    client, session, base = local_api
    session.set_draft(OpinionSummary(topic="Pilot", haltung="Original"), validation_passed=True)
    monkeypatch.setattr(main, "foundry", None)
    response = client.post(
        base + "/draft",
        json={"version": 1, "summary": {"topic": "Pilot", "haltung": "New"}},
    )
    assert response.status_code == 503
    assert session.snapshot()["summary"]["haltung"] == "Original"


@pytest.mark.parametrize("invalid", ["cookie", "origin"])
def test_voice_guard_rejects_nonlocal_websocket_before_starting_bridge(local_api, invalid):
    client, session, base = local_api
    if invalid == "cookie":
        client.cookies.clear()
    headers = {"origin": "http://other.example" if invalid == "origin" else "http://testserver"}
    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect(base + "/voice", headers=headers):
            pytest.fail("A nonlocal connection must not be accepted.")
    assert rejected.value.code == 1008
    assert session.voice_connected is False
    assert main.voice_sessions == set()


@pytest.mark.parametrize("kind", ["failure", "disconnect"])
def test_voice_disconnect_releases_active_state_and_reports_safe_diagnostic(
    local_api, monkeypatch, kind
):
    client, session, base = local_api
    diagnostic = Mock(return_value="synthetic-diagnostic")
    monkeypatch.setattr(main, "record_diagnostic", diagnostic)

    async def bridge(socket, *args):
        if kind == "disconnect":
            raise WebSocketDisconnect()
        raise RuntimeError("private provider payload")

    monkeypatch.setattr(main, "bridge", bridge)
    with client.websocket_connect(base + "/voice", headers={"origin": "http://testserver"}) as ws:
        if kind == "failure":
            message = ws.receive_json()
            assert message["diagnostic_id"] == "synthetic-diagnostic"
            assert "private" not in message["message"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert session.voice_connected is False
    assert session.session_id in main.voice_sessions
    assert diagnostic.call_count == (1 if kind == "failure" else 0)
