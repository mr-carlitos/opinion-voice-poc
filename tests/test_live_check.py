import sys

import httpx
import pytest

from app.config import Settings
from app.graph import Folder, GraphHTTPError, ServiceError
from scripts import live_check


@pytest.fixture
def diagnostic(monkeypatch, tmp_path):
    settings = Settings(
        tenant_id="synthetic-tenant",
        graph_client_id="synthetic-client",
        input_url="https://demo.sharepoint.com/:f:/s/Demo/input-token",
        output_url="https://demo.sharepoint.com/:f:/s/Demo/output-token",
        project_endpoint="",
        agent_name="synthetic",
        model="synthetic",
        voice_endpoint="",
        voice_name="synthetic",
        voice_api_version="synthetic",
    )
    calls = []
    results = []

    class FakeAuth:
        def __init__(self, config):
            self.owner = None

        def authenticate(self):
            self.owner = {"id": "synthetic-user", "displayName": "Synthetic"}

    class FakeGraph:
        def __init__(self, auth):
            pass

        def resolve_folder(self, url, **kwargs):
            calls.append(url)
            result = results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(live_check.Settings, "load", lambda: settings)
    monkeypatch.setattr(live_check, "ConsoleAuth", FakeAuth)
    monkeypatch.setattr(live_check, "Graph", FakeGraph)
    monkeypatch.setattr(live_check, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["live_check.py", "--resolve-folders"])
    return settings, calls, results, tmp_path


def forbidden(code="accessDenied"):
    return GraphHTTPError(
        httpx.Response(
            403, headers={"request-id": "synthetic-request"}, json={"error": {"code": code}}
        )
    )


def test_readonly_diagnostic_checks_both_folders_and_exits_without_traceback(diagnostic, capsys):
    settings, calls, results, root = diagnostic
    results.extend([forbidden(), forbidden("insufficient_claims")])
    assert live_check.run() == 1
    captured = capsys.readouterr()
    assert "Sign-in and Graph profile lookup succeeded" in captured.out
    assert "Input folder failed: Graph HTTP 403 (accessDenied)" in captured.err
    assert "Output folder failed: Graph HTTP 403 (insufficient_claims)" in captured.err
    assert "Conditional Access" in captured.err
    assert "No document contents read or uploaded" in captured.err
    assert "Traceback" not in captured.err
    assert calls == [settings.input_url, settings.output_url]
    assert not (root / ".local").exists()


def test_failed_input_never_saves_partial_configuration(diagnostic, capsys):
    _, _, results, root = diagnostic
    results.extend(
        [
            forbidden(),
            Folder("drive", "out", "https://demo.sharepoint.com/sites/Demo/Documents/Output"),
        ]
    )
    assert live_check.run() == 1
    assert "Output folder metadata resolved" in capsys.readouterr().out
    assert not (root / ".local").exists()


def test_write_diagnostic_aborts_before_output_or_upload_on_input_denial(
    diagnostic, monkeypatch, capsys
):
    settings, calls, results, root = diagnostic
    monkeypatch.setattr(sys, "argv", ["live_check.py", "--upload-corpus", "--save-example"])
    results.append(forbidden())
    assert live_check.run() == 1
    assert calls == [settings.input_url]
    assert "Input folder failed" in capsys.readouterr().err
    assert not (root / ".local").exists()


def test_successful_metadata_check_has_no_corpus_or_upload_dependency(diagnostic):
    _, _, results, root = diagnostic
    results.extend(
        [
            Folder("drive", "in", "https://demo.sharepoint.com/sites/Demo/Documents/Input"),
            Folder("drive", "out", "https://demo.sharepoint.com/sites/Demo/Documents/Output"),
        ]
    )
    assert live_check.run() == 0
    assert (root / ".local/sharepoint-folders.json").exists()


def test_expected_service_failure_returns_nonzero_but_programming_errors_are_not_hidden(
    monkeypatch, capsys
):
    def service_failure():
        raise ServiceError("synthetic failure")

    monkeypatch.setattr(live_check, "main", service_failure)
    assert live_check.run() == 1
    assert "Live check failed: synthetic failure" in capsys.readouterr().err

    def bug():
        raise TypeError("programming defect")

    monkeypatch.setattr(live_check, "main", bug)
    with pytest.raises(TypeError, match="programming defect"):
        live_check.run()
