import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from app import graph as graph_module
from app import grounding
from app.graph import Folder, Graph, ServiceError

FOLDER = Folder("drive", "input", "https://demo.sharepoint.com/sites/Demo/Documents/Input")
URL = "https://demo.sharepoint.com/download?token=synthetic-secret"


@pytest.fixture
def transport(monkeypatch):
    responses = []
    requests = []
    clients = []
    real_client = httpx.Client

    def handle(request):
        requests.append(request)
        return responses.pop(0)

    def make_client(**kwargs):
        client = real_client(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(graph_module.httpx, "Client", make_client)
    return responses, requests, clients


def test_operation_scope_reuses_connections_and_never_sends_auth_to_file_url(transport, caplog):
    responses, requests, clients = transport
    item = {"id": "item", "size": 3, "@microsoft.graph.downloadUrl": URL}
    responses.extend([httpx.Response(200, json=item), httpx.Response(200, content=b"pdf")])
    caplog.set_level(logging.INFO, logger="httpx")
    graph = Graph(SimpleNamespace(token=lambda: "synthetic-bearer"))
    with graph:
        fresh = graph.child(FOLDER, "D01.pdf")
        assert graph.download(FOLDER, fresh) == b"pdf"
        assert not clients[0].is_closed
    assert len(clients) == 1
    assert clients[0].is_closed
    assert graph._client is None
    assert len(requests) == 2  # No redundant metadata refresh for a fresh download URL.
    assert requests[0].headers["authorization"].endswith("synthetic-bearer")
    assert "authorization" not in requests[1].headers
    assert "synthetic-secret" not in caplog.text


def test_legacy_unscoped_requests_still_close_connections(transport):
    responses, _, clients = transport
    responses.append(httpx.Response(200, json={"id": "item"}))
    Graph(SimpleNamespace(token=lambda: "synthetic")).child(FOLDER, "D01.pdf")
    assert len(clients) == 1 and clients[0].is_closed


def test_missing_download_url_fetches_metadata_once(transport):
    responses, requests, _ = transport
    responses.extend(
        [
            httpx.Response(200, json={"@microsoft.graph.downloadUrl": URL}),
            httpx.Response(200, content=b"pdf"),
        ]
    )
    with Graph(SimpleNamespace(token=lambda: "synthetic")) as graph:
        assert graph.download(FOLDER, {"id": "item", "size": 3}) == b"pdf"
    assert len(requests) == 2
    assert requests[0].url.path == "/v1.0/drives/drive/items/item"
    assert "authorization" not in requests[1].headers


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(403), "HTTP 403"),
        (httpx.Response(200, content=b"large"), "Groessenlimit"),
    ],
)
def test_failed_or_oversized_download_fails_and_closes_scope(transport, response, message):
    responses, requests, clients = transport
    responses.append(response)
    graph = Graph(SimpleNamespace(token=lambda: "synthetic"))
    with pytest.raises(ServiceError, match=message), graph:
        graph.download(
            FOLDER, {"id": "item", "size": 3, "@microsoft.graph.downloadUrl": URL}, limit=3
        )
    assert len(requests) == 1
    assert clients[0].is_closed


@pytest.fixture
def corpus_source(monkeypatch, tmp_path):
    content = (grounding.ROOT / "sample-data/pdfs/D01-entscheidung.pdf").read_bytes()
    sample = tmp_path / "sample-data"
    sample.mkdir()
    (sample / "corpus-manifest.json").write_text(
        json.dumps(
            {
                "documents": [{"document_id": "D01", "filename": "D01.pdf", "title": "Synthetic"}],
            }
        )
    )
    monkeypatch.setattr(grounding, "ROOT", tmp_path)
    item = {
        "id": "doc1",
        "file": {},
        "eTag": "version-1",
        "webUrl": FOLDER.url + "/D01.pdf",
        "parentReference": {"id": FOLDER.item_id, "driveId": FOLDER.drive_id},
    }

    class FakeGraph:
        def __init__(self):
            self.calls = 0
            self.downloads = 0
            self.first = item
            self.second = item.copy()

        def child(self, *args):
            self.calls += 1
            return self.first if self.calls % 2 else self.second

        def download(self, *args):
            self.downloads += 1
            return content

    return FakeGraph()


def test_corpus_still_rechecks_source_version_after_download(corpus_source):
    corpus = grounding.load_corpus(corpus_source, FOLDER)
    assert corpus_source.calls == 2 and corpus_source.downloads == 1
    assert corpus.versions == {"D01": "version-1"}
    assert corpus.pages["D01"] == 2
    assert "30 Fahrzeuge" in corpus.context
    assert str(corpus.sources["D01"].url).endswith("/D01.pdf")


@pytest.mark.parametrize("change", [{"eTag": "version-2"}, {"id": "replaced-doc"}])
def test_corpus_rejects_changed_or_replaced_source(corpus_source, change):
    corpus_source.second.update(change)
    with pytest.raises(ServiceError, match="geaendert"):
        grounding.load_corpus(corpus_source, FOLDER)


@pytest.mark.parametrize("field", ["id", "eTag"])
def test_corpus_rejects_unverifiable_source_before_download(corpus_source, field):
    corpus_source.first.pop(field)
    with pytest.raises(ServiceError, match="pruefbare"):
        grounding.load_corpus(corpus_source, FOLDER)
    assert corpus_source.downloads == 0


def test_corpus_rejects_wrong_drive_even_when_parent_id_matches(corpus_source):
    corpus_source.first["parentReference"] = {"id": FOLDER.item_id, "driveId": "other-drive"}
    with pytest.raises(ServiceError, match="Eingabeordner"):
        grounding.load_corpus(corpus_source, FOLDER)
    assert corpus_source.downloads == 0
