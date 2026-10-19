import base64
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app import graph as graph_module
from app.config import Settings, folder_reference
from app.graph import (
    Folder,
    Graph,
    GraphAuth,
    GraphHTTPError,
    ServiceError,
    ensure_separate_folders,
)
from app.graph_permissions import GRAPH_SCOPES

SHARING_URL = "https://demo.sharepoint.com/:f:/s/Demo/synthetic-token?e=demo"
CANONICAL_URL = "https://demo.sharepoint.com/sites/Demo/Documents/Input"
ITEM = {
    "id": "01INPUT",
    "folder": {},
    "parentReference": {"driveId": "b!synthetic"},
    "webUrl": CANONICAL_URL,
}


@pytest.fixture
def settings():
    return Settings(
        tenant_id="demo-tenant",
        graph_client_id="demo-client",
        input_url=SHARING_URL,
        output_url="https://demo.sharepoint.com/:f:/s/Demo/output-token?e=demo",
        project_endpoint="https://demo.services.ai.azure.com/api/projects/demo",
        agent_name="demo",
        model="demo",
        voice_endpoint="https://demo.services.ai.azure.com",
        voice_name="demo",
        voice_api_version="demo",
    )


@pytest.fixture
def graph(monkeypatch):
    client_type = httpx.Client
    calls = []
    responses = []

    def handle(request):
        calls.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return (
            response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)
        )

    monkeypatch.setattr(
        graph_module.httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs),
    )
    return Graph(SimpleNamespace(token=lambda: "synthetic-token")), calls, responses


def test_sharing_resolution_uses_narrow_token_without_redemption(graph):
    client, calls, responses = graph
    responses.append(ITEM)
    folder = client.resolve_folder(SHARING_URL)
    encoded = base64.urlsafe_b64encode(SHARING_URL.encode()).decode().rstrip("=")
    assert folder == Folder("b!synthetic", "01INPUT", CANONICAL_URL)
    assert calls[0].url.path == f"/v1.0/shares/u!{encoded}/driveItem"
    assert calls[0].headers["authorization"] == "Bearer synthetic-token"
    assert "prefer" not in calls[0].headers


def test_pinned_folder_uses_item_endpoint_without_site_discovery(graph):
    client, calls, responses = graph
    responses.append(ITEM)
    assert (
        client.resolve_folder(CANONICAL_URL, drive_id="b!synthetic", item_id="01INPUT").url
        == CANONICAL_URL
    )
    assert calls[0].url.path == "/v1.0/drives/b!synthetic/items/01INPUT"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"folder": None, "file": {}},
        {"remoteItem": {}},
        {"parentReference": {}},
        {"webUrl": "https://outside.sharepoint.com/sites/Demo/Documents/Input"},
        {"webUrl": "https://demo.sharepoint.com/sites/Demo/Documents/Input?token=secret"},
        {"id": "../outside"},
    ],
)
def test_resolution_rejects_invalid_graph_folder_metadata(graph, changes):
    client, _, responses = graph
    responses.append({**ITEM, **changes})
    with pytest.raises(ServiceError):
        client.resolve_folder(SHARING_URL)


def test_pinned_folder_must_match_configured_path_and_ids(graph):
    client, _, responses = graph
    responses.append({**ITEM, "webUrl": CANONICAL_URL + "/different"})
    with pytest.raises(ServiceError, match="stimmt nicht"):
        client.resolve_folder(CANONICAL_URL, drive_id="b!synthetic", item_id="01INPUT")


@pytest.mark.parametrize(
    "url",
    [
        "http://demo.sharepoint.com/:f:/s/Demo/token",
        "https://demo.sharepoint.com.evil.example/:f:/s/Demo/token",
        "https://user@demo.sharepoint.com/:f:/s/Demo/token",
        "https://demo.sharepoint.com/:f:/s/Demo/token#fragment",
        "https://demo.sharepoint.com/:f:/s/Demo/../token",
        "https://demo.sharepoint.com/sites/Demo/Forms/AllItems.aspx?id=Input",
        "https://demo.sharepoint.com/:x:/s/Demo/token",
    ],
)
def test_invalid_folder_references_are_rejected(url):
    with pytest.raises(ValueError):
        folder_reference(url)


