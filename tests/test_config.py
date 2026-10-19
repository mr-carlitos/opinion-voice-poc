from dataclasses import replace

import pytest

from app import config
from app.config import Settings, folder_reference, folder_url, validate_graph_id


@pytest.fixture
def settings():
    return Settings(
        tenant_id="synthetic-tenant",
        graph_client_id="synthetic-client",
        input_url="https://demo.sharepoint.com/sites/Demo/Docs/Input",
        output_url="https://demo.sharepoint.com/sites/Demo/Docs/Output",
        input_drive_id="drive",
        input_folder_id="input",
        output_drive_id="drive",
        output_folder_id="output",
        project_endpoint="https://demo.services.ai.azure.com/api/projects/demo",
        agent_name="synthetic",
        model="synthetic",
        voice_endpoint="https://demo.cognitiveservices.azure.com",
        voice_name="synthetic",
        voice_api_version="synthetic",
    )


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://demo.sharepoint.com/sites/Demo/Docs/%FF",
        "https://demo.sharepoint.com:invalid/sites/Demo/Docs/Input",
        "https://demo.sharepoint.com/sites/Demo/Docs/%",
        "https://demo.sharepoint.com/sites/Demo/Docs/%252e%252e",
    ],
)
def test_invalid_sharepoint_url_encodings_are_rejected(url):
    with pytest.raises(ValueError):
        folder_url(url)


@pytest.mark.parametrize("value", [".", "..", "", "a/b", "a?b", None])
def test_invalid_graph_ids(value):
    with pytest.raises(ValueError, match="Graph-Ordner-ID"):
        validate_graph_id(value)


@pytest.mark.parametrize(
    ("tail", "valid"),
    [
        ("r/sites/Demo/Docs/Input", True),
        ("g/personal/synthetic/token", True),
        ("t/Demo/token", True),
        ("unsupported/token", False),
        ("r/_layouts/test", False),
    ],
)
def test_supported_folder_sharing_link_shapes(tail, valid):
    url = "https://demo.sharepoint.com/:f:/" + tail
    if valid:
        reference = folder_reference(url)
        assert reference.sharing is True and reference.host == "demo.sharepoint.com"
    else:
        with pytest.raises(ValueError):
            folder_reference(url)


def test_sharing_links_cannot_be_combined_with_pinned_ids():
    with pytest.raises(ValueError, match="nicht mit Freigabelink"):
        folder_reference(
            "https://demo.sharepoint.com/:f:/s/Demo/token", drive_id="drive", item_id="item"
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://demo.services.ai.azure.com",
        "https://example.org",
        "https://demo.ai.azure.com.attacker.example",
        "******demo.services.ai.azure.com",
        "https://demo.services.ai.azure.com?token=synthetic",
        "https://demo.services.ai.azure.com#fragment",
    ],
)
def test_cloud_endpoints_require_azure_https_without_credentials_or_query(settings, endpoint):
    assert any(
        "Azure-HTTPS-Endpunkte" in issue
        for issue in replace(settings, project_endpoint=endpoint).issues()
    )


def test_missing_folder_url_still_reports_partial_pinned_ids(settings):
    issues = replace(settings, input_url="", input_folder_id="").folder_issues()
    assert any("SHAREPOINT_INPUT_FOLDER_URL fehlt" in issue for issue in issues)
    assert any("gemeinsam konfiguriert" in issue for issue in issues)


def test_settings_load_normalizes_environment_without_using_operator_dotenv(monkeypatch):
    load = []
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: load.append(kwargs))
    environment = {
        "FOUNDRY_PROJECT_ENDPOINT": "https://demo.services.ai.azure.com/api/projects/demo/",
        "VOICELIVE_ENDPOINT": "https://demo.cognitiveservices.azure.com/",
        "GRAPH_AUTH_MODE": " Application ",
        "VOICE_DELIVERY_MODE": " Streaming ",
        "VOICE_AVATAR_ENABLED": " TRUE ",
        "VOICE_AVATAR_CHARACTER": " harry ",
        "VOICE_AVATAR_STYLE": " casual ",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    loaded = Settings.load()
    assert loaded.project_endpoint.endswith("/demo")
    assert not loaded.voice_endpoint.endswith("/")
    assert loaded.graph_auth_mode == "application"
    assert loaded.voice_delivery_mode == "streaming"
    assert loaded.avatar_enabled is True
    assert (loaded.avatar_character, loaded.avatar_style) == ("harry", "casual")
    assert load == [{"override": False}]
