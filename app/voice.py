import asyncio
import logging
import re
import unicodedata

from azure.ai.voicelive.aio import connect
from azure.identity.aio import AzureCliCredential
from fastapi import WebSocket

from app.avatar import checked_ice, checked_sdp
from app.config import Settings
from app.diagnostics import record_diagnostic
from app.foundry import Foundry
from app.graph import Graph, ServiceError
from app.sessions import Session
from app.source_attribution import attribute_sources

logger = logging.getLogger(__name__)
AVATAR_HANDSHAKE_TIMEOUT = 35


def voice_session_settings(settings, avatar=False):
    result = {
        "modalities": ["text", "audio"],
        "voice": {"type": "azure-standard", "name": settings.voice_name},
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "input_audio_sampling_rate": 24000,
        "input_audio_transcription": {"model": "azure-speech", "language": "de-DE"},
        "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
        "turn_detection": {
            "type": "azure_semantic_vad_multilingual",
            "threshold": 0.6,
            "prefix_padding_ms": 420,
            "speech_duration_ms": 200,
            "silence_duration_ms": 500,
            "create_response": False,
            "interrupt_response": False,
        },
    }
    if avatar:
        result["avatar"] = {
            "character": getattr(settings, "avatar_character", "lisa"),
            "style": getattr(settings, "avatar_style", "casual-sitting"),
            "customized": False,
        }
    return result


def cleanup_error_request(failure, requests):
    if failure.get("code") != "item_delete_invalid_item_id":
        return None
    event_id = failure.get("event_id")
    if event_id in requests:
        return event_id
    if event_id is not None:
        return None
    # Voice Live can omit event_id even when supplied. Match only its exact
    # missing-item diagnostic against an outstanding operation issued by us.
    match = re.fullmatch(
        r"Error deleting item: the item with id '([^']+)' does not exist\.",
        failure.get("message", ""),
    )
    if match:
        return next((key for key, item in requests.items() if item == match[1]), None)
    return None


def summary_requested(text: str) -> bool:
    # Match the entire utterance, not a command hidden in reported speech,
    # negation or a condition. Unknown wording deliberately stays in chat.
    if len(text) > 6000 or re.search(r"""["'„“”‚‘’«»‹›`\\]""", text):
        return False
    normalized = unicodedata.normalize("NFKC", text).casefold()
    for umlaut, spelling in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        normalized = normalized.replace(umlaut, spelling)
    normalized = " ".join(re.sub(r"[.,!?;:…]", " ", normalized).split())
    if len(normalized.split()) > 80:
        return False

    filler = r"(?:ja|ok|okay|also|eben|gut|ist gut|alles klar|jetzt|nun|bitte|dann)"
    polite = r"(?:(?:jetzt|nun|bitte|doch|mal|einmal|gerne) )*"
    summary = r"(?:(?:eine|die|meine|unsere) )?zusammenfassung"
    subject = (
        r"(?:das|dies|unser gespraech|das gespraech|unsere unterhaltung|"
        r"meine meinungsbildung)"
    )
    command = (
        rf"(?:{summary} {polite}erstellen|"
        rf"(?:erstelle|erstellen sie) {polite}{summary}|"
        rf"(?:(?:{subject}) )?{polite}zusammenfassen|"
        rf"fasse {polite}{subject} {polite}zusammen|"
        rf"fassen sie {polite}{subject} {polite}zusammen|"
        rf"ich (?:moechte|will) {polite}{summary}(?: {polite}erstellen lassen)?|"
        rf"(?:kannst du|koenntest du|koennen sie|koennten sie) {polite}"
        rf"(?:{subject} {polite}zusammenfassen|{summary} {polite}erstellen))"
    )
    # A release requested before seeing the draft is only a request for review.
    # It never substitutes for the separate, version-bound save confirmation.
    release = r"(?: und (?:fuer diesen entwurf )?(?:so )?freigeben)?"
    return (
        re.fullmatch(rf"(?:{filler} )*{command}(?: bitte| jetzt| danke)*{release}", normalized)
        is not None
    )


