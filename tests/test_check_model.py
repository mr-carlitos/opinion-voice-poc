import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.graph import Folder, ServiceError
from app.grounding import Corpus
from scripts import check_model


class VoiceConnection:
    def __init__(self, events):
        self.events = events
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def send(self, message):
        self.sent.append(message)

    def __aiter__(self):
        async def iterate():
            for event in self.events:
                yield SimpleNamespace(as_dict=lambda event=event: event)

        return iterate()


@pytest.fixture
def model_probe(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        issues=lambda: [],
        tenant_id="synthetic",
        model="synthetic-model",
        voice_endpoint="synthetic-endpoint",
        voice_api_version="synthetic",
        agent_name="synthetic-agent",
        project_endpoint="https://demo.services.ai.azure.com/api/projects/synthetic",
        voice_name="synthetic-voice",
        input_url="synthetic-input",
        input_drive_id="drive",
        input_folder_id="input",
        output_url="synthetic-output",
        output_drive_id="drive",
        output_folder_id="output",
    )
    auth = Mock(owner={"id": "synthetic", "displayName": "Synthetic"})
    graph = Mock()
    graph.resolve_folder.side_effect = [
        Folder("drive", "input", "https://demo.sharepoint.com/sites/Demo/Docs/Input"),
        Folder("drive", "output", "https://demo.sharepoint.com/sites/Demo/Docs/Output"),
    ]
    foundry = Mock(version="1")
    foundry.configure_agent.return_value = "1"
    foundry.create_conversation.return_value = "owned-conversation"
    foundry.verify_answer.return_value = SimpleNamespace(supported=True, sources=["D01"])
    foundry.summary.return_value = SimpleNamespace(sources=["D01"])
    monkeypatch.setattr(check_model.Settings, "load", lambda: settings)
    monkeypatch.setattr(check_model, "GraphAuth", Mock(return_value=auth))
    monkeypatch.setattr(check_model, "Graph", Mock(return_value=graph))
    monkeypatch.setattr(check_model, "Foundry", Mock(return_value=foundry))
    monkeypatch.setattr(check_model, "load_corpus", Mock(return_value=Corpus("[]", {}, {}, {})))
    monkeypatch.setattr(check_model, "ROOT", tmp_path)
    return settings, auth, foundry, tmp_path


@pytest.mark.parametrize(
    "text_kind",
    [
        "response.audio_transcript.delta",
        "response.text.delta",
        "response.output_audio_transcript.delta",
        "response.output_text.delta",
        "fallback",
    ],
)
def test_voice_probe_accepts_supported_event_shapes_without_duplicate_initialization(
    model_probe, monkeypatch, text_kind
):
    settings, _, foundry, _ = model_probe
    events = [
        {"type": "session.updated"},
        {"type": "session.updated"},
        {"type": "response.audio.delta", "delta": "AAAA"},
        {"type": "response.output_audio.delta", "delta": "AAAA"},
    ]
    if text_kind != "fallback":
        events.append({"type": text_kind, "delta": "30 Fahrzeuge"})
    events.append(
        {
            "type": "response.done",
            "response": {
                "status": "completed",
                "output": [{"content": [{"transcript": "30 Fahrzeuge"}]}],
            },
        }
    )
    upstream = VoiceConnection(events)
    connect = Mock(return_value=upstream)
    monkeypatch.setattr(check_model, "connect", connect)
    monkeypatch.setattr(check_model, "AzureCliCredential", Mock(return_value=VoiceConnection([])))
    result, text = asyncio.run(check_model.voice_probe(settings, foundry, "owned-conversation"))
    assert text == "30 Fahrzeuge"
    assert result["audio_chunks"] == 2
    assert result["audio_base64_characters"] == 8
    assert result["first_audio_seconds"] >= 0
    assert [message["type"] for message in upstream.sent] == [
        "session.update",
        "conversation.item.create",
        "response.create",
    ]
    assert connect.call_args.kwargs["conversation_id"] == "owned-conversation"
    assert upstream.sent[0]["session"]["input_audio_sampling_rate"] == 24000


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([{"type": "error", "error": {"code": "synthetic"}}], "synthetic"),
        ([{"type": "response.done", "response": {"status": "failed"}}], "did not complete"),
        (
            [{"type": "response.done", "response": {"status": "completed"}}],
            "audio and the corpus fact",
        ),
        (
            [
                {"type": "response.audio.delta", "delta": "AAAA"},
                {"type": "response.text.delta", "delta": "incorrect answer"},
                {"type": "response.done", "response": {"status": "completed"}},
            ],
            "audio and the corpus fact",
        ),
        ([], "without a completed response"),
    ],
)
def test_voice_probe_rejects_incomplete_or_factless_responses(
    model_probe, monkeypatch, events, message
):
    settings, _, foundry, _ = model_probe
    monkeypatch.setattr(check_model, "connect", Mock(return_value=VoiceConnection(events)))
    monkeypatch.setattr(check_model, "AzureCliCredential", Mock(return_value=VoiceConnection([])))
    with pytest.raises(ServiceError, match=message):
        asyncio.run(check_model.voice_probe(settings, foundry, "owned-conversation"))


@pytest.mark.parametrize("failure", [None, "voice", "evidence", "summary", "conversation"])
def test_model_check_report_and_cleanup_are_offline_and_failure_safe(
    model_probe, monkeypatch, failure
):
    _, _, foundry, root = model_probe
    probe = AsyncMock(return_value=({"audio_chunks": 1}, "30 Fahrzeuge"))
    monkeypatch.setattr(check_model, "voice_probe", probe)
    if failure == "voice":
        probe.side_effect = ServiceError("Synthetic voice failure")
    elif failure == "evidence":
        foundry.verify_answer.return_value.supported = False
    elif failure == "summary":
        foundry.summary.side_effect = ServiceError("Synthetic summary failure")
    elif failure == "conversation":
        foundry.create_conversation.side_effect = ServiceError("Synthetic creation failure")
    if failure:
        with pytest.raises(ServiceError):
            check_model.main()
        assert not (root / ".local/model-check.json").exists()
    else:
        check_model.main()
        report = json.loads((root / ".local/model-check.json").read_text())
        assert report["evidence_passed"] is True
        assert report["summary_schema_passed"] is True
        assert report["microphone_tested"] is False
        assert report["browser_playback_tested"] is False
    if failure == "conversation":
        foundry.delete_conversation.assert_not_called()
    else:
        foundry.delete_conversation.assert_called_once_with("owned-conversation")
    foundry.client.close.assert_called_once()
    foundry.project.close.assert_called_once()


@pytest.mark.parametrize("failure", ["config", "identity"])
def test_model_check_fails_before_model_creation_when_not_ready(model_probe, failure):
    settings, auth, _, _ = model_probe
    if failure == "config":
        settings.issues = lambda: ["Synthetic configuration missing"]
    else:
        auth.owner = None
        auth.snapshot.return_value = {"message": "Synthetic identity missing"}
    with pytest.raises(ServiceError, match="Synthetic"):
        check_model.main()
    check_model.Foundry.assert_not_called()