def test_configuration_requires_both_pinned_ids_and_checks_each_url(settings):
    assert settings.issues() == []
    assert replace(settings, input_url=CANONICAL_URL).folder_issues()
    assert replace(settings, input_drive_id="b!synthetic").folder_issues()
    assert replace(settings, output_url="invalid").folder_issues()
    assert replace(settings, output_url=SHARING_URL).folder_issues()
    pinned = replace(
        settings,
        input_url=CANONICAL_URL,
        input_drive_id="b!synthetic",
        input_folder_id="01INPUT",
    )
    assert pinned.folder_issues() == []


@pytest.mark.parametrize("reversed_order", [False, True])
def test_resolved_folder_overlap_is_rejected_in_either_direction(reversed_order):
    parent = Folder("drive", "parent", CANONICAL_URL)
    child = Folder("drive", "child", CANONICAL_URL + "/Output")
    with pytest.raises(ServiceError, match="ueberlappen"):
        ensure_separate_folders(*(child, parent) if reversed_order else (parent, child))
    ensure_separate_folders(parent, Folder("drive", "sibling", CANONICAL_URL + "-Output"))


def test_authentication_and_token_refresh_request_only_shared_narrow_scopes(monkeypatch, settings):
    calls = []

    class Credential:
        def __init__(self, **kwargs):
            assert kwargs["client_id"] == settings.graph_client_id

        def authenticate(self, *, scopes):
            calls.append(tuple(scopes))

        def get_token(self, *scopes):
            calls.append(scopes)
            return SimpleNamespace(token="synthetic-token")

    monkeypatch.setattr(graph_module, "DeviceCodeCredential", Credential)
    monkeypatch.setattr(Graph, "request", lambda *args: {"id": "demo-user", "displayName": "Demo"})
    auth = GraphAuth(settings)
    auth.authenticate()
    assert auth.snapshot()["status"] == "signed_in"
    assert auth.token() == "synthetic-token"
    assert calls == [GRAPH_SCOPES, GRAPH_SCOPES]
    assert GRAPH_SCOPES == ("User.Read", "Files.ReadWrite")


def test_folder_403_preserves_error_codes_without_leaking_sharing_link(graph, caplog):
    client, calls, responses = graph
    responses.append(
        httpx.Response(
            403,
            headers={"request-id": "synthetic-request-id"},
            json={
                "error": {
                    "code": "accessDenied",
                    "message": f"Cannot access {SHARING_URL}",
                    "innerError": {"code": "restrictedAccess", "message": "sensitive details"},
                }
            },
        )
    )
    with pytest.raises(GraphHTTPError) as caught:
        client.resolve_folder(SHARING_URL)
    error = caught.value
    assert error.status_code == 403
    assert error.codes == ["accessDenied", "restrictedAccess"]
    assert error.request_id == "synthetic-request-id"
    assert len(calls) == 1
    rendered = str(error) + caplog.text
    assert "accessDenied" in rendered
    assert "restrictedAccess" in rendered
    assert SHARING_URL not in rendered
    assert "sensitive details" not in rendered
    assert "/shares/u!" not in rendered
    assert base64.urlsafe_b64encode(SHARING_URL.encode()).decode().rstrip("=") not in rendered


@pytest.mark.parametrize("content", [b"not JSON", b"null", b"[]", b'{"error":"unexpected"}'])
def test_graph_error_with_nonstandard_body_preserves_http_status(content):
    error = GraphHTTPError(httpx.Response(403, content=content))
    assert error.status_code == 403
    assert error.codes == []
    assert "error code unavailable" in str(error)


