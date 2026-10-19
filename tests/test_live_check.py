import json
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

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


@pytest.mark.parametrize(
    "flags",
    [
        ["--foundry-only", "--resolve-folders"],
        ["--foundry-only", "--save-example"],
        ["--resolve-folders", "--upload-corpus"],
    ],
)
def test_incompatible_live_flags_fail_before_authentication(diagnostic, monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", ["live_check.py", *flags])
    auth = Mock()
    monkeypatch.setattr(live_check, "GraphAuth", auth)
    monkeypatch.setattr(live_check, "ConsoleAuth", auth)
    with pytest.raises(SystemExit) as failure:
        live_check.main()
    assert failure.value.code == 2
    auth.assert_not_called()


@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_foundry_only_probe_is_offline_and_does_not_touch_sharepoint(
    diagnostic, monkeypatch, status
):
    settings, calls, _, _ = diagnostic
    settings = replace(settings, project_endpoint="https://demo.services.ai.azure.com")
    monkeypatch.setattr(live_check.Settings, "load", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["live_check.py", "--foundry-only"])
    foundry = Mock()
    foundry.configure_agent.return_value = "version-1"
    foundry.client.responses.create.return_value = SimpleNamespace(
        status=status, output_text="Synthetischer Gruss"
    )
    monkeypatch.setattr(live_check, "Foundry", Mock(return_value=foundry))
    assert live_check.run() == (0 if status == "completed" else 1)
    assert calls == []
    request = foundry.client.responses.create.call_args.kwargs
    assert request["store"] is False
    assert request["extra_body"]["agent_reference"]["version"] == "version-1"


@pytest.mark.parametrize("problem", ["foundry", "graph", "folders", "identity"])
def test_missing_live_configuration_stops_without_writes(diagnostic, monkeypatch, problem):
    settings, _, _, root = diagnostic
    if problem == "foundry":
        monkeypatch.setattr(sys, "argv", ["live_check.py", "--foundry-only"])
    elif problem == "graph":
        settings = replace(settings, tenant_id="")
    elif problem == "folders":
        settings = replace(settings, input_url="")
    else:
        auth = Mock(owner=None)
        auth.snapshot.return_value = {"message": "Synthetic sign-in failed"}
        monkeypatch.setattr(live_check, "ConsoleAuth", Mock(return_value=auth))
    monkeypatch.setattr(live_check.Settings, "load", lambda: settings)
    if problem == "identity":
        assert live_check.run() == 1
    else:
        with pytest.raises(SystemExit) as failure:
            live_check.main()
        assert failure.value.code == 2
    assert not (root / ".local").exists()


@pytest.fixture
def file_diagnostic(diagnostic, monkeypatch):
    settings, _, results, root = diagnostic
    source = Folder("drive", "in", "https://demo.sharepoint.com/sites/Demo/Docs/Input")
    output = Folder("drive", "out", "https://demo.sharepoint.com/sites/Demo/Docs/Output")
    results.extend([source, output])
    sample = root / "sample-data"
    (sample / "pdfs").mkdir(parents=True)
    (sample / "corpus-manifest.json").write_text(
        json.dumps({"documents": [{"document_id": "D01", "filename": "D01.pdf"}]})
    )
    (sample / "pdfs/D01.pdf").write_bytes(b"synthetic-pdf-upload")
    graph = Mock()
    graph.resolve_folder.side_effect = [source, output]
    stored = {}

    def upload(folder, filename, content):
        stored[filename] = content
        return {"id": filename, "size": len(content), "webUrl": folder.url + "/" + filename}

    graph.upload.side_effect = upload
    graph.download.side_effect = lambda folder, item: stored[item["id"]]
    monkeypatch.setattr(live_check, "Graph", Mock(return_value=graph))
    corpus = SimpleNamespace(context="30 Fahrzeuge", sources={"D01": None}, pages={"D01": 2})
    monkeypatch.setattr(live_check, "load_corpus", Mock(return_value=corpus))
    return settings, graph, root, stored


@pytest.mark.parametrize("mode", ["delegated", "application"])
@pytest.mark.parametrize("operation", ["read", "upload", "save", "both"])
def test_file_diagnostics_use_only_explicit_synthetic_operations(
    file_diagnostic, monkeypatch, mode, operation
):
    settings, graph, root, stored = file_diagnostic
    if mode == "application":
        settings = replace(settings, graph_auth_mode="application")
        monkeypatch.setattr(live_check.Settings, "load", lambda: settings)
        monkeypatch.setattr(settings.__class__, "graph_issues", lambda self: [])
        auth = Mock(owner={"id": "synthetic-application", "displayName": "Synthetic app"})
        monkeypatch.setattr(live_check, "GraphAuth", Mock(return_value=auth))
    flags = []
    if operation in ("upload", "both"):
        flags.append("--upload-corpus")
    if operation in ("save", "both"):
        flags.append("--save-example")
    monkeypatch.setattr(sys, "argv", ["live_check.py", *flags])
    assert live_check.run() == 0
    assert set(stored) == (
        ({"D01.pdf"} if operation in ("upload", "both") else set())
        | ({"poc-smoke-summary.docx"} if operation in ("save", "both") else set())
    )
    assert live_check.load_corpus.call_count == (0 if operation == "save" else 1)
    assert graph.download.call_count == (1 if operation in ("save", "both") else 0)
    assert (root / ".local/sharepoint-folders.json").exists()
    if operation in ("save", "both"):
        evidence = json.loads((root / ".local/smoke-item.json").read_text())
        assert evidence["authored_package_content_verified"] is True
        assert evidence["exact_bytes_equal"] is True


def test_read_probe_fails_when_distinctive_corpus_fact_is_missing(file_diagnostic, monkeypatch):
    live_check.load_corpus.return_value.context = "No expected fact"
    monkeypatch.setattr(sys, "argv", ["live_check.py"])
    assert live_check.run() == 1


@pytest.mark.parametrize("failure", ["content", "headings"])
def test_word_probe_does_not_report_success_for_invalid_downloads(
    file_diagnostic, monkeypatch, failure
):
    _, graph, root, _ = file_diagnostic
    monkeypatch.setattr(sys, "argv", ["live_check.py", "--save-example"])
    if failure == "content":
        graph.download.side_effect = None
        graph.download.return_value = b"not the approved Word document"
    else:
        from io import BytesIO

        from docx import Document

        document = Document()
        document.add_paragraph("Missing required headings")
        buffer = BytesIO()
        document.save(buffer)
        (root / ".local").mkdir()
        (root / ".local/smoke-summary.docx").write_bytes(buffer.getvalue())
    assert live_check.run() == 1
    assert not (root / ".local/smoke-item.json").exists()
