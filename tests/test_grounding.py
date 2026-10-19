import json
from io import BytesIO
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen.canvas import Canvas

from app import grounding
from app.graph import Folder, ServiceError


@pytest.fixture
def corpus_input(monkeypatch, tmp_path):
    sample = tmp_path / "sample-data"
    sample.mkdir()
    manifest = sample / "corpus-manifest.json"
    entry = {"document_id": "D01", "filename": "D01.pdf", "title": "Synthetische Quelle"}
    manifest.write_text(json.dumps({"documents": [entry]}))
    monkeypatch.setattr(grounding, "ROOT", tmp_path)
    folder = Folder("drive", "input", "https://demo.sharepoint.com/sites/Demo/Docs/Input")
    item = {
        "id": "source",
        "eTag": "v1",
        "file": {},
        "webUrl": folder.url + "/D01.pdf",
        "parentReference": {"id": folder.item_id, "driveId": folder.drive_id},
    }
    graph = Mock()
    graph.child.return_value = item
    graph.download.return_value = text_pdf(["  Synthetischer Inhalt: 30 Fahrzeuge.  "])
    return graph, folder, manifest, entry


def text_pdf(pages):
    buffer = BytesIO()
    canvas = Canvas(buffer)
    for text in pages:
        canvas.drawString(40, 800, text)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


@pytest.mark.parametrize("count", [0, 7])
def test_manifest_document_count_is_bounded(corpus_input, count):
    graph, folder, manifest, entry = corpus_input
    manifest.write_text(json.dumps({"documents": [entry] * count}))
    with pytest.raises(ServiceError, match="ein bis sechs"):
        grounding.load_corpus(graph, folder)
    graph.child.assert_not_called()


@pytest.mark.parametrize("invalid", ["duplicate", "not-pdf"])
def test_manifest_rejects_duplicate_ids_and_non_pdf_files(corpus_input, invalid):
    graph, folder, manifest, entry = corpus_input
    entries = [entry, entry] if invalid == "duplicate" else [{**entry, "filename": "D01.docx"}]
    manifest.write_text(json.dumps({"documents": entries}))
    with pytest.raises(ServiceError, match="Korpusmanifest"):
        grounding.load_corpus(graph, folder)
    assert graph.download.call_count == (1 if invalid == "duplicate" else 0)


@pytest.mark.parametrize(
    "change", [{"file": None}, {"parentReference": {}}, {"parentReference": {"id": "other"}}]
)
def test_source_must_be_a_file_in_the_approved_folder(corpus_input, change):
    graph, folder, _, _ = corpus_input
    if "file" in change:
        graph.child.return_value.pop("file")
    else:
        graph.child.return_value.update(change)
    with pytest.raises(ServiceError, match="Eingabeordner"):
        grounding.load_corpus(graph, folder)
    graph.download.assert_not_called()


@pytest.mark.parametrize("kind", ["encrypted", "empty", "too-many-pages", "blank"])
def test_pdf_content_boundaries(corpus_input, kind):
    graph, folder, _, _ = corpus_input
    writer = PdfWriter()
    if kind != "empty":
        for _ in range(9 if kind == "too-many-pages" else 1):
            writer.add_blank_page(width=200, height=200)
    if kind == "encrypted":
        writer.encrypt("synthetic-pdf-password")
    buffer = BytesIO()
    writer.write(buffer)
    graph.download.return_value = buffer.getvalue()
    message = "extrahierbarer Text" if kind == "blank" else "maximal acht Seiten"
    with pytest.raises(ServiceError, match=message):
        grounding.load_corpus(graph, folder)


def test_real_pdf_extraction_preserves_text_pages_sources_and_versions(corpus_input):
    graph, folder, _, _ = corpus_input
    graph.download.return_value = text_pdf(["Erste Seite.", "Zweite Seite."])
    corpus = grounding.load_corpus(graph, folder)
    assert json.loads(corpus.context) == [
        {"document_id": "D01", "page": 1, "text": "Erste Seite."},
        {"document_id": "D01", "page": 2, "text": "Zweite Seite."},
    ]
    assert corpus.pages == {"D01": 2}
    assert corpus.versions == {"D01": "v1"}
    assert corpus.sources["D01"].title == "Synthetische Quelle"
    assert str(corpus.sources["D01"].url) == folder.url + "/D01.pdf"
    assert graph.child.call_count == 2
    graph.download.assert_called_once_with(folder, graph.child.return_value)


@pytest.mark.parametrize("characters", [100_000, 100_001])
def test_total_extracted_text_limit_has_no_silent_truncation(corpus_input, monkeypatch, characters):
    graph, folder, _, _ = corpus_input
    reader = Mock(is_encrypted=False)
    reader.pages = [Mock(extract_text=Mock(return_value="x" * characters))]
    monkeypatch.setattr(grounding, "PdfReader", Mock(return_value=reader))
    if characters > 100_000:
        with pytest.raises(ServiceError, match="keine stille Kuerzung"):
            grounding.load_corpus(graph, folder)
    else:
        sections = json.loads(grounding.load_corpus(graph, folder).context)
        assert len(sections[0]["text"]) == characters


def test_character_limit_is_shared_across_documents(corpus_input, monkeypatch):
    graph, folder, manifest, entry = corpus_input
    manifest.write_text(json.dumps({"documents": [entry, {**entry, "document_id": "D02"}]}))
    reader = Mock(is_encrypted=False)
    reader.pages = [Mock(extract_text=Mock(return_value="x" * 50_001))]
    monkeypatch.setattr(grounding, "PdfReader", Mock(return_value=reader))
    with pytest.raises(ServiceError, match="100000"):
        grounding.load_corpus(graph, folder)