def test_graph_error_uses_inner_request_id_and_conditional_access_marker():
    error = GraphHTTPError(
        httpx.Response(
            403,
            headers={"www-authenticate": 'Bearer error="insufficient_claims", claims="sensitive"'},
            json={
                "error": {
                    "code": "accessDenied",
                    "innererror": {"request-id": "inner-request", "code": "insufficient_claims"},
                }
            },
        )
    )
    assert error.codes == ["accessDenied", "insufficient_claims"]
    assert error.request_id == "inner-request"
    assert "sensitive" not in str(error)


def test_graph_error_rejects_unsafe_code_and_request_id():
    error = GraphHTTPError(
        httpx.Response(
            403,
            json={
                "error": {
                    "code": SHARING_URL,
                    "innerError": {"request-id": SHARING_URL},
                }
            },
        )
    )
    assert SHARING_URL not in str(error)
    assert error.codes == []
    assert error.request_id == "unavailable"


@pytest.mark.parametrize("path", ["https://outside.example", "//outside.example", "relative"])
def test_graph_requests_reject_absolute_or_ambiguous_paths_before_network(graph, path):
    client, calls, _ = graph
    with pytest.raises(ValueError, match="relative paths"):
        client.request("GET", path)
    assert calls == []


def test_optional_missing_item_and_empty_response_are_supported(graph):
    client, _, responses = graph
    responses.extend([httpx.Response(404), httpx.Response(204)])
    assert client.request("GET", "/missing", missing_ok=True) is None
    assert client.request("DELETE", "/item") == {}


@pytest.mark.parametrize("operation", ["request", "download", "upload"])
def test_transport_failures_return_actionable_service_errors(graph, operation):
    client, _, responses = graph
    folder = Folder("drive", "folder", CANONICAL_URL)
    failure = httpx.ReadTimeout("synthetic private transfer URL")
    if operation == "request":
        responses.append(failure)

        def call():
            return client.request("GET", "/item")
    elif operation == "download":
        responses.append(failure)

        def call():
            return client.download(
                folder,
                {"size": 3, "@microsoft.graph.downloadUrl": "https://demo.sharepoint.com/file"},
            )
    else:
        responses.extend(
            [
                httpx.Response(404),
                {"uploadUrl": "https://demo.sharepoint.com/upload"},
                failure,
            ]
        )

        def call():
            return client.upload(folder, "D01.pdf", b"pdf")

    with pytest.raises(ServiceError) as caught:
        call()
    assert "synthetic private" not in str(caught.value)


@pytest.mark.parametrize("filename", [".hidden", "../outside.pdf", "a/b.pdf", "x" * 161])
def test_child_rejects_unsafe_filenames(graph, filename):
    client, calls, _ = graph
    with pytest.raises(ValueError, match="Dateiname"):
        client.child(Folder("drive", "folder", CANONICAL_URL), filename)
    assert calls == []


@pytest.mark.parametrize("size", [None, 2_000_001])
def test_download_requires_bounded_metadata_before_any_transfer(graph, size):
    client, calls, _ = graph
    item = {} if size is None else {"size": size}
    with pytest.raises(ServiceError, match="Groessenlimit"):
        client.download(Folder("drive", "folder", CANONICAL_URL), item)
    assert calls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://demo.sharepoint.com/file",
        "https://outside.example/file",
        "https://demo.sharepoint.com.attacker.example/file",
        "https://user@demo.sharepoint.com/file",
        "https://demo.sharepoint.com:444/file",
    ],
)
def test_transfer_url_must_remain_on_supported_https_hosts(url):
    with pytest.raises(ServiceError, match="uebertragungsadresse"):
        Graph.validate_transfer_url(url)