async def bridge(
    socket: WebSocket, session: Session, settings: Settings, foundry: Foundry, graph: Graph
):
    delivery_mode = getattr(settings, "voice_delivery_mode", "strict")
    if delivery_mode not in ("strict", "streaming"):
        raise ServiceError("Ungueltiger Sprach-Ausgabemodus.")
    streaming = delivery_mode == "streaming"
    avatar = getattr(session, "avatar_enabled", False)
    if avatar and (not streaming or not getattr(settings, "avatar_enabled", False)):
        raise ServiceError("Avatar erfordert aktivierten Streaming-Modus.")
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
            confirmation_version = None
            generating = False
            speech_pending = False
            finishing = None
            audio_size = 0
            reviewing = False
            transitioning = False
            background_failure = asyncio.get_running_loop().create_future()
            cleanup_requests = {}
            deleted_items = set()
            stream_announced = False
            source_tasks = set()

            def source_finished(task):
                source_tasks.discard(task)
                if not task.cancelled() and task.exception():
                    logger.warning("Post-response source result could not be delivered.")

            avatar_state = "starting" if avatar else "off"
            avatar_ready = asyncio.Event()
            service_session_id = ""

            async def avatar_failure(
                reason="browser_connection_failed", *, browser=None, service=None, event_id=""
            ):
                diagnostic_id = record_diagnostic(
                    "avatar_failure",
                    reason=reason,
                    phase=avatar_state,
                    browser=browser,
                    service=service,
                    service_session_id=service_session_id,
                    service_event_id=event_id,
                    voice_api_version=settings.voice_api_version,
                    model=getattr(settings, "model", ""),
                    delivery_mode=delivery_mode,
                )
                await socket.send_json(
                    {
                        "type": "avatar_failed",
                        "reason": reason,
                        "diagnostic_id": diagnostic_id,
                        "message": "Avatar-Verbindung fehlgeschlagen. "
                        f"Diagnose-ID: {diagnostic_id}. "
                        "Details im Terminal und .local/diagnostics.jsonl. "
                        "Stoppen und ohne Avatar neu starten.",
                    }
                )
                failure = ServiceError(
                    f"Avatar-Verbindung fehlgeschlagen (Diagnose {diagnostic_id})."
                )
                failure.diagnostic_id = diagnostic_id
                raise failure

            async def handshake_timeout():
                try:
                    await asyncio.wait_for(avatar_ready.wait(), timeout=AVATAR_HANDSHAKE_TIMEOUT)
                except TimeoutError:
                    await avatar_failure("handshake_timeout")
                await asyncio.Future()

            async def greet():
                nonlocal initialized, responding, generating
                initialized = True
                await socket.send_json({"type": "connected", "voice_delivery_mode": delivery_mode})
                await status("Verbunden. Sie koennen sprechen oder tippen.")
                await upstream.send(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Bitte begruesse mich kurz "
                                    "und lade zum Sprechen oder Tippen ein.",
                                }
                            ],
                        },
                    }
                )
                responding = generating = True
                await upstream.send({"type": "response.create"})

            async def announce_stream(item_id):
                nonlocal stream_announced
                if not stream_announced:
                    stream_announced = True
                    await socket.send_json(
                        {
                            "type": "assistant_start",
                            "item_id": item_id,
                            "evidence_status": "not_independently_verified",
                        }
                    )

            async def delete_item(item_id):
                if not item_id or item_id in deleted_items:
                    return
                deleted_items.add(item_id)
                event_id = f"cleanup-{len(cleanup_requests)}-{len(deleted_items)}"
                cleanup_requests[event_id] = item_id
                await upstream.send(
                    {
                        "type": "conversation.item.delete",
                        "item_id": item_id,
                        "event_id": event_id,
                    }
                )

            def completion_finished(task):
                if not task.cancelled():
                    failure = task.exception()
                    if failure and not background_failure.done():
                        background_failure.set_exception(failure)

            async def status(message):
                await socket.send_json({"type": "status", "message": message})

            async def error(message):
                await socket.send_json({"type": "error", "message": message})

            async def interrupt(item_id=None, milliseconds=0):
                nonlocal cancelled
                # A delayed playback report belongs to an older answer, not the
                # response currently being generated for the next spoken turn.
                cancel_current = item_id is None or item_id == assistant_item
                if cancel_current:
                    cancelled = True
                await socket.send_json({"type": "interrupt"})
                if generating and cancel_current:
                    await upstream.send({"type": "response.cancel"})
                if avatar and cancel_current:
                    await upstream.send({"type": "output_audio_buffer.clear"})
                if item_id and item_id not in deleted_items:
                    await upstream.send(
                        {
                            "type": "conversation.item.truncate",
                            "item_id": item_id,
                            "content_index": 0,
                            "audio_end_ms": max(0, int(milliseconds)),
                        }
                    )

            async def review():
                nonlocal pending_review, awaiting_confirmation, confirmation_version, reviewing
                pending_review = False
                reviewing = True
                if avatar:
                    await interrupt()
                await status("Zusammenfassung wird erstellt.")
                try:
                    summary = await asyncio.to_thread(
                        foundry.summary,
                        session.conversation_id,
                        session.corpus,
                        user_turns=list(session.user_turns),
                    )
                    snapshot = session.set_draft(summary, validation_passed=True)
                finally:
                    reviewing = False
                awaiting_confirmation = True
                confirmation_version = snapshot["version"]
                await socket.send_json(
                    {
                        "type": "draft",
                        "summary": snapshot["summary"],
                        "version": confirmation_version,
                    }
                )
                await status(
                    "Entwurf bereit. Bitte pruefen und Speicherung ausdruecklich bestaetigen."
                )

            async def accept_text(text, *, already_added=False):
                nonlocal \
                    responding, \
                    generating, \
                    pending_text, \
                    pending_review, \
                    cancelled, \
                    awaiting_confirmation
                if not isinstance(text, str):
                    raise ServiceError("Ungueltiger Textbeitrag.")
                text = text.strip()
                if not text or len(text) > 6000:
                    raise ServiceError("Bitte einen Beitrag mit maximal 6000 Zeichen eingeben.")
                if not already_added and speech_pending:
                    raise ServiceError("Gesprochener Beitrag wird noch erkannt. Bitte kurz warten.")
                if reviewing or transitioning:
                    raise ServiceError("Sitzung wird aktualisiert. Bitte kurz warten.")
                if pending_review or pending_text is not None:
                    raise ServiceError("Ein Beitrag wartet bereits. Bitte kurz warten.")
                normalized = re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
                if session.phase == "review":
                    if awaiting_confirmation and normalized in (
                        "ja speichern",
                        "bitte speichern",
                        "zusammenfassung speichern",
                        "ja bitte speichern",
                    ):
                        await status("Dokument wird gespeichert.")
                        result = await asyncio.to_thread(session.save, graph, confirmation_version)
                        awaiting_confirmation = False
                        await socket.send_json({"type": "saved", **result})
                        return
                    if normalized in ("nein", "abbrechen", "nicht speichern"):
                        awaiting_confirmation = False
                        await status("Nicht gespeichert. Der Entwurf bleibt zur Pruefung erhalten.")
                        return
                    await error(
                        "Der Entwurf ist in Pruefung. "
                        "Bitte per Formular korrigieren oder speichern."
                    )
                    return
                if session.phase != "conversation":
                    raise ServiceError("Diese Sitzung ist bereits abgeschlossen.")
                if summary_requested(text):
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
                    await socket.send_json({"type": "user", "text": text})
                    pending_text = (text, already_added)
                    await interrupt()
                    return
                session.add_turn(text)
                await socket.send_json({"type": "user", "text": text})
                if not already_added:
                    await upstream.send(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": text}],
                            },
                        }
                    )
                cancelled = False
                responding = True
                generating = True
                await upstream.send({"type": "response.create"})

            async def browser_events():
                nonlocal pending_review, awaiting_confirmation, avatar_state
                while True:
                    message = await socket.receive_json()
                    try:
                        kind = message.get("type")
                        if kind == "avatar_offer":
                            if avatar_state != "offering":
                                raise ServiceError("Unerwartetes Avatar-Angebot.")
                            offer = checked_sdp(message.get("client_sdp"), "offer")
                            avatar_state = "answering"
                            await upstream.send(
                                {"type": "session.avatar.connect", "client_sdp": offer}
                            )
                            continue
                        if kind == "avatar_ready":
                            if avatar_state != "connecting":
                                raise ServiceError("Unerwartete Avatar-Bestaetigung.")
                            avatar_state = "ready"
                            avatar_ready.set()
                            await greet()
                            continue
                        if kind == "avatar_failed" and avatar:
                            reason = message.get("reason", "browser_connection_failed")
                            if not isinstance(reason, str) or not re.fullmatch(
                                r"[a-z0-9_]{1,80}", reason
                            ):
                                reason = "browser_connection_failed"
                            await avatar_failure(reason, browser=message.get("diagnostics"))
                            return
                        if avatar and not initialized and kind != "stop":
                            raise ServiceError("Sprachverbindung wird noch vorbereitet.")
                        if (
                            kind == "audio"
                            and not reviewing
                            and session.phase in ("conversation", "review")
                        ):
                            chunk = message.get("audio", "")
                            if not isinstance(chunk, str) or len(chunk) > 65536:
                                raise ServiceError("Ungueltiger Audioblock.")
                            await upstream.send(
                                {"type": "input_audio_buffer.append", "audio": chunk}
                            )
                        elif kind == "text":
                            await accept_text(message.get("text", ""))
                        elif kind == "interrupt":
                            await interrupt(message.get("item_id"), message.get("milliseconds", 0))
                        elif kind == "finish" and session.phase == "conversation":
                            if reviewing or transitioning:
                                raise ServiceError("Zusammenfassung wird bereits erstellt.")
                            if speech_pending:
                                raise ServiceError(
                                    "Gesprochener Beitrag wird noch erkannt. Bitte kurz warten."
                                )
                            if responding:
                                pending_review = True
                                await interrupt()
                            else:
                                await review()
                        elif kind == "stop":
                            await interrupt()
                            return
                        elif kind == "draft_editing":
                            session.mark_editing(message.get("version"))
                            awaiting_confirmation = False
                    except ServiceError as failure:
                        if kind == "avatar_failed":
                            raise
                        await error(str(failure))

            async def complete_response(response):
                nonlocal \
                    responding, \
                    generating, \
                    pending_text, \
                    cancelled, \
                    audio, \
                    text_parts, \
                    audio_size, \
                    transitioning, \
                    assistant_item
                released = False
                try:
                    if not cancelled and response.get("status") == "completed":
                        text = "".join(text_parts).strip()
                        if not text:
                            text = " ".join(
                                content.get("transcript", content.get("text", ""))
                                for item in response.get("output", [])
                                for content in item.get("content", [])
                            )
                        if not text.strip():
                            raise ServiceError("Antwort ohne pruefbaren Text; nicht wiedergegeben.")
                        if streaming:
                            references = []
                            supported = True
                        else:
                            verdict = await asyncio.to_thread(
                                foundry.verify_answer,
                                text,
                                session.corpus,
                                list(session.user_turns),
                            )
                            supported = verdict.supported
                            references = [reference.model_dump() for reference in verdict.sources]
                        if supported and not cancelled:
                            await socket.send_json(
                                {
                                    "type": "assistant",
                                    "text": text,
                                    "item_id": assistant_item,
                                    "sources": references,
                                    "source_status": "pending" if streaming else "checked",
                                    "evidence_status": (
                                        "not_independently_verified" if streaming else "verified"
                                    ),
                                }
                            )
                            for chunk in audio:
                                if cancelled:
                                    break
                                await socket.send_json(
                                    {"type": "audio", "audio": chunk, "item_id": assistant_item}
                                )
                            released = not cancelled
                            if released:
                                await socket.send_json({"type": "audio_done"})
                                await status("Bereit.")
                                if streaming:
                                    if len(source_tasks) < 2:
                                        task = asyncio.create_task(
                                            attribute_sources(
                                                socket,
                                                foundry,
                                                session.corpus,
                                                list(session.user_turns),
                                                text,
                                                assistant_item,
                                            )
                                        )
                                        source_tasks.add(task)
                                        task.add_done_callback(source_finished)
                                    else:
                                        await socket.send_json(
                                            {
                                                "type": "assistant_sources",
                                                "item_id": assistant_item,
                                                "sources": [],
                                                "source_status": "busy",
                                            }
                                        )
                        elif not cancelled:
                            await error(
                                "Antwort nicht ausreichend belegt; nicht wiedergegeben. "
                                "Bitte nachfragen."
                            )
                    elif not cancelled:
                        await error("Antwort wurde nicht abgeschlossen. Bitte erneut versuchen.")
                except Exception:
                    logger.warning("Voice evidence check failed", exc_info=False)
                    await error("Quellenpruefung fehlgeschlagen; Antwort nicht wiedergegeben.")
                finally:
                    transitioning = True
                    if not released:
                        if streaming and stream_announced:
                            await socket.send_json(
                                {
                                    "type": "assistant_interrupted",
                                    "item_id": assistant_item,
                                }
                            )
                        item_ids = {
                            item["id"]
                            for item in response.get("output", [])
                            if item.get("id")
                            and item.get("type", "message") == "message"
                            and item.get("role", "assistant") == "assistant"
                        }
                        if assistant_item:
                            item_ids.add(assistant_item)
                        for item_id in item_ids:
                            await delete_item(item_id)
                    audio, text_parts, audio_size, assistant_item = [], [], 0, None
                if pending_text:
                    text, already_added = pending_text
                    pending_text = None
                    if not already_added:
                        await upstream.send(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": text}],
                                },
                            }
                        )
                    if not pending_review:
                        cancelled = False
                        responding = generating = True
                        await upstream.send({"type": "response.create"})
                if pending_review:
                    try:
                        await review()
                    except Exception:
                        await error("Zusammenfassung fehlgeschlagen. Bitte erneut versuchen.")
                if not generating:
                    responding = False
                transitioning = False

            async def service_events():
                nonlocal service_session_id
                nonlocal \
                    responding, \
                    generating, \
                    pending_text, \
                    cancelled, \
                    initialized, \
                    assistant_item, \
                    audio, \
                    text_parts, \
                    speech_pending, \
                    finishing, \
                    audio_size, \
                    stream_announced
                nonlocal avatar_state
                async for event in upstream:
                    data = event.as_dict()
                    kind = data.get("type")
                    if kind in ("session.created", "session.updated"):
                        details = data.get("session")
                        if isinstance(details, dict) and isinstance(details.get("id"), str):
                            service_session_id = details["id"]
                    if kind == "session.updated" and not initialized:
                        if avatar:
                            if avatar_state != "starting":
                                continue
                            try:
                                ice = checked_ice(
                                    data.get("session", {}).get("avatar", {}).get("ice_servers")
                                )
                            except ServiceError:
                                await avatar_failure("invalid_service_ice")
                            avatar_state = "offering"
                            await socket.send_json({"type": "avatar_start", "ice_servers": ice})
                            continue
                        await greet()
                    elif kind == "session.avatar.connecting":
                        if avatar_state != "answering":
                            await avatar_failure("unexpected_service_answer")
                        try:
                            answer = checked_sdp(data.get("server_sdp"), "answer")
                        except ServiceError:
                            await avatar_failure("invalid_service_answer")
                        avatar_state = "connecting"
                        await socket.send_json({"type": "avatar_answer", "server_sdp": answer})
                    elif kind == "input_audio_buffer.speech_started":
                        speech_pending = True
                        await socket.send_json({"type": "speech_started"})
                    elif kind == "conversation.item.input_audio_transcription.completed":
                        speech_pending = False
                        item_id = data.get("item_id")
                        if item_id not in seen_inputs:
                            seen_inputs.add(item_id)
                            if not data.get("transcript", "").strip():
                                if item_id:
                                    await delete_item(item_id)
                                continue
                            try:
                                await accept_text(data.get("transcript", ""), already_added=True)
                            except ServiceError as failure:
                                if item_id:
                                    await delete_item(item_id)
                                await error(str(failure))
                    elif kind == "conversation.item.input_audio_transcription.failed":
                        speech_pending = False
                        if data.get("item_id"):
                            await delete_item(data["item_id"])
                        await error("Spracherkennung fehlgeschlagen. Bitte erneut sprechen.")
                    elif kind == "response.created":
                        responding = True
                        audio, text_parts, assistant_item = [], [], None
                        stream_announced = False
                        if avatar and not cancelled:
                            await socket.send_json({"type": "avatar_resume"})
                        await status(
                            "Antwort wird gestreamt – ohne separate Vorabpruefung."
                            if streaming
                            else "Antwort wird vorbereitet und geprueft."
                        )
                    elif kind == "response.audio.delta":
                        if cancelled:
                            continue
                        if not streaming:
                            audio.append(data["delta"])
                        audio_size += len(data["delta"])
                        assistant_item = data.get("item_id", assistant_item)
                        if audio_size > 12_000_000:
                            await interrupt()
                            await error("Antwort zu lang. Bitte eine kuerzere Frage stellen.")
                        elif streaming and not avatar:
                            await announce_stream(assistant_item)
                            await socket.send_json(
                                {
                                    "type": "audio",
                                    "audio": data["delta"],
                                    "item_id": assistant_item,
                                }
                            )
                    elif kind in ("response.audio_transcript.delta", "response.text.delta"):
                        if cancelled:
                            continue
                        text_parts.append(data.get("delta", ""))
                        assistant_item = data.get("item_id", assistant_item)
                        if sum(map(len, text_parts)) > 60_000:
                            await interrupt()
                            await error("Antworttext zu lang; nicht wiedergegeben.")
                        elif streaming:
                            await announce_stream(assistant_item)
                            await socket.send_json(
                                {
                                    "type": "assistant_delta",
                                    "text": data.get("delta", ""),
                                    "item_id": assistant_item,
                                }
                            )
                    elif kind == "response.done":
                        if finishing and not finishing.done():
                            logger.warning("Duplicate response.done ignored during finalization.")
                            continue
                        generating = False
                        response = data.get("response", {})
                        finishing = asyncio.create_task(complete_response(response))
                        finishing.add_done_callback(completion_finished)
                    elif kind == "conversation.item.deleted":
                        item_id = data.get("item_id")
                        for key in list(cleanup_requests):
                            if cleanup_requests[key] == item_id:
                                cleanup_requests.pop(key)
                    elif kind == "error":
                        if avatar and not initialized:
                            code = data.get("error", {}).get("code", "unknown")
                            safe_code = (
                                code
                                if isinstance(code, str)
                                and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", code)
                                else "unknown"
                            )
                            await avatar_failure(
                                f"service_{safe_code}",
                                service=data.get("error"),
                                event_id=data.get("event_id", ""),
                            )
                        failure = data.get("error", {})
                        code = failure.get("code", "unknown")
                        cleanup_id = cleanup_error_request(failure, cleanup_requests)
                        if cleanup_id is not None:
                            cleanup_requests.pop(cleanup_id)
                            logger.info("Cancelled response item already absent during cleanup.")
                            continue
                        logger.warning("Voice Live error: %s", code)
                        await error(f"Voice Live: {code}. Sitzung stoppen und erneut starten.")
                    if finishing and finishing.done():
                        finishing.result()

            await upstream.send(
                {
                    "type": "session.update",
                    "session": voice_session_settings(settings, avatar),
                }
            )
            tasks = [
                asyncio.create_task(browser_events()),
                asyncio.create_task(service_events()),
                background_failure,
            ]
            if avatar:
                tasks.append(asyncio.create_task(handshake_timeout()))
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                tasks.extend(source_tasks)
                if finishing:
                    tasks.append(finishing)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
