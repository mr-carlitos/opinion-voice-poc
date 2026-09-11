import pytest

from types import SimpleNamespace

from app.voice import cleanup_error_request, summary_requested, voice_session_settings


@pytest.mark.parametrize(
    "text",
    [
        "OK, jetzt Zusammenfassung erstellen.",
        "Okay, bitte meine Meinungsbildung zusammenfassen!",
        "Jetzt bitte die Zusammenfassung erstellen",
        "Erstelle eine Zusammenfassung",
        "Bitte zusammenfassen",
    ],
)
def test_affirmative_summary_commands(text):
    assert summary_requested(text)


@pytest.mark.parametrize(
    "text",
    [
        "Jetzt nicht zusammenfassen",
        "Keine Zusammenfassung erstellen",
        "Was bedeutet Zusammenfassung erstellen?",
        "Ja bitte speichern",
        "Er sagte Zusammenfassung erstellen",
        "Ich moechte noch keine Zusammenfassung",
    ],
)
def test_other_or_negative_commands_do_not_finish(text):
    assert not summary_requested(text)


def test_real_missing_item_error_without_event_id_matches_only_our_pending_cleanup():
    failure = {
        "code": "item_delete_invalid_item_id",
        "event_id": None,
        "message": "Error deleting item: the item with id 'old-item' does not exist.",
    }
    assert cleanup_error_request(failure, {"cleanup-1": "old-item"}) == "cleanup-1"
    assert cleanup_error_request(failure, {"cleanup-1": "different-item"}) is None
    assert cleanup_error_request(failure, {}) is None
    assert (
        cleanup_error_request({**failure, "event_id": "unrelated"}, {"cleanup-1": "old-item"})
        is None
    )
    assert cleanup_error_request({**failure, "code": "other"}, {"cleanup-1": "old-item"}) is None


def test_noisy_environment_vad_keeps_manual_response_control():
    settings = voice_session_settings(SimpleNamespace(voice_name="de-DE-KatjaNeural"))
    vad = settings["turn_detection"]
    assert vad["type"] == "azure_semantic_vad_multilingual"
    assert vad["threshold"] == 0.6
    assert vad["speech_duration_ms"] == 200
    assert vad["create_response"] is False and vad["interrupt_response"] is False
    assert settings["input_audio_noise_reduction"]["type"] == "azure_deep_noise_suppression"
