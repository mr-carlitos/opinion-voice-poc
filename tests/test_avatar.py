import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from test_voice import Transport, until

from app import diagnostics, voice
from app.avatar import checked_ice, checked_sdp
from app.config import Settings
from app.graph import ServiceError
from app.grounding import Corpus


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "LOG_PATH", tmp_path / "diagnostics.jsonl")


def sdp(kind="offer"):
    return base64.b64encode(
        json.dumps(
            {
                "type": kind,
                "sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
                "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            }
        ).encode()
    ).decode()


@pytest.mark.parametrize(
    "value", [None, {}, "!", "A" * 131073, base64.b64encode(b"{}").decode(), sdp("answer")]
)
def test_invalid_offer_rejected(value):
    with pytest.raises(ServiceError):
        checked_sdp(value, "offer")


def test_only_bounded_signaling_fields_and_safe_default():
    assert checked_sdp(sdp(), "offer") == sdp()
    assert checked_ice([{"urls": ["turn:relay.example:3478"], "secret": "not-forwarded"}]) == [
        {"urls": ["turn:relay.example:3478"], "username": "", "credential": ""}
    ]
    settings = Settings("", "", "", "", "", "", "", "", "", "")
    assert settings.avatar_enabled is False
    assert "avatar" not in voice.voice_session_settings(settings)
    assert voice.voice_session_settings(settings, True)["avatar"]["character"] == "lisa"


@pytest.mark.parametrize(
    "value",
    [
        [],
        [{}],
        [{"urls": ["https://bad.example"]}],
        [{"urls": ["turn:host"], "credential": "x" * 4097}],
    ],
)
def test_invalid_ice_rejected(value):
    with pytest.raises(ServiceError):
        checked_ice(value)


def fixtures(monkeypatch, mode="streaming", enabled=True):
    upstream, browser = Transport(), Transport()
    monkeypatch.setattr(voice, "connect", lambda **kwargs: upstream)
    monkeypatch.setattr(voice, "AzureCliCredential", lambda **kwargs: Transport())
    settings = SimpleNamespace(
        voice_delivery_mode=mode,
        avatar_enabled=enabled,
        tenant_id="tenant",
        voice_endpoint="endpoint",
        voice_api_version="version",
        agent_name="agent",
        project_endpoint="endpoint/project",
        voice_name="voice",
    )
    session = SimpleNamespace(
        conversation_id="same",
        avatar_enabled=True,
        corpus=Corpus("[]", {}, {}, {}),
        user_turns=[],
        phase="conversation",
    )
    return upstream, browser, session, settings


@pytest.mark.parametrize("mode,enabled", [("strict", True), ("streaming", False)])
def test_avatar_requires_both_capability_and_streaming(monkeypatch, mode, enabled):
    async def scenario():
        _, browser, session, settings = fixtures(monkeypatch, mode, enabled)
        with pytest.raises(ServiceError):
            await voice.bridge(browser, session, settings, SimpleNamespace(version="2"), None)

    asyncio.run(scenario())


def test_negotiates_before_greeting_single_audio_path_interrupt_and_stop(monkeypatch):
    async def scenario():
        upstream, browser, session, settings = fixtures(monkeypatch)
        task = asyncio.create_task(
            voice.bridge(browser, session, settings, SimpleNamespace(version="2"), None)
        )
        try:
            await upstream.incoming.put(
                {
                    "type": "session.updated",
                    "session": {"avatar": {"ice_servers": [{"urls": ["turn:relay.example:3478"]}]}},
                }
            )
            await until(lambda: any(x["type"] == "avatar_start" for x in browser.sent))
            assert not any(x["type"] == "response.create" for x in upstream.sent)
            await browser.incoming.put({"type": "avatar_ready"})
            await until(lambda: any(x["type"] == "error" for x in browser.sent))
            assert not any(x["type"] == "response.create" for x in upstream.sent)
            await browser.incoming.put(
                {"type": "avatar_offer", "client_sdp": sdp(), "secret": "drop"}
            )
            await until(lambda: any(x["type"] == "session.avatar.connect" for x in upstream.sent))
            assert set(upstream.sent[-1]) == {"type", "client_sdp"}
            await upstream.incoming.put(
                {"type": "session.avatar.connecting", "server_sdp": sdp("answer")}
            )
            await until(lambda: any(x["type"] == "avatar_answer" for x in browser.sent))
            assert not any(x["type"] == "response.create" for x in upstream.sent)
            await browser.incoming.put({"type": "avatar_ready"})
            await until(lambda: any(x["type"] == "response.create" for x in upstream.sent))
            await upstream.incoming.put({"type": "response.created"})
            await upstream.incoming.put(
                {"type": "response.audio.delta", "item_id": "a", "delta": "AAA="}
            )
            await upstream.incoming.put(
                {"type": "response.audio_transcript.delta", "item_id": "a", "delta": "Hallo"}
            )
            await until(lambda: any(x["type"] == "assistant_delta" for x in browser.sent))
            assert not any(x["type"] == "audio" for x in browser.sent)
            await browser.incoming.put({"type": "interrupt"})
            await until(
                lambda: any(x["type"] == "output_audio_buffer.clear" for x in upstream.sent)
            )
            assert any(x["type"] == "response.cancel" for x in upstream.sent)
            await browser.incoming.put({"type": "stop"})
            await asyncio.wait_for(task, 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["missing_ice", "service_error", "browser_failed"])
def test_handshake_failure_is_explicit_and_terminates(monkeypatch, failure):
    async def scenario():
        upstream, browser, session, settings = fixtures(monkeypatch)
        task = asyncio.create_task(
            voice.bridge(browser, session, settings, SimpleNamespace(version="2"), None)
        )
        if failure == "missing_ice":
            await upstream.incoming.put({"type": "session.updated"})
        elif failure == "service_error":
            await upstream.incoming.put({"type": "error", "error": {"code": "unsupported"}})
        else:
            await browser.incoming.put({"type": "avatar_failed"})
        with pytest.raises(ServiceError):
            await asyncio.wait_for(task, 1)
        assert any(x["type"] == "avatar_failed" for x in browser.sent)
        assert not any(x["type"] == "response.create" for x in upstream.sent)

    asyncio.run(scenario())


def test_server_handshake_timeout_closes_idle_negotiation(monkeypatch):
    async def scenario():
        upstream, browser, session, settings = fixtures(monkeypatch)
        monkeypatch.setattr(voice, "AVATAR_HANDSHAKE_TIMEOUT", 0.01)
        with pytest.raises(ServiceError):
            await asyncio.wait_for(
                voice.bridge(browser, session, settings, SimpleNamespace(version="2"), None), 1
            )
        assert any(x.get("reason") == "handshake_timeout" for x in browser.sent)
        assert not any(x["type"] == "response.create" for x in upstream.sent)

    asyncio.run(scenario())


def test_browser_failure_retains_specific_reason_states_and_shared_diagnostic_id(monkeypatch):
    async def scenario():
        _, browser, session, settings = fixtures(monkeypatch)
        await browser.incoming.put(
            {
                "type": "avatar_failed",
                "reason": "remote_description_failed",
                "diagnostics": {
                    "stage": "set_remote_description",
                    "error_name": "OperationError",
                    "error_message": "Failed video negotiation",
                    "ice_connection_state": "failed",
                    "ice_errors": [{"code": 701, "text": "Unreachable"}],
                    "server_sdp": "MUST_NOT_LOG",
                },
            }
        )
        with pytest.raises(ServiceError) as caught:
            await voice.bridge(browser, session, settings, SimpleNamespace(version="2"), None)
        event = next(x for x in browser.sent if x["type"] == "avatar_failed")
        saved = json.loads(diagnostics.LOG_PATH.read_text())
        assert saved["diagnostic_id"] == event["diagnostic_id"] == caught.value.diagnostic_id
        assert saved["reason"] == "remote_description_failed"
        assert saved["browser"]["ice_errors"][0]["code"] == 701
        assert "MUST_NOT_LOG" not in diagnostics.LOG_PATH.read_text()

    asyncio.run(scenario())


def test_service_failure_keeps_service_message_and_correlation(monkeypatch):
    async def scenario():
        upstream, browser, session, settings = fixtures(monkeypatch)
        await upstream.incoming.put({"type": "session.created", "session": {"id": "sess_demo"}})
        await upstream.incoming.put(
            {
                "type": "error",
                "event_id": "evt_demo",
                "error": {
                    "code": "avatar_service_internal_error",
                    "message": "Failed to set remote video description send parameters",
                },
            }
        )
        with pytest.raises(ServiceError):
            await voice.bridge(browser, session, settings, SimpleNamespace(version="2"), None)
        saved = json.loads(diagnostics.LOG_PATH.read_text())
        assert saved["service"]["message"].startswith("Failed to set remote video")
        assert saved["service_session_id"] == "sess_demo"
        assert saved["service_event_id"] == "evt_demo"

    asyncio.run(scenario())


@pytest.mark.parametrize("mode,enabled", [("strict", True), ("streaming", False)])
def test_http_rejects_avatar_before_any_cloud_work(monkeypatch, mode, enabled):
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            issues=lambda: [],
            avatar_enabled=enabled,
            voice_delivery_mode=mode,
        ),
    )
    monkeypatch.setattr(main, "auth", SimpleNamespace(owner={"id": "synthetic"}))
    monkeypatch.setattr(main, "foundry", object())
    monkeypatch.setattr(main, "sessions", {})
    with TestClient(main.app) as client:
        client.get("/")
        client.headers.update({"Origin": "http://testserver", "X-Local-Client": "1"})
        assert client.post("/api/sessions", json={"avatar_enabled": True}).status_code == 400
        assert client.post("/api/sessions", json={"arbitrary_event": True}).status_code == 422
