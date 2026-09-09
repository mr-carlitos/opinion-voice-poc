import asyncio
import logging
import re

from azure.ai.voicelive.aio import connect
from azure.identity.aio import AzureCliCredential
from fastapi import WebSocket

from app.config import Settings
from app.foundry import Foundry
from app.graph import Graph, ServiceError
from app.sessions import Session

logger = logging.getLogger(__name__)


async def bridge(socket: WebSocket, session: Session, settings: Settings, foundry: Foundry, graph: Graph):
    async with AzureCliCredential(tenant_id=settings.tenant_id) as credential:
        async with connect(
            endpoint=settings.voice_endpoint,
            credential=credential,
            api_version=settings.voice_api_version,
            agent_name=settings.agent_name,
            project_name=settings.project_endpoint.rsplit("/", 1)[-1],
            agent_version=foundry.version,
            conversation_id=session.conversation_id,
        ) as upstream:
            responding = False
            pending_text = None
            pending_review = False
            audio = []
            text_parts = []
            assistant_item = None
            seen_inputs = set()
            cancelled = False
            initialized = False
            awaiting_confirmation = False

            async def status(message):
                await socket.send_json({"type": "status", "message": message})

            async def error(message):
                await socket.send_json({"type": "error", "message": message})

            async def interrupt(item_id=None, milliseconds=0):
                nonlocal cancelled
                cancelled = True
                await socket.send_json({"type": "interrupt"})
                if responding:
                    await upstream.send({"type": "response.cancel"})
                if item_id:
                    await upstream.send({"type": "conversation.item.truncate", "item_id": item_id, "content_index": 0, "audio_end_ms": max(0, int(milliseconds))})

            async def review():
                nonlocal pending_review, awaiting_confirmation
                pending_review = False
                await status("Zusammenfassung wird erstellt.")
                summary = await asyncio.to_thread(foundry.summary, session.conversation_id, session.corpus)
                session.set_draft(summary)
                awaiting_confirmation = True
                await socket.send_json({"type": "draft", "summary": summary.model_dump(mode="json"), "version": session.draft_version})
                await status("Entwurf bereit. Bitte pruefen und Speicherung ausdruecklich bestaetigen.")

            async def accept_text(text, *, already_added=False):
                nonlocal responding, pending_text, pending_review, cancelled, awaiting_confirmation
                text = text.strip()
                if not text or len(text) > 6000:
                    raise ServiceError("Bitte einen Beitrag mit maximal 6000 Zeichen eingeben.")
                await socket.send_json({"type": "user", "text": text})
                normalized = re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
                if session.phase == "review":
                    if awaiting_confirmation and normalized in ("ja speichern", "bitte speichern", "zusammenfassung speichern", "ja bitte speichern"):
                        await status("Dokument wird gespeichert.")
                        result = await asyncio.to_thread(session.save, graph, session.draft_version)
                        awaiting_confirmation = False
                        await socket.send_json({"type": "saved", **result})
                        return
                    if normalized in ("nein", "abbrechen", "nicht speichern"):
                        awaiting_confirmation = False
                        await status("Nicht gespeichert. Der Entwurf bleibt zur Pruefung erhalten.")
                        return
                    await error("Der Entwurf ist in Pruefung. Bitte per Formular korrigieren oder speichern.")
                    return
                if session.phase != "conversation":
                    raise ServiceError("Diese Sitzung ist bereits abgeschlossen.")
                if normalized in ("bitte meine meinungsbildung zusammenfassen", "zusammenfassung erstellen", "bitte zusammenfassen"):
                    if responding:
                        pending_review = True
                        await interrupt()
                    else:
                        await review()
                    return
                if responding:
                    if pending_text is not None:
                        raise ServiceError("Ein Beitrag wartet bereits. Bitte kurz warten.")
                    session.add_turn(text)
                    pending_text = (text, already_added)
                    await interrupt()
                    return
                session.add_turn(text)
                if not already_added:
                    await upstream.send({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
                cancelled = False
                responding = True
                await upstream.send({"type": "response.create"})

            async def browser_events():
                nonlocal pending_review, awaiting_confirmation
                while True:
                    message = await socket.receive_json()
                    try:
                        kind = message.get("type")
                        if kind == "audio" and session.phase in ("conversation", "review"):
                            chunk = message.get("audio", "")
                            if not isinstance(chunk, str) or len(chunk) > 65536:
                                raise ServiceError("Ungueltiger Audioblock.")
                            await upstream.send({"type": "input_audio_buffer.append", "audio": chunk})
                        elif kind == "text":
                            await accept_text(message.get("text", ""))
                        elif kind == "interrupt":
                            await interrupt(message.get("item_id"), message.get("milliseconds", 0))
                        elif kind == "finish" and session.phase == "conversation":
                            if responding:
                                pending_review = True
                                await interrupt()
                            else:
                                await review()
                        elif kind == "stop":
                            await interrupt()
                            return
                        elif kind == "draft_editing":
                            session.draft_editing = True
                            awaiting_confirmation = False
                    except ServiceError as failure:
                        await error(str(failure))

            async def service_events():
                nonlocal responding, pending_text, cancelled, initialized, assistant_item, audio, text_parts
                async for event in upstream:
                    data = event.as_dict()
                    kind = data.get("type")
                    if kind == "session.updated" and not initialized:
                        initialized = True
                        await socket.send_json({"type": "connected"})
                        await status("Verbunden. Sie koennen sprechen oder tippen.")
                        await upstream.send({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Bitte begruesse mich kurz und lade zum Sprechen oder Tippen ein."}]}})
                        responding = True
                        await upstream.send({"type": "response.create"})
                    elif kind == "input_audio_buffer.speech_started":
                        await socket.send_json({"type": "speech_started"})
                        await interrupt()
                    elif kind == "conversation.item.input_audio_transcription.completed":
                        item_id = data.get("item_id")
                        if item_id not in seen_inputs:
                            seen_inputs.add(item_id)
                            try:
                                await accept_text(data.get("transcript", ""), already_added=True)
                            except ServiceError as failure:
                                await error(str(failure))
                    elif kind == "response.created":
                        responding = True
                        audio, text_parts, assistant_item = [], [], None
                        await status("Antwort wird vorbereitet und geprueft.")
                    elif kind == "response.audio.delta":
                        audio.append(data["delta"])
                        assistant_item = data.get("item_id", assistant_item)
                        if sum(map(len, audio)) > 12_000_000:
                            await interrupt()
                            await error("Antwort zu lang. Bitte eine kuerzere Frage stellen.")
                    elif kind in ("response.audio_transcript.delta", "response.text.delta"):
                        text_parts.append(data.get("delta", ""))
                        assistant_item = data.get("item_id", assistant_item)
                    elif kind == "response.done":
                        response = data.get("response", {})
                        if not cancelled and response.get("status") == "completed":
                            text = "".join(text_parts).strip()
                            if not text:
                                text = " ".join(content.get("transcript", content.get("text", "")) for item in response.get("output", []) for content in item.get("content", []))
                            verdict = await asyncio.to_thread(foundry.verify_answer, text, session.corpus, list(session.user_turns))
                            if verdict.supported and not cancelled:
                                await socket.send_json({"type": "assistant", "text": text, "item_id": assistant_item, "sources": [reference.model_dump() for reference in verdict.sources]})
                                for chunk in audio:
                                    await socket.send_json({"type": "audio", "audio": chunk, "item_id": assistant_item})
                                await socket.send_json({"type": "audio_done"})
                                await status("Bereit.")
                            else:
                                if assistant_item:
                                    await upstream.send({"type": "conversation.item.delete", "item_id": assistant_item})
                                await error("Antwort nicht ausreichend belegt; nicht wiedergegeben. Bitte nachfragen.")
                        elif not cancelled:
                            await error("Antwort wurde nicht abgeschlossen. Bitte erneut versuchen.")
                        audio, text_parts = [], []
                        responding = False
                        if pending_review:
                            await review()
                        elif pending_text:
                            text, already_added = pending_text
                            pending_text = None
                            if not already_added:
                                await upstream.send({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
                            cancelled = False
                            responding = True
                            await upstream.send({"type": "response.create"})
                    elif kind == "error":
                        failure = data.get("error", {})
                        code = failure.get("code", "unknown")
                        logger.warning("Voice Live error: %s", code)
                        await error(f"Voice Live: {code}. Sitzung stoppen und erneut starten.")

            await upstream.send({"type": "session.update", "session": {
                "modalities": ["text", "audio"],
                "voice": {"type": "azure-standard", "name": settings.voice_name},
                "input_audio_format": "pcm16", "output_audio_format": "pcm16",
                "input_audio_sampling_rate": 24000,
                "input_audio_transcription": {"model": "azure-speech", "language": "de-DE"},
                "turn_detection": {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300, "silence_duration_ms": 700, "create_response": False, "interrupt_response": False},
            }})
            tasks = [asyncio.create_task(browser_events()), asyncio.create_task(service_events())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)