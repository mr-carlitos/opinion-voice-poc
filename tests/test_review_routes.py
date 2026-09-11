from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.export import OpinionSummary
from app.graph import Folder
from app.grounding import Corpus
from app.sessions import Session


@pytest.fixture
def review_client(monkeypatch):
    owner = {"id": "synthetic-owner", "displayName": "Synthetic"}
    session = Session(
        owner,
        "synthetic-conversation",
        Corpus("[]", {}, {}, {}),
        Folder(
            "synthetic-drive", "synthetic-folder", "https://demo.sharepoint.com/sites/Demo/Docs/Out"
        ),
    )
    session.set_draft(
        OpinionSummary(topic="Pilot", haltung="Noch unentschieden"), validation_passed=True
    )
    monkeypatch.setattr(main, "auth", SimpleNamespace(owner=owner))
    monkeypatch.setattr(main, "sessions", {session.session_id: session})
    monkeypatch.setattr(main, "foundry", Mock())
    with TestClient(main.app) as client:
        client.get("/")
        client.headers.update({"Origin": "http://testserver", "X-Local-Client": "1"})
        yield client, session, f"/api/sessions/{session.session_id}"


def test_draft_api_recovery_requires_versions_and_rejects_stale_edits(review_client):
    client, session, base = review_client
    initial = client.get(base + "/draft")
    assert initial.status_code == 200
    assert initial.json()["version"] == 1
    assert initial.json()["summary"]["haltung"] == "Noch unentschieden"
    assert client.post(base + "/editing", json={}).status_code == 422
    assert client.post(base + "/editing", json={"version": 1}).status_code == 200
    assert client.get(base + "/draft").json()["editing"] is True
    summary = {"topic": "Pilot", "haltung": "Ich bevorzuge den Pilot"}
    assert client.post(base + "/draft", json={"summary": summary}).status_code == 422
    updated = client.post(base + "/draft", json={"summary": summary, "version": 1})
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["editing"] is False
    assert client.post(base + "/draft", json={"summary": summary, "version": 1}).status_code != 200
    assert client.post(base + "/editing", json={"version": 1}).status_code != 200
    assert session.draft_version == 2


def test_http_draft_edit_cannot_introduce_unretrieved_sources(review_client):
    client, _, base = review_client
    result = client.post(
        base + "/draft",
        json={
            "version": 1,
            "summary": {
                "topic": "Pilot",
                "haltung": "Unentschieden",
                "sources": [{"document_id": "invented", "page": 1}],
            },
        },
    )
    assert result.status_code != 200
    assert client.get(base + "/draft").json()["version"] == 1


def test_failed_semantic_validation_does_not_apply_or_approve_edit(review_client):
    client, _, base = review_client
    from app.graph import ServiceError

    main.foundry.validate_summary.side_effect = ServiceError("Synthetic validation failure")
    client.post(base + "/editing", json={"version": 1})
    result = client.post(
        base + "/draft",
        json={
            "version": 1,
            "summary": {"topic": "Pilot", "haltung": "Falscher Fakt"},
        },
    )
    assert result.status_code == 502
    state = client.get(base + "/draft").json()
    assert state["version"] == 1 and state["editing"] is True
    assert client.post(base + "/save", json={"version": 1}).status_code != 200


def test_http_save_reuses_frozen_result_and_recovery_snapshot(review_client, monkeypatch):
    client, session, base = review_client
    uploads = []

    class Connection:
        def __init__(self, auth):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def upload(self, folder, filename, content):
            uploads.append(content)
            return {"id": "owned-item", "webUrl": "https://demo.sharepoint.com/owned.docx"}

    monkeypatch.setattr(main, "Graph", Connection)
    saved = client.post(base + "/save", json={"version": 1})
    assert saved.status_code == 200
    assert client.post(base + "/save", json={"version": 1}).json() == saved.json()
    assert len(uploads) == 1
    recovered = client.get(base + "/draft").json()
    assert recovered["phase"] == "saved"
    assert recovered["frozen"] is True
    assert recovered["result"]["item_id"] == "owned-item"
    assert client.post(base + "/editing", json={"version": 1}).status_code != 200
    assert session.document == uploads[0]


def test_voice_reservation_rejects_concurrent_connections_and_reconnects(
    review_client, monkeypatch
):
    client, session, base = review_client
    monkeypatch.setattr(main, "voice_sessions", set())

    async def bridge(socket, *args):
        await socket.send_json({"type": "connected"})
        await socket.receive_json()
        await socket.send_json({"type": "stopped"})

    monkeypatch.setattr(main, "bridge", bridge)
    with client.websocket_connect(base + "/voice", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "connected"
        assert session.voice_connected is True
        with pytest.raises(WebSocketDisconnect) as concurrent:
            with client.websocket_connect(base + "/voice", headers={"origin": "http://testserver"}):
                pytest.fail("A concurrent voice connection must not be accepted.")
        assert concurrent.value.code == 1008
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["type"] == "stopped"
    assert session.voice_connected is False
    with pytest.raises(WebSocketDisconnect) as reconnect:
        with client.websocket_connect(base + "/voice", headers={"origin": "http://testserver"}):
            pytest.fail("Reconnect would replay the greeting and create duplicate context.")
    assert reconnect.value.code == 1008
