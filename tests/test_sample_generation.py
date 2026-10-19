import json

from PIL import Image, ImageFont
from pypdf import PdfReader

from scripts import generate_sample_pdfs


def test_sample_generation_produces_reproducible_manifest_pdfs_and_preview(tmp_path, monkeypatch):
    scenario = json.loads((generate_sample_pdfs.ROOT / "sample-data/scenario.json").read_text())
    sample = tmp_path / "sample-data"
    sample.mkdir()
    (sample / "scenario.json").write_text(json.dumps(scenario))
    (tmp_path / "app/static").mkdir(parents=True)
    monkeypatch.setattr(generate_sample_pdfs, "ROOT", tmp_path)
    # Avoid requiring an OS-installed font for this document-generation test.
    font = ImageFont.load_default()
    monkeypatch.setattr(generate_sample_pdfs.ImageFont, "truetype", lambda *args: font)
    generate_sample_pdfs.generate()
    manifest = json.loads((sample / "corpus-manifest.json").read_text())
    assert manifest["documents"] == [
        {key: entry[key] for key in ("document_id", "filename", "title")}
        for entry in scenario["documents"]
    ]
    assert len(manifest["documents"]) == 6
    originals = {}
    for entry in scenario["documents"]:
        path = sample / "pdfs" / entry["filename"]
        originals[path] = path.read_bytes()
        reader = PdfReader(path)
        assert len(reader.pages) == len(entry["pages"])
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            assert "SYNTHETISCHE DEMODATEN" in text
            assert entry["document_id"] in text
            assert f"Seite {number}" in text
    with Image.open(tmp_path / "app/static/briefing.png") as preview:
        assert preview.size == (960, 560)
        assert preview.format == "PNG"
    generate_sample_pdfs.generate()
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_sample_pdf_escapes_markup_in_source_text(tmp_path, monkeypatch):
    sample = tmp_path / "sample-data"
    sample.mkdir()
    (tmp_path / "app/static").mkdir(parents=True)
    scenario = {
        "company": "Synthetic",
        "date": "2026-01-01",
        "documents": [
            {
                "document_id": "D01",
                "filename": "D01.pdf",
                "title": "A < B & C",
                "pages": [{"heading": "<synthetic>", "paragraphs": ["A & B < C > D"]}],
            }
        ],
    }
    (sample / "scenario.json").write_text(json.dumps(scenario))
    monkeypatch.setattr(generate_sample_pdfs, "ROOT", tmp_path)
    font = ImageFont.load_default()
    monkeypatch.setattr(generate_sample_pdfs.ImageFont, "truetype", lambda *args: font)
    generate_sample_pdfs.generate()
    text = PdfReader(sample / "pdfs/D01.pdf").pages[0].extract_text()
    assert "A < B & C" in text
    assert "<synthetic>" in text
    assert "A & B < C > D" in text
