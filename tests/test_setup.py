import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.graph_permissions import GRAPH_SCOPES
from scripts import setup_m365

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("key", "quota", "success", "message"),
    [
        (
            "OpenAI.Standard.gpt-5.1",
            [{"limit": 5000.0, "used": 0.0}],
            True,
            "available 5000, requested 100",
        ),
        ("", [], False, "quota key is missing or ambiguous"),
        ("first\nsecond", [], False, "quota key is missing or ambiguous"),
        ("key", [], False, "Quota is missing or ambiguous"),
        ("key", [{"limit": 100, "used": 1}], False, "Insufficient quota"),
        ("key", [{"limit": 100, "used": 0}], True, "available 100, requested 100"),
        ("key", [{"limit": None, "used": 0}], False, "Invalid quota values"),
        ("key", [{"limit": "5000", "used": 0}], False, "Invalid quota values"),
    ],
)
def test_provision_preflight_uses_catalog_key(tmp_path, key, quota, success, message):
    fake_az = tmp_path / "az"
    fake_az.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:3] == ['cognitiveservices', 'model', 'list']:\n"
        "    assert 'usageName' in args[args.index('--query') + 1]\n"
        "    print(os.environ['TEST_USAGE_KEY'])\n"
        "elif args[:3] == ['cognitiveservices', 'usage', 'list']:\n"
        "    assert os.environ['TEST_USAGE_KEY'] in args[args.index('--query') + 1]\n"
        "    print(os.environ['TEST_QUOTA'])\n"
        "elif args[0] == 'account':\n"
        "    print('{}')\n"
        "else:\n"
        "    sys.exit('Unexpected cloud write or command: ' + str(args))\n"
    )
    fake_az.chmod(0o700)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/provision.sh")],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "TEST_USAGE_KEY": key,
            "TEST_QUOTA": json.dumps(quota),
            "FOUNDRY_DEPLOYMENT_SKU": "Standard",
            "FOUNDRY_DEPLOYMENT_CAPACITY": "100",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is success
    assert message in result.stdout + result.stderr


