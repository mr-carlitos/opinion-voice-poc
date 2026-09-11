import asyncio
import threading
from types import SimpleNamespace

import pytest

from app import voice
from app.graph import ServiceError


class Transport:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def send(self, message):
        self.sent.append(message)

    send_json = send

    async def receive_json(self):
        return await self.incoming.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.incoming.get()
        return SimpleNamespace(as_dict=lambda: message)


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


def test_barge_in_during_evidence_drops_audio_and_preserves_one_queued_turn(monkeypatch):
    async def scenario():
        upstream, browser = Transport(), Transport()
        monkeypatch.setattr(voice, "connect", lambda **kwargs: upstream)
        monkeypatch.setattr(voice, "AzureCliCredential", lambda **kwargs: Transport())
        started, release = threading.Event(), threading.Event()

        def verify(*args):
            started.set()
            assert release.wait(3)
            return SimpleNamespace(supported=True, sources=[])

        session = SimpleNamespace(
            conversation_id="same",
            corpus=None,
            user_turns=[],
            phase="conversation",
        )
        session.add_turn = session.user_turns.append
        settings = SimpleNamespace(
            tenant_id="tenant",
            voice_endpoint="endpoint",
            voice_api_version="version",
            agent_name="agent",
            project_endpoint="endpoint/project",
            voice_name="voice",
        )
        task = asyncio.create_task(
            voice.bridge(
                browser,
                session,
                settings,
                SimpleNamespace(version="2", verify_answer=verify),
                None,
            )
        )
        try:
            await upstream.incoming.put({"type": "session.updated"})
            await until(lambda: any(x["type"] == "response.create" for x in upstream.sent))
            await upstream.incoming.put({"type": "response.created"})
            await upstream.incoming.put(
                {"type": "response.audio.delta", "item_id": "old", "delta": "AA=="}
            )
            await upstream.incoming.put(
                {"type": "response.audio_transcript.delta", "item_id": "old", "delta": "Hallo"}
            )
            await upstream.incoming.put(
                {
                    "type": "response.done",
                    "response": {"status": "completed", "output": [{"id": "old"}]},
                }
            )
            await until(started.is_set)
            assert not any(x["type"] == "audio" for x in browser.sent)
            await upstream.incoming.put({"type": "input_audio_buffer.speech_started"})
            await until(lambda: any(x["type"] == "speech_started" for x in browser.sent))
            assert not any(x["type"] == "interrupt" for x in browser.sent)
            await browser.incoming.put({"type": "text", "text": "too early"})
            await until(lambda: any(x["type"] == "error" for x in browser.sent))
            await upstream.incoming.put(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "spoken",
                    "transcript": "Meine Haltung",
                }
            )
            await until(lambda: session.user_turns == ["Meine Haltung"])
            release.set()
            await until(lambda: sum(x["type"] == "response.create" for x in upstream.sent) == 2)
            assert not any(x["type"] == "audio" for x in browser.sent)
            assert not any(x["type"] == "response.cancel" for x in upstream.sent)
            assert any(
                x["type"] == "conversation.item.delete" and x["item_id"] == "old"
                for x in upstream.sent
            )
            cleanup = next(x for x in upstream.sent if x["type"] == "conversation.item.delete")
            await upstream.incoming.put(
                {
                    "type": "error",
                    "error": {
                        "code": "item_delete_invalid_item_id",
                        "event_id": cleanup["event_id"],
                    },
                }
            )
            await asyncio.sleep(0.02)
            assert not any(
                x["type"] == "error" and "item_delete_invalid_item_id" in x.get("message", "")
                for x in browser.sent
            )
            await upstream.incoming.put(
                {
                    "type": "error",
                    "error": {
                        "code": "item_delete_invalid_item_id",
                        "event_id": "unrelated",
                    },
                }
            )
            await until(
                lambda: any(
                    x["type"] == "error" and "item_delete_invalid_item_id" in x.get("message", "")
                    for x in browser.sent
                )
            )
            assert [x["text"] for x in browser.sent if x["type"] == "user"] == ["Meine Haltung"]
            assert not any(
                x.get("item", {}).get("content", [{}])[0].get("text") == "Meine Haltung"
                for x in upstream.sent
            )
            await upstream.incoming.put({"type": "response.created"})
            await upstream.incoming.put(
                {
                    "type": "response.audio.delta",
                    "item_id": "new",
                    "delta": "AA==",
                }
            )
            await browser.incoming.put(
                {
                    "type": "interrupt",
                    "item_id": "old",
                    "milliseconds": 250,
                }
            )
            await asyncio.sleep(0.02)
            assert not any(x["type"] == "response.cancel" for x in upstream.sent)
            await upstream.incoming.put(
                {
                    "type": "response.audio_transcript.delta",
                    "item_id": "new",
                    "delta": "Antwort auf die neue Frage.",
                }
            )
            await upstream.incoming.put(
                {
                    "type": "response.done",
                    "response": {
                        "status": "completed",
                        "output": [{"id": "new", "type": "message"}],
                    },
                }
            )
            await until(
                lambda: any(
                    x["type"] == "assistant" and x.get("item_id") == "new" for x in browser.sent
                )
            )
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("finish", [False, True])
def test_queued_typed_turn_is_added_once_before_response_or_summary(monkeypatch, finish):
    async def scenario():
        upstream, browser = Transport(), Transport()
        monkeypatch.setattr(voice, "connect", lambda **kwargs: upstream)
        monkeypatch.setattr(voice, "AzureCliCredential", lambda **kwargs: Transport())
        session = SimpleNamespace(
            conversation_id="same",
            corpus=None,
            user_turns=[],
            phase="conversation",
            draft_version=1,
        )
        session.add_turn = session.user_turns.append
        summary_inputs = []

        def summary(*args, user_turns):
            assert user_turns == ["Meine Korrektur"]
            assert user_turns is not session.user_turns
            summary_inputs.extend(upstream.sent)
            return SimpleNamespace(model_dump=lambda **kwargs: {})

        def set_draft(value, *, validation_passed):
            assert validation_passed
            session.phase = "review"
            return {"summary": {}, "version": session.draft_version}

        session.set_draft = set_draft
        settings = SimpleNamespace(
            tenant_id="t",
            voice_endpoint="e",
            voice_api_version="v",
            agent_name="a",
            project_endpoint="e/p",
            voice_name="v",
        )
        task = asyncio.create_task(
            voice.bridge(
                browser, session, settings, SimpleNamespace(version="2", summary=summary), None
            )
        )
        try:
            await upstream.incoming.put({"type": "session.updated"})
            await upstream.incoming.put({"type": "response.created"})
            await until(lambda: any(x["type"] == "response.create" for x in upstream.sent))
            await browser.incoming.put({"type": "text", "text": "Meine Korrektur"})
            await until(lambda: session.user_turns == ["Meine Korrektur"])
            await browser.incoming.put({"type": "text", "text": "Nicht angenommen"})
            await until(lambda: any(x["type"] == "error" for x in browser.sent))
            if finish:
                await browser.incoming.put({"type": "finish"})
                await until(lambda: sum(x["type"] == "interrupt" for x in browser.sent) == 2)
            await upstream.incoming.put(
                {
                    "type": "response.done",
                    "response": {"status": "cancelled", "output": [{"id": "unheard"}]},
                }
            )
            await until(
                lambda: (
                    session.phase == "review"
                    if finish
                    else sum(x["type"] == "response.create" for x in upstream.sent) == 2
                )
            )
            assert session.user_turns == ["Meine Korrektur"]
            messages = summary_inputs if finish else upstream.sent
            assert (
                sum(
                    x.get("item", {}).get("content", [{}])[0].get("text") == "Meine Korrektur"
                    for x in messages
                )
                == 1
            )
            assert [x["text"] for x in browser.sent if x["type"] == "user"] == ["Meine Korrektur"]
            assert any(
                x["type"] == "conversation.item.delete" and x["item_id"] == "unheard"
                for x in upstream.sent
            )
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_failed_evidence_is_visible_and_deletes_unheard_history(monkeypatch):
    async def scenario():
        upstream, browser = Transport(), Transport()
        monkeypatch.setattr(voice, "connect", lambda **kwargs: upstream)
        monkeypatch.setattr(voice, "AzureCliCredential", lambda **kwargs: Transport())

        def verify(*args):
            raise RuntimeError("private backend detail")

        session = SimpleNamespace(
            conversation_id="same", corpus=None, user_turns=[], phase="conversation"
        )
        settings = SimpleNamespace(
            tenant_id="t",
            voice_endpoint="e",
            voice_api_version="v",
            agent_name="a",
            project_endpoint="e/p",
            voice_name="v",
        )
        task = asyncio.create_task(
            voice.bridge(
                browser, session, settings, SimpleNamespace(version="2", verify_answer=verify), None
            )
        )
        try:
            await upstream.incoming.put({"type": "session.updated"})
            await upstream.incoming.put({"type": "response.created"})
            await upstream.incoming.put(
                {"type": "response.text.delta", "delta": "Test", "item_id": "bad"}
            )
            await upstream.incoming.put(
                {
                    "type": "response.done",
                    "response": {"status": "completed", "output": [{"id": "bad"}]},
                }
            )
            await until(lambda: any(x["type"] == "error" for x in browser.sent))
            await until(
                lambda: any(
                    x["type"] == "conversation.item.delete" and x["item_id"] == "bad"
                    for x in upstream.sent
                )
            )
            assert not any(x["type"] in ("audio", "assistant") for x in browser.sent)
            assert "private backend detail" not in str(browser.sent)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_spoken_approval_cannot_approve_newer_form_version(monkeypatch):
    async def scenario():
        upstream, browser = Transport(), Transport()
        monkeypatch.setattr(voice, "connect", lambda **kwargs: upstream)
        monkeypatch.setattr(voice, "AzureCliCredential", lambda **kwargs: Transport())
        session = SimpleNamespace(
            conversation_id="same",
            corpus=None,
            user_turns=[],
            phase="conversation",
            draft_version=0,
        )
        approvals = []

        def set_draft(value, *, validation_passed):
            assert validation_passed
            session.phase = "review"
            session.draft_version = 1
            return {"summary": {}, "version": 1}

        def save(graph, version):
            approvals.append(version)
            if version != session.draft_version:
                raise ServiceError("Keine passende, gepruefte Zusammenfassung vorhanden.")
            return {}

        session.set_draft, session.save = set_draft, save
        settings = SimpleNamespace(
            tenant_id="t",
            voice_endpoint="e",
            voice_api_version="v",
            agent_name="a",
            project_endpoint="e/p",
            voice_name="v",
        )
        task = asyncio.create_task(
            voice.bridge(
                browser,
                session,
                settings,
                SimpleNamespace(version="2", summary=lambda *args, **kwargs: object()),
                None,
            )
        )
        try:
            await browser.incoming.put({"type": "finish"})
            await until(lambda: any(x["type"] == "draft" for x in browser.sent))
            session.draft_version = 2
            await browser.incoming.put({"type": "text", "text": "Ja speichern"})
            await until(lambda: any(x["type"] == "error" for x in browser.sent))
            assert approvals == [1]
            assert not any(x["type"] == "saved" for x in browser.sent)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
