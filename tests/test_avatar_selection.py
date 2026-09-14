from dataclasses import replace

from app.config import Settings


def test_avatar_selection_is_configurable_without_changing_model(monkeypatch):
    monkeypatch.setenv("VOICE_NAME", "de-DE-ConradNeural")
    monkeypatch.setenv("VOICE_AVATAR_CHARACTER", "harry")
    monkeypatch.setenv("VOICE_AVATAR_STYLE", "casual")
    settings = Settings.load()
    assert settings.voice_name == "de-DE-ConradNeural"
    assert (settings.avatar_character, settings.avatar_style) == ("harry", "casual")
    assert not any("Bezeichnung" in issue for issue in settings.issues())


def test_avatar_identifiers_reject_arbitrary_urls_or_missing_character():
    settings = Settings("", "", "", "", "", "", "", "", "", "", avatar_enabled=True)
    for character in ("", "https://outside.example/person", "harry\ninjected"):
        issues = replace(settings, avatar_character=character).issues()
        assert any("VOICE_AVATAR_CHARACTER" in issue for issue in issues)
    assert any(
        "VOICE_AVATAR_STYLE" in issue
        for issue in replace(settings, avatar_style="../other").issues()
    )
