"""Explicit live model/Voice Live compatibility probe; uses synthetic SharePoint data."""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from azure.ai.voicelive.aio import connect
from azure.identity.aio import AzureCliCredential

from app.config import ROOT, Settings
from app.foundry import Foundry
from app.graph import Graph, GraphAuth, ServiceError, ensure_separate_folders
from app.grounding import load_corpus


async def voice_probe(settings, foundry, conversation_id):
    result = {"audio_chunks": 0, "audio_base64_characters": 0}
    parts = []
    async with AzureCliCredential(tenant_id=settings.tenant_id) as credential:
        async with connect(
            endpoint=settings.voice_endpoint,
            credential=credential,
            api_version=settings.voice_api_version,
            agent_name=settings.agent_name,
            project_name=settings.project_endpoint.rsplit("/", 1)[-1],
            agent_version=foundry.version,
            conversation_id=conversation_id,
        ) as upstream:
            start = time.monotonic()
            await upstream.send(
                {
                    "type": "session.update",
                    "session": {
                        "modalities": ["text", "audio"],
                        "voice": {"type": "azure-standard", "name": settings.voice_name},
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "input_audio_sampling_rate": 24000,
                        "input_audio_transcription": {"model": "azure-speech", "language": "de-DE"},
                        "turn_detection": {
                            "type": "server_vad",
                            "create_response": False,
                            "interrupt_response": False,
                        },
                    },
                }
            )
            initialized = False
            async for event in upstream:
                data = event.as_dict()
                kind = data.get("type")
                if kind == "error":
                    code = data.get("error", {}).get("code", "unknown")
                    print("Voice error code:", code, flush=True)
                    raise ServiceError(f"Voice Live rejected the model probe ({code}).")
                if kind == "session.updated" and not initialized:
                    initialized = True
                    result["session_ready_seconds"] = round(time.monotonic() - start, 2)
                    await upstream.send(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": "Wie viele Fahrzeuge umfasst der Pilot? "
                                        "Antworte kurz auf Deutsch mit Quellenverweis.",
                                    }
                                ],
                            },
                        }
                    )
                    start = time.monotonic()
                    await upstream.send({"type": "response.create"})
                elif kind in ("response.audio.delta", "response.output_audio.delta"):
                    result.setdefault("first_audio_seconds", round(time.monotonic() - start, 2))
                    result["audio_chunks"] += 1
                    result["audio_base64_characters"] += len(data.get("delta", ""))
                elif kind in (
                    "response.audio_transcript.delta",
                    "response.text.delta",
                    "response.output_audio_transcript.delta",
                    "response.output_text.delta",
                ):
                    parts.append(data.get("delta", ""))
                elif kind == "response.done":
                    response = data.get("response", {})
                    if response.get("status") != "completed":
                        raise ServiceError("Voice Live response did not complete.")
                    text = "".join(parts).strip() or " ".join(
                        content.get("transcript", content.get("text", ""))
                        for item in response.get("output", [])
                        for content in item.get("content", [])
                    )
                    if not result["audio_chunks"] or "30" not in text:
                        raise ServiceError("Voice probe did not return audio and the corpus fact.")
                    result["response_completed_seconds"] = round(time.monotonic() - start, 2)
                    return result, text
    raise ServiceError("Voice connection ended without a completed response.")


def main():
    settings = Settings.load()
    if issues := settings.issues():
        raise ServiceError("; ".join(issues))
    print("Explicit live probe; model usage is billable. Model:", settings.model, flush=True)
    auth = GraphAuth(settings)
    auth.authenticate()
    if not auth.owner:
        raise ServiceError(auth.snapshot()["message"])
    graph = Graph(auth)
    source = graph.resolve_folder(
        settings.input_url, drive_id=settings.input_drive_id, item_id=settings.input_folder_id
    )
    output = graph.resolve_folder(
        settings.output_url, drive_id=settings.output_drive_id, item_id=settings.output_folder_id
    )
    ensure_separate_folders(source, output)
    started = time.monotonic()
    corpus = load_corpus(graph, source)
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "model": settings.model,
        "corpus_load_seconds": round(time.monotonic() - started, 2),
        "source_documents": len(corpus.sources),
        "microphone_tested": False,
        "browser_playback_tested": False,
    }
    print("Real SharePoint corpus loaded:", len(corpus.sources), "documents.", flush=True)
    foundry = Foundry(settings)
    conversation_id = None
    try:
        report["agent_version"] = foundry.configure_agent()
        conversation_id = foundry.create_conversation(corpus)

        async def run_voice():
            async with asyncio.timeout(100):
                return await voice_probe(settings, foundry, conversation_id)

        report["voice"], answer = asyncio.run(run_voice())
        print("Voice Live generated audio and the correct corpus fact.", flush=True)
        started = time.monotonic()
        verdict = foundry.verify_answer(answer, corpus, [])
        if not verdict.supported or not verdict.sources:
            raise ServiceError("Voice answer did not pass structured evidence validation.")
        report["evidence_seconds"] = round(time.monotonic() - started, 2)
        report["evidence_passed"] = True
        started = time.monotonic()
        summary = foundry.summary(
            conversation_id, corpus, user_turns=["Wie viele Fahrzeuge umfasst der Pilot?"]
        )
        report["summary_seconds"] = round(time.monotonic() - started, 2)
        report["summary_schema_passed"] = True
        report["summary_source_count"] = len(summary.sources)
        print(json.dumps(report, indent=2), flush=True)
        state = ROOT / ".local"
        state.mkdir(exist_ok=True)
        (state / "model-check.json").write_text(json.dumps(report, indent=2) + "\n")
    finally:
        if conversation_id:
            foundry.delete_conversation(conversation_id)
            print("Diagnostic Foundry conversation deleted.", flush=True)
        foundry.client.close()
        foundry.project.close()


if __name__ == "__main__":
    try:
        main()
    except (ServiceError, TimeoutError) as error:
        print(f"Model compatibility probe failed: {error or 'Timed out'}", file=sys.stderr)
        raise SystemExit(1) from None