def test_global_deployment_is_rejected_before_any_azure_call():
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/provision.sh"), "--apply"],
        env={**os.environ, "FOUNDRY_DEPLOYMENT_SKU": "GlobalStandard"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "no global fallback" in result.stderr


def test_permission_request_contains_only_two_delegated_scopes():
    assert setup_m365.SCOPES is GRAPH_SCOPES
    assert GRAPH_SCOPES == ("User.Read", "Files.ReadWrite")
    scopes = [
        {"value": name, "id": f"scope-{index}", "isEnabled": True}
        for index, name in enumerate(setup_m365.SCOPES)
    ]
    request = setup_m365.permission_request(scopes)
    assert request == [
        {
            "resourceAppId": setup_m365.GRAPH_APP_ID,
            "resourceAccess": [{"id": f"scope-{index}", "type": "Scope"} for index in range(2)],
        }
    ]
    scopes[0]["isEnabled"] = False
    with pytest.raises(setup_m365.SetupError, match="enabled delegated"):
        setup_m365.permission_request(scopes)


def test_reusing_registration_rejects_unknown_owners_secrets_or_permissions():
    required = [
        {
            "resourceAppId": setup_m365.GRAPH_APP_ID,
            "resourceAccess": [
                {"id": "scope-1", "type": "Scope"},
            ],
        }
    ]
    app = {
        "displayName": setup_m365.APP_NAME,
        "serviceManagementReference": setup_m365.OWNER_MARKER,
        "signInAudience": "AzureADMyOrg",
        "isFallbackPublicClient": True,
        "passwordCredentials": [],
        "keyCredentials": [],
        "requiredResourceAccess": required,
    }
    setup_m365.validate_app(app, required)
    for change in [
        {"serviceManagementReference": None},
        {"isFallbackPublicClient": False},
        {"passwordCredentials": [{"keyId": "unexpected"}]},
        {"signInAudience": "AzureADMultipleOrgs"},
        {"requiredResourceAccess": []},
    ]:
        with pytest.raises(setup_m365.SetupError):
            setup_m365.validate_app({**app, **change}, required)


def test_registration_preflight_never_creates_or_grants_consent(monkeypatch, capsys):
    commands = []

    def azure(*args):
        commands.append(args)
        if args == ("account", "show"):
            return {"tenantId": "demo-tenant"}
        if args[:3] == ("ad", "sp", "show"):
            return {
                "oauth2PermissionScopes": [
                    {"value": name, "id": name, "isEnabled": True} for name in setup_m365.SCOPES
                ]
            }
        if args[:3] == ("ad", "app", "list"):
            return []
        pytest.fail(f"Unexpected command: {args}")

    monkeypatch.setattr(setup_m365, "azure", azure)
    setup_m365.setup("demo-tenant", False)
    assert "Would create" in capsys.readouterr().out
    assert len(commands) == 3


@pytest.fixture
def legacy_registration(monkeypatch, tmp_path):
    scopes = [
        {"value": name, "id": name, "isEnabled": True}
        for name in dict.fromkeys((*GRAPH_SCOPES, *setup_m365.LEGACY_SCOPES))
    ]
    app = {
        "id": "owned-app-object",
        "appId": "owned-app-client",
        "displayName": setup_m365.APP_NAME,
        "serviceManagementReference": setup_m365.OWNER_MARKER,
        "signInAudience": "AzureADMyOrg",
        "isFallbackPublicClient": True,
        "requiredResourceAccess": setup_m365.permission_request(scopes, setup_m365.LEGACY_SCOPES),
    }
    commands = []
    grants = []

    def azure(*args):
        commands.append(args)
        if args == ("account", "show"):
            return {"tenantId": "demo-tenant"}
        if args[:3] == ("ad", "sp", "show"):
            return {"id": "graph-resource", "oauth2PermissionScopes": scopes}
        if args[:3] == ("ad", "app", "list"):
            return [app]
        if args[:3] == ("ad", "sp", "list"):
            return [{"id": "owned-principal"}]
        if args[:3] == ("ad", "app", "update"):
            app["requiredResourceAccess"] = json.loads(
                args[args.index("--required-resource-accesses") + 1]
            )
            return None
        if args[:3] == ("ad", "app", "show"):
            return app
        if args[:3] == ("rest", "--method", "get"):
            return {"value": grants if "oauth2PermissionGrants" in args[-1] else []}
        pytest.fail(f"Unexpected command: {args}")

    monkeypatch.setattr(setup_m365, "ROOT", tmp_path)
    monkeypatch.setattr(setup_m365, "azure", azure)
    return app, commands, grants


def test_legacy_migration_requires_explicit_flag(legacy_registration):
    _, commands, _ = legacy_registration
    with pytest.raises(setup_m365.SetupError, match="--narrow-permissions"):
        setup_m365.setup("demo-tenant", True)
    assert not any(command[:3] == ("ad", "app", "update") for command in commands)


def test_legacy_migration_plan_does_not_change_permissions(legacy_registration, capsys):
    _, commands, _ = legacy_registration
    setup_m365.setup("demo-tenant", False)
    assert "Would replace" in capsys.readouterr().out
    assert not any(command[:3] == ("ad", "app", "update") for command in commands)


def test_legacy_migration_removes_all_scopes_without_granting_consent(
    legacy_registration, tmp_path
):
    app, commands, _ = legacy_registration
    setup_m365.setup("demo-tenant", True, narrow_permissions=True)
    assert app["requiredResourceAccess"] == [
        {
            "resourceAppId": setup_m365.GRAPH_APP_ID,
            "resourceAccess": [{"id": name, "type": "Scope"} for name in GRAPH_SCOPES],
        }
    ]
    state = json.loads((tmp_path / ".local/m365-app.json").read_text())
    assert state["requested_delegated_scopes"] == list(GRAPH_SCOPES)
    assert state["admin_consent_granted_by_script"] is False
    assert state["existing_delegated_grants"] == []
    setup_m365.setup("demo-tenant", True, narrow_permissions=True)
    assert sum(command[:3] == ("ad", "app", "update") for command in commands) == 1
    assert not any("admin-consent" in command for command in commands)
    assert all(command[2] == "get" for command in commands if command[0] == "rest")


@pytest.mark.parametrize(
    "change",
    [
        {"serviceManagementReference": "another-owner"},
        {
            "requiredResourceAccess": [
                {
                    "resourceAppId": setup_m365.GRAPH_APP_ID,
                    "resourceAccess": [{"id": "unrelated-scope", "type": "Scope"}],
                }
            ]
        },
    ],
)
def test_migration_does_not_overwrite_unexpected_registration(legacy_registration, change):
    app, commands, _ = legacy_registration
    app.update(change)
    with pytest.raises(setup_m365.SetupError):
        setup_m365.setup("demo-tenant", True, narrow_permissions=True)
    assert not any(command[:3] == ("ad", "app", "update") for command in commands)


def test_migration_refuses_to_ignore_existing_broad_consent(legacy_registration):
    _, commands, grants = legacy_registration
    grants.append(
        {
            "scope": "User.Read Sites.Read.All Files.ReadWrite.All",
            "resourceId": "graph-resource",
            "consentType": "Principal",
        }
    )
    with pytest.raises(setup_m365.SetupError, match="Broader consent grants"):
        setup_m365.setup("demo-tenant", True, narrow_permissions=True)
    assert not any(command[:3] == ("ad", "app", "update") for command in commands)


def test_permission_review_checks_later_pages(monkeypatch):
    pages = iter(
        [
            {"value": [], "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"},
            {
                "value": [
                    {
                        "scope": "Files.ReadWrite.All",
                        "resourceId": "graph-resource",
                    }
                ]
            },
            {"value": []},
        ]
    )
    monkeypatch.setattr(setup_m365, "azure", lambda *args: next(pages))
    with pytest.raises(setup_m365.SetupError, match="Broader consent grants"):
        setup_m365.review_grants("owned-principal", "graph-resource")


def test_permission_review_rejects_app_only_access(monkeypatch):
    pages = iter([{"value": []}, {"value": [{"appRoleId": "application-permission"}]}])
    monkeypatch.setattr(setup_m365, "azure", lambda *args: next(pages))
    with pytest.raises(setup_m365.SetupError, match="app-only permissions"):
        setup_m365.review_grants("owned-principal", "graph-resource")


@pytest.mark.parametrize("result", ['{"id":"synthetic"}', "", "failure"])
def test_azure_cli_wrapper_checks_exit_status_and_json(monkeypatch, result):
    run = Mock(
        return_value=SimpleNamespace(
            returncode=1 if result == "failure" else 0,
            stdout=result if result != "failure" else "",
            stderr="Synthetic CLI failure",
        )
    )
    monkeypatch.setattr(setup_m365.subprocess, "run", run)
    if result == "failure":
        with pytest.raises(setup_m365.SetupError, match="Synthetic CLI failure"):
            setup_m365.azure("account", "show")
    else:
        assert setup_m365.azure("account", "show") == ({"id": "synthetic"} if result else None)
    assert run.call_args.args[0] == [
        "az",
        "account",
        "show",
        "--output",
        "json",
        "--only-show-errors",
    ]
    assert run.call_args.kwargs["check"] is False


@pytest.mark.parametrize(
    "url",
    [
        "http://graph.microsoft.com/v1.0/items",
        "https://outside.example/v1.0/items",
        "https://graph.microsoft.com/beta/items",
        "https://graph.microsoft.com/v1.0/items#fragment",
    ],
)
def test_permission_review_rejects_untrusted_pagination_before_cli(monkeypatch, url):
    azure = Mock()
    monkeypatch.setattr(setup_m365, "azure", azure)
    with pytest.raises(setup_m365.SetupError, match="Invalid or excessive"):
        setup_m365.graph_collection(url)
    azure.assert_not_called()


@pytest.mark.parametrize("body", [[], {}, {"value": "not-a-list"}, "cycle"])
def test_permission_review_fails_on_malformed_or_cyclic_graph_pages(monkeypatch, body):
    url = "https://graph.microsoft.com/v1.0/items"
    if body == "cycle":
        body = {"value": [], "@odata.nextLink": url}
    azure = Mock(return_value=body)
    monkeypatch.setattr(setup_m365, "azure", azure)
    with pytest.raises(setup_m365.SetupError):
        setup_m365.graph_collection(url)
    assert azure.call_count == 1


def test_setup_rejects_wrong_tenant_before_registration_or_permissions(monkeypatch):
    azure = Mock(return_value={"tenantId": "other-tenant"})
    monkeypatch.setattr(setup_m365, "azure", azure)
    with pytest.raises(setup_m365.SetupError, match="different tenant"):
        setup_m365.setup("expected-tenant", True)
    azure.assert_called_once_with("account", "show")


def test_apply_creates_only_owned_public_registration_and_principal(monkeypatch, tmp_path):
    scopes = [{"value": name, "id": name, "isEnabled": True} for name in GRAPH_SCOPES]
    required = setup_m365.permission_request(scopes)
    app = {
        "id": "synthetic-object",
        "appId": "synthetic-client",
        "displayName": setup_m365.APP_NAME,
        "serviceManagementReference": setup_m365.OWNER_MARKER,
        "signInAudience": "AzureADMyOrg",
        "isFallbackPublicClient": True,
        "requiredResourceAccess": required,
    }
    commands = []

    def azure(*args):
        commands.append(args)
        if args == ("account", "show"):
            return {"tenantId": "SYNTHETIC-TENANT"}
        if args[:3] == ("ad", "sp", "show"):
            return {"id": "graph-resource", "oauth2PermissionScopes": scopes}
        if args[:3] in (("ad", "app", "list"), ("ad", "sp", "list")):
            return []
        if args[:3] == ("ad", "app", "create"):
            assert json.loads(args[args.index("--required-resource-accesses") + 1]) == required
            return app
        if args[:3] == ("ad", "sp", "create"):
            return {"id": "synthetic-principal"}
        pytest.fail(f"Unexpected cloud operation: {args}")

    monkeypatch.setattr(setup_m365, "azure", azure)
    monkeypatch.setattr(setup_m365, "ROOT", tmp_path)
    setup_m365.setup("synthetic-tenant", True)
    path = tmp_path / ".local/m365-app.json"
    state = json.loads(path.read_text())
    assert state["service_principal_id"] == "synthetic-principal"
    assert state["admin_consent_granted_by_script"] is False
    assert path.stat().st_mode & 0o777 == 0o600
    assert not any("consent" in argument for command in commands for argument in command)


@pytest.mark.parametrize("error", [None, setup_m365.SetupError("Synthetic setup failure")])
def test_setup_cli_passes_explicit_flags_and_reports_expected_errors(monkeypatch, capsys, error):
    setup = Mock(side_effect=error)
    monkeypatch.setattr(setup_m365, "setup", setup)
    monkeypatch.setattr(
        sys,
        "argv",
        ["setup_m365.py", "--tenant-id", "synthetic", "--apply", "--narrow-permissions"],
    )
    if error:
        with pytest.raises(SystemExit) as failure:
            setup_m365.main()
        assert failure.value.code == 1
        assert "Synthetic setup failure" in capsys.readouterr().err
    else:
        setup_m365.main()
    setup.assert_called_once_with("synthetic", True, True)
