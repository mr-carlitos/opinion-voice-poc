import asyncio
from types import SimpleNamespace

import pytest

from app import voice
from app.config import Settings
from app.grounding import Corpus
from test_voice import Transport, until


def test_delivery_mode_defaults_to_strict_and_rejects_unknown_mode():
    settings = Settings("", "", "", "", "", "", "", "", "", "")
    assert settings.voice_delivery_mode == "strict"
    from dataclasses import replace

    assert any(
        "VOICE_DELIVERY_MODE" in issue
        for issue in replace(settings, voice_delivery_mode="fastest").issues()
    )


@pytest.mark.parametrize("mode", ["strict", "streaming"])
def test_only_explicit_streaming_releases_audio_before_response_done(monkeypatch, mode):
    async def scenario():
        upstream, browser = Transport(), Transport()
        monkeypatch.setattr(voice, "connect", lambda **kwargs: upstream)
        monkeypatch.setattr(voice, "AzureCliCredential", lambda **kwargs: Transport())
        checks = []

        def verify(*args):
            checks.append(True)
            return SimpleNamespace(supported=True, sources=[])

        settings = SimpleNamespace(
            voice_delivery_mode=mode,
            tenant_id="tenant",
            voice_endpoint="endpoint",
            voice_api_version="version",
            agent_name="agent",
            project_endpoint="endpoint/project",
            voice_name="voice",
        )
        session = SimpleNamespace(
            conversation_id="same",
            corpus=Corpus("[]", {}, {}, {}),
            user_turns=[],
            phase="conversation",
        )
        task = asyncio.create_task(
            voice.bridge(
                browser, session, settings, SimpleNamespace(version="2", verify_answer=verify), None
            )
        )
        try:
            await upstream.incoming.put({"type": "session.updated"})
            await until(lambda: any(x["type"] == "response.create" for x in upstream.sent))
            await upstream.incoming.put({"type": "response.created"})
            await upstream.incoming.put(
                {
                    "type": "response.audio.delta",
                    "item_id": "answer",
                    "delta": "AAA=",
                }
            )
            await upstream.incoming.put(
                {
                    "type": "response.audio_transcript.delta",
                    "item_id": "answer",
                    "delta": "Hallo.",
                }
            )
            if mode == "streaming":
                await until(lambda: any(x["type"] == "audio" for x in browser.sent))
                assert any(x["type"] == "assistant_delta" for x in browser.sent)
            else:
                await asyncio.sleep(0.03)
                assert not any(x["type"] == "audio" for x in browser.sent)
            assert checks == []
            await upstream.incoming.put(
                {
                    "type": "response.done",
                    "response": {
                        "status": "completed",
                        "output": [{"id": "answer", "type": "message"}],
                    },
                }
            )
            await until(lambda: any(x["type"] == "assistant" for x in browser.sent))
            if mode == "streaming":
                await until(lambda: any(x["type"] == "assistant_sources" for x in browser.sent))
            assert len(checks) == 1
            assert sum(x["type"] == "audio" for x in browser.sent) == 1
            completed = next(x for x in browser.sent if x["type"] == "assistant")
            assert completed["evidence_status"] == (
                "verified" if mode == "strict" else "not_independently_verified"
            )
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
