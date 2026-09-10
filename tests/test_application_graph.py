from dataclasses import replace
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ClientAuthenticationError

from app import config
from app import graph as graph_module
from app.config import Settings
from app.graph import Graph, GraphAuth, ServiceError
from app.graph_permissions import GRAPH_APPLICATION_SCOPE

TENANT = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / ".env.application").write_text(
        f"GRAPH_TENANT_ID={TENANT}\n"
        f"GRAPH_APP_CLIENT_ID={CLIENT}\n"
        "GRAPH_APP_CLIENT_SECRET=synthetic-secret\n"
        "FOUNDRY_PROJECT_ENDPOINT=https://must-not-override.example/\n"
    )
    return Settings(
        tenant_id=TENANT,
        graph_client_id="",
        input_url="https://demo.sharepoint.com/sites/Demo/Documents/Input",
        output_url="https://demo.sharepoint.com/sites/Demo/Documents/Output",
        project_endpoint="https://demo.services.ai.azure.com/api/projects/demo",
        agent_name="demo",
        model="demo",
        voice_endpoint="https://demo.services.ai.azure.com",
        voice_name="demo",
        voice_api_version="demo",
        input_drive_id="drive",
        input_folder_id="input",
        output_drive_id="drive",
        output_folder_id="output",
        graph_auth_mode="application",
        graph_application_credentials_file=".env.application",
    )


def test_application_credentials_are_explicit_and_do_not_override_environment(
    settings, monkeypatch
):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "unchanged")
    credentials = settings.application_credentials()
    assert credentials.tenant_id == TENANT
    assert credentials.client_id == CLIENT
    assert credentials.secret == "synthetic-secret"
    assert "synthetic-secret" not in repr(credentials)
    assert config.os.environ["FOUNDRY_PROJECT_ENDPOINT"] == "unchanged"
    assert settings.issues() == []
    assert replace(settings, graph_auth_mode="delegated").graph_issues() == [
        "GRAPH_CLIENT_ID fehlt"
    ]
    assert replace(settings, graph_auth_mode="automatic").graph_issues()


@pytest.mark.parametrize(
    "content",
    [
        f"GRAPH_TENANT_ID={TENANT}\nGRAPH_APP_CLIENT_ID={CLIENT}\n",
        f"GRAPH_TENANT_ID=33333333-3333-4333-8333-333333333333\n"
        f"GRAPH_APP_CLIENT_ID={CLIENT}\nGRAPH_APP_CLIENT_SECRET=synthetic-secret\n",
        f"GRAPH_TENANT_ID={TENANT}\nGRAPH_APP_CLIENT_ID=not-an-id\n"
        "GRAPH_APP_CLIENT_SECRET=synthetic-secret\n",
    ],
)
def test_invalid_or_wrong_tenant_credentials_fail_without_revealing_secret(settings, content):
    settings.application_credentials_path().write_text(content)
    with pytest.raises(ValueError) as caught:
        settings.application_credentials()
    assert "synthetic-secret" not in str(caught.value)


def test_missing_or_outside_project_credential_file_is_rejected(settings, tmp_path):
    assert replace(settings, graph_application_credentials_file="").graph_issues()
    assert replace(settings, graph_application_credentials_file="missing.env").graph_issues()
    assert replace(
        settings, graph_application_credentials_file=str(tmp_path.parent / "outside.env")
    ).graph_issues()


def test_application_auth_uses_default_scope_without_device_flow_or_me(settings, monkeypatch):
    calls = []

    class Credential:
        def __init__(self, tenant_id, client_id, secret):
            assert (tenant_id, client_id, secret) == (TENANT, CLIENT, "synthetic-secret")

        def get_token(self, *scopes):
            calls.append(scopes)
            return SimpleNamespace(token="synthetic-token")

        def close(self):
            pass

    monkeypatch.setattr(graph_module, "ClientSecretCredential", Credential)
    monkeypatch.setattr(
        graph_module,
        "DeviceCodeCredential",
        lambda **kwargs: pytest.fail("Application mode must not create a device credential"),
    )
    monkeypatch.setattr(
        Graph, "request", lambda *args: pytest.fail("Application identity must not call /me")
    )
    auth = GraphAuth(settings)
    with pytest.raises(ServiceError):
        auth.token()
    auth.authenticate()
    assert auth.snapshot() == {
        "mode": "application",
        "status": "signed_in",
        "name": "Lokale Demo (Anwendungsidentitaet)",
    }
    assert auth.owner["id"] == f"application:{TENANT}:{CLIENT}"
    assert auth.token() == "synthetic-token"
    assert calls == [(GRAPH_APPLICATION_SCOPE,), (GRAPH_APPLICATION_SCOPE,)]
    assert auth.start() == auth.snapshot()


def test_failed_application_auth_never_falls_back_and_clears_owner(settings, monkeypatch, caplog):
    class Credential:
        def __init__(self, *args):
            pass

        def get_token(self, *args):
            raise ClientAuthenticationError(message="synthetic-secret AADSTS7000215 invalid")

    monkeypatch.setattr(graph_module, "ClientSecretCredential", Credential)
    monkeypatch.setattr(
        graph_module,
        "DeviceCodeCredential",
        lambda **kwargs: pytest.fail("Do not fall back to delegated or CLI credentials"),
    )
    auth = GraphAuth(settings)
    auth.owner = {"id": "previous", "displayName": "Previous"}
    auth.authenticate()
    state = auth.snapshot()
    assert state["status"] == "error"
    assert state["mode"] == "application"
    assert "AADSTS7000215" in state["message"]
    assert auth.owner is None
    assert "synthetic-secret" not in str(state) + caplog.text
