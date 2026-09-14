from types import SimpleNamespace

import pytest

from app.voice import cleanup_error_request, summary_requested, voice_session_settings


@pytest.mark.parametrize(
    "text",
    [
        "OK, jetzt Zusammenfassung erstellen.",
        "Okay, bitte meine Meinungsbildung zusammenfassen!",
        "Jetzt bitte die Zusammenfassung erstellen",
        "Erstelle eine Zusammenfassung",
        "Bitte zusammenfassen",
        "Ja, ist gut. Also eben OK. Jetzt Zusammenfassung erstellen "
        "und für diesen Entwurf so freigeben.",
        "Fasse unser Gespräch bitte zusammen",
        "Fasse unser Gespraech bitte zusammen!",
        "Ich möchte jetzt eine Zusammenfassung",
        "Ich moechte jetzt eine Zusammenfassung.",
        "Kannst du das bitte zusammenfassen?",
        "Okay! Also, kannst du bitte unser Gespräch zusammenfassen? Danke.",
        "Könnten Sie bitte eine Zusammenfassung erstellen?",
        "Ja, bitte die Zusammenfassung jetzt erstellen.",
        "Fasse unser Gespra\u0308ch bitte zusammen.",
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
        "Noch nicht zusammenfassen",
        "Wie erstellt man eine Zusammenfassung?",
        "Wenn ich fertig bin, bitte zusammenfassen",
        "Bitte zusammenfassen, wenn ich fertig bin",
        "Vielleicht jetzt Zusammenfassung erstellen",
        "Ich möchte jetzt eine Zusammenfassung, aber noch nicht erstellen",
        "Kannst du das bitte zusammenfassen, falls ich zustimme?",
        'Er sagte: "Bitte zusammenfassen".',
        "„Fasse unser Gespräch bitte zusammen“",
        "'Zusammenfassung erstellen'",
        "Die Worte Zusammenfassung erstellen sind ein Befehl",
        "Was bedeutet bitte zusammenfassen?",
        "Ich frage, ob du das zusammenfassen kannst",
        "Ich möchte wissen, wie man eine Zusammenfassung erstellt",
        "Angenommen, ich möchte jetzt eine Zusammenfassung",
        "Ja, ist gut. Also eben OK. Jetzt keine Zusammenfassung erstellen.",
        "Bitte zusammenfassen und sofort speichern",
        "Zusammenfassung erstellen und für diesen Entwurf nicht freigeben",
        "Nicht jetzt. Bitte zusammenfassen.",
        "Bitte zusammenfassen. Nein, doch nicht.",
        "zusammenfassender Bericht",
        "",
        "bitte " * 81 + "zusammenfassen",
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


@pytest.mark.parametrize(
    ("options", "character", "style"),
    [
        ({}, "lisa", "casual-sitting"),
        ({"avatar_character": "harry", "avatar_style": "casual"}, "harry", "casual"),
    ],
)
def test_voice_avatar_settings_use_configured_values_or_legacy_defaults(options, character, style):
    settings = SimpleNamespace(voice_name="voice", **options)
    assert voice_session_settings(settings, avatar=True)["avatar"] == {
        "character": character,
        "style": style,
        "customized": False,
    }
    assert "avatar" not in voice_session_settings(settings)
