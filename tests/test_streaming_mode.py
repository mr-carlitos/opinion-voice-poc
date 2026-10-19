import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice import Transport, until

from app import voice
from app.config import Settings
from app.export import OpinionSummary
from app.graph import Folder, ServiceError
from app.grounding import Corpus
from app.sessions import Session


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


@asynccontextmanager
async def running_voice(monkeypatch, mode="strict"):
    upstream, browser = Transport(), Transport()
    monkeypatch.setattr(voice, "connect", lambda **kwargs: upstream)
    monkeypatch.setattr(voice, "AzureCliCredential", lambda **kwargs: Transport())
    settings = Settings("", "", "", "", "https://synthetic/project", "", "", "", "", "")
    from dataclasses import replace

    settings = replace(settings, voice_delivery_mode=mode)
    session = Session(
        {"id": "synthetic", "displayName": "Synthetic"},
        "conversation",
        Corpus("[]", {}, {}, {}),
        Folder("drive", "output", "https://demo.sharepoint.com/sites/Demo/Docs/Output"),
    )
    foundry = Mock(version="1")
    foundry.verify_answer.return_value = SimpleNamespace(supported=True, sources=[])
    foundry.summary.return_value = OpinionSummary(topic="Pilot", haltung="Unentschieden")
    graph = Mock()
    graph.upload.return_value = {
        "id": "owned-item",
        "webUrl": "https://demo.sharepoint.com/synthetic.docx",
    }
    task = asyncio.create_task(voice.bridge(browser, session, settings, foundry, graph))
    try:
        await upstream.incoming.put({"type": "session.updated"})
        await until(lambda: any(message["type"] == "connected" for message in browser.sent))
        yield upstream, browser, session, foundry, graph
        await browser.incoming.put({"type": "stop"})
        await asyncio.wait_for(task, timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def complete_greeting(upstream, browser):
    await upstream.incoming.put(
        {
            "type": "response.done",
            "response": {
                "status": "completed",
                "output": [{"id": "greeting", "content": [{"text": "Hallo."}]}],
            },
        }
    )
    await until(lambda: any(message.get("message") == "Bereit." for message in browser.sent))


@pytest.mark.parametrize(
    "message",
    [
        {"type": "text", "text": None},
        {"type": "text", "text": ""},
        {"type": "text", "text": " "},
        {"type": "text", "text": "x" * 6001},
        {"type": "audio", "audio": None},
        {"type": "audio", "audio": "A" * 65537},
        {"type": "avatar_offer", "client_sdp": "unexpected"},
    ],
)
def test_invalid_browser_messages_are_rejected_without_storing_turns(monkeypatch, message):
    async def scenario():
        async with running_voice(monkeypatch) as (_, browser, session, _, _):
            await browser.incoming.put(message)
            await until(lambda: any(entry["type"] == "error" for entry in browser.sent))
            assert session.user_turns == []

    asyncio.run(scenario())


def test_audio_chunks_are_forwarded_only_through_the_input_buffer(monkeypatch):
    async def scenario():
        async with running_voice(monkeypatch) as (upstream, browser, _, _, _):
            await browser.incoming.put({"type": "audio", "audio": "AAAA"})
            await until(
                lambda: any(entry["type"] == "input_audio_buffer.append" for entry in upstream.sent)
            )
            assert upstream.sent[-1] == {"type": "input_audio_buffer.append", "audio": "AAAA"}

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["unsupported", "incomplete", "empty", "validator"])
def test_strict_response_failures_withhold_audio_and_remove_unreleased_items(monkeypatch, failure):
    async def scenario():
        async with running_voice(monkeypatch) as (upstream, browser, _, foundry, _):
            if failure == "unsupported":
                foundry.verify_answer.return_value.supported = False
            if failure == "validator":
                foundry.verify_answer.side_effect = ServiceError("Synthetic validator failure")
            await upstream.incoming.put({"type": "response.created"})
            await upstream.incoming.put(
                {"type": "response.audio.delta", "item_id": "rejected", "delta": "AAAA"}
            )
            await upstream.incoming.put(
                {
                    "type": "response.done",
                    "response": {
                        "status": "failed" if failure == "incomplete" else "completed",
                        "output": [
                            {
                                "id": "rejected",
                                "content": []
                                if failure == "empty"
                                else [{"text": "Synthetic answer"}],
                            }
                        ],
                    },
                }
            )
            await until(
                lambda: any(entry["type"] == "conversation.item.delete" for entry in upstream.sent)
            )
            assert any(entry["type"] == "error" for entry in browser.sent)
            assert not any(entry["type"] in ("audio", "assistant") for entry in browser.sent)

    asyncio.run(scenario())