@pytest.mark.parametrize("outcome", ["success", "status", "metadata", "size", "word-content"])
def test_new_upload_requires_explicit_confirmation_and_content_consistency(graph, outcome):
    client, calls, responses = graph
    item = {
        "id": "owned-item",
        "webUrl": CANONICAL_URL + "/result",
        "size": 3,
        "@microsoft.graph.downloadUrl": "https://demo.sharepoint.com/download",
    }
    if outcome == "metadata":
        item.pop("id")
    if outcome == "size":
        item["size"] = 4
    responses.extend(
        [
            httpx.Response(404),
            {"uploadUrl": "https://demo.sharepoint.com/upload"},
            httpx.Response(202 if outcome == "status" else 201, json=item),
        ]
    )
    if outcome == "word-content":
        responses.append(httpx.Response(200, content=b"changed"))
    filename = "result.docx" if outcome == "word-content" else "D01.pdf"
    if outcome == "success":
        assert client.upload(Folder("drive", "folder", CANONICAL_URL), filename, b"pdf") == item
    else:
        with pytest.raises(ServiceError):
            client.upload(Folder("drive", "folder", CANONICAL_URL), filename, b"pdf")
    assert calls[1].method == "POST"
    assert calls[2].method == "PUT"
    assert "authorization" not in calls[2].headers
    assert calls[2].headers["content-range"] == "bytes 0-2/3"


def test_connection_scopes_cannot_be_nested_and_close_idempotently(graph):
    client, _, _ = graph
    with client:
        with pytest.raises(RuntimeError, match="already open"):
            client.__enter__()
    client.__exit__()
    assert client._client is None


def test_folder_resolution_rejects_missing_parent_and_invalid_configuration(graph):
    client, calls, responses = graph
    with pytest.raises(ServiceError):
        client.resolve_folder("invalid")
    assert calls == []
    responses.append({key: value for key, value in ITEM.items() if key != "parentReference"})
    with pytest.raises(ServiceError, match="Laufwerk-ID"):
        client.resolve_folder(SHARING_URL)


@pytest.mark.parametrize("invalid", ["same-ids", "invalid-canonical"])
def test_folder_separation_requires_distinct_ids_and_valid_canonical_urls(invalid):
    source = Folder("drive", "input", CANONICAL_URL)
    output = (
        Folder("drive", "input", CANONICAL_URL + "-other")
        if invalid == "same-ids"
        else Folder("drive", "output", "https://outside.example/path")
    )
    with pytest.raises(ServiceError):
        ensure_separate_folders(source, output)


def test_device_prompt_snapshot_and_start_are_safe_and_idempotent(monkeypatch, settings):
    monkeypatch.setattr(graph_module, "DeviceCodeCredential", Mock())
    thread = Mock()
    monkeypatch.setattr(graph_module.threading, "Thread", thread)
    auth = GraphAuth(settings)
    assert auth.start()["status"] == "starting"
    thread.assert_called_once_with(target=auth.authenticate, daemon=True)
    thread.return_value.start.assert_called_once()
    expires = datetime(2026, 1, 1, tzinfo=UTC)
    auth.prompt("https://microsoft.com/devicelogin", "SYNTHETIC", expires)
    state = auth.start()
    assert state["status"] == "pending"
    assert state["expires_at"] == expires.isoformat()
    state["status"] = "mutated"
    assert auth.snapshot()["status"] == "pending"
    assert thread.call_count == 1


def test_delegated_auth_without_credential_fails_closed(monkeypatch, settings):
    monkeypatch.setattr(graph_module, "DeviceCodeCredential", Mock())
    auth = GraphAuth(settings)
    auth.credential = None
    auth.authenticate()
    assert auth.snapshot()["status"] == "error"
    assert auth.owner is None
    with pytest.raises(ServiceError, match="Authentifizierung fehlgeschlagen"):
        auth.token()
    with pytest.raises(ValueError, match="Authentifizierungsmodus"):
        GraphAuth(replace(settings, graph_auth_mode="unsupported"))