@pytest.mark.parametrize("request_kind", ["finish", "text"])
def test_speech_recognition_failure_releases_pending_turn_and_deletes_failed_item(
    monkeypatch, request_kind
):
    async def scenario():
        async with running_voice(monkeypatch) as (upstream, browser, session, _, _):
            await complete_greeting(upstream, browser)
            await upstream.incoming.put({"type": "input_audio_buffer.speech_started"})
            await until(lambda: any(entry["type"] == "speech_started" for entry in browser.sent))
            await browser.incoming.put({"type": request_kind, "text": "Typed too early"})
            await until(
                lambda: any("noch erkannt" in entry.get("message", "") for entry in browser.sent)
            )
            await upstream.incoming.put(
                {
                    "type": "conversation.item.input_audio_transcription.failed",
                    "item_id": "failed-input",
                }
            )
            await until(
                lambda: any(
                    "Spracherkennung fehlgeschlagen" in entry.get("message", "")
                    for entry in browser.sent
                )
            )
            assert session.user_turns == []
            cleanup = next(
                entry for entry in upstream.sent if entry.get("item_id") == "failed-input"
            )
            assert cleanup["type"] == "conversation.item.delete"
            await upstream.incoming.put(
                {"type": "conversation.item.deleted", "item_id": "failed-input"}
            )
            await browser.incoming.put({"type": "text", "text": "Now accepted"})
            await until(lambda: session.user_turns == ["Now accepted"])

    asyncio.run(scenario())


def test_empty_and_duplicate_transcriptions_do_not_add_turns(monkeypatch):
    async def scenario():
        async with running_voice(monkeypatch) as (upstream, _, session, _, _):
            event = {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "empty-input",
                "transcript": "  ",
            }
            await upstream.incoming.put(event)
            await until(
                lambda: any(entry.get("item_id") == "empty-input" for entry in upstream.sent)
            )
            await upstream.incoming.put({**event, "transcript": "Duplicate must be ignored"})
            await upstream.incoming.put({**event, "item_id": "second-empty"})
            await until(
                lambda: any(entry.get("item_id") == "second-empty" for entry in upstream.sent)
            )
            assert session.user_turns == []

    asyncio.run(scenario())


@pytest.mark.parametrize("confirmation", ["approve", "decline", "editing"])
def test_spoken_review_confirmation_never_saves_declined_or_dirty_drafts(monkeypatch, confirmation):
    async def scenario():
        async with running_voice(monkeypatch) as (upstream, browser, session, _, graph):
            await complete_greeting(upstream, browser)
            await browser.incoming.put({"type": "finish"})
            await until(lambda: any(entry["type"] == "draft" for entry in browser.sent))
            graph.upload.assert_not_called()
            if confirmation == "decline":
                await browser.incoming.put({"type": "text", "text": "nein"})
                await until(
                    lambda: any(
                        "Nicht gespeichert" in entry.get("message", "") for entry in browser.sent
                    )
                )
            elif confirmation == "editing":
                await browser.incoming.put({"type": "draft_editing", "version": 1})
                await until(lambda: session.draft_editing)
            await browser.incoming.put({"type": "text", "text": "ja speichern"})
            expected = "saved" if confirmation == "approve" else "error"
            await until(lambda: any(entry["type"] == expected for entry in browser.sent))
            assert graph.upload.call_count == (1 if confirmation == "approve" else 0)
            assert session.phase == ("saved" if confirmation == "approve" else "review")

    asyncio.run(scenario())


def test_streaming_source_backlog_is_bounded_and_pending_checks_are_cancelled(monkeypatch):
    async def scenario():
        started, cancelled = [], []

        async def blocked_sources(socket, foundry, corpus, turns, text, item_id):
            started.append(item_id)
            try:
                await asyncio.Future()
            finally:
                cancelled.append(item_id)

        monkeypatch.setattr(voice, "attribute_sources", blocked_sources)
        async with running_voice(monkeypatch, mode="streaming") as (upstream, browser, _, _, _):
            for number in range(3):
                item_id = f"answer-{number}"
                await upstream.incoming.put({"type": "response.created"})
                await upstream.incoming.put(
                    {"type": "response.text.delta", "item_id": item_id, "delta": "Antwort."}
                )
                await upstream.incoming.put(
                    {
                        "type": "response.done",
                        "response": {"status": "completed", "output": [{"id": item_id}]},
                    }
                )
                await until(
                    lambda number=number: (
                        sum(entry.get("message") == "Bereit." for entry in browser.sent)
                        == number + 1
                    )
                )
            await until(lambda: any(entry.get("source_status") == "busy" for entry in browser.sent))
            assert started == ["answer-0", "answer-1"]
        assert sorted(cancelled) == ["answer-0", "answer-1"]

    asyncio.run(scenario())
