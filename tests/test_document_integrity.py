from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import httpx
import pytest

from app.document_integrity import CONTENT_TYPE, OFFICE_REL, REL, stored_content_matches
from app.export import OpinionSummary, render_summary
from app.graph import Folder, Graph, ServiceError


def package(parts):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def parts(content):
    with ZipFile(BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.fixture
def original():
    return render_summary(
        OpinionSummary(topic="Synthetic example", haltung="Unentschieden"),
        sources={},
        owner="Synthetic operator",
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
    )


@pytest.fixture
def enriched(original):
    result = parts(original)
    result["docProps/custom.xml"] = (
        b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"/>'
    )
    result["customXml/item2.xml"] = (
        b'<properties xmlns="http://schemas.microsoft.com/office/2006/metadata/properties"/>'
    )
    result["customXml/itemProps2.xml"] = (
        b'<datastoreItem xmlns="http://schemas.openxmlformats.org/officeDocument/2006/customXml"/>'
    )
    result["customXml/_rels/item2.xml.rels"] = (
        f'<Relationships xmlns="{REL}"><Relationship Id="meta" '
        f'Type="{OFFICE_REL}customXmlProps" Target="itemProps2.xml"/></Relationships>'
    ).encode()
    result["[trash]/0000.dat"] = b"discarded package blocks"
    for name, target, kind in [
        ("_rels/.rels", "docProps/custom.xml", "custom-properties"),
        ("word/_rels/document.xml.rels", "../customXml/item2.xml", "customXml"),
    ]:
        root = ET.fromstring(result[name])
        ET.SubElement(
            root,
            f"{{{REL}}}Relationship",
            {
                "Id": "metadata",
                "Type": OFFICE_REL + kind,
                "Target": target,
            },
        )
        result[name] = ET.tostring(root)
    root = ET.fromstring(result["[Content_Types].xml"])
    for name, kind in [
        ("docProps/custom.xml", "custom-properties"),
        ("customXml/itemProps2.xml", "customXmlProperties"),
    ]:
        ET.SubElement(
            root,
            f"{{{CONTENT_TYPE}}}Override",
            {
                "PartName": "/" + name,
                "ContentType": f"application/vnd.openxmlformats-officedocument.{kind}+xml",
            },
        )
    result["[Content_Types].xml"] = ET.tostring(root)
    for name in ("docProps/core.xml", "customXml/item1.xml"):
        result[name] = ET.tostring(ET.fromstring(result[name]))
    return result


def test_metadata_enrichment_preserves_authored_package(original, enriched):
    stored = package(enriched)
    assert original != stored
    assert stored_content_matches("summary.docx", original, stored)
    assert stored_content_matches("summary.docx", original, original)
    assert not stored_content_matches("source.pdf", original, stored)


@pytest.mark.parametrize("name", ["word/document.xml", "word/styles.xml", "docProps/app.xml"])
def test_authored_parts_must_remain_byte_identical(original, enriched, name):
    enriched[name] += b" "
    assert not stored_content_matches("summary.docx", original, package(enriched))


def test_core_properties_must_preserve_values(original, enriched):
    enriched["docProps/core.xml"] = enriched["docProps/core.xml"].replace(
        b"Synthetic example", b"A different topic"
    )
    assert not stored_content_matches("summary.docx", original, package(enriched))


def test_original_metadata_cannot_change_semantically(original, enriched):
    enriched["customXml/item1.xml"] = b"<different/>"
    assert not stored_content_matches("summary.docx", original, package(enriched))


def test_unrecognized_parts_and_macro_parts_are_rejected(original, enriched):
    enriched["word/vbaProject.bin"] = b"unrelated payload"
    assert not stored_content_matches("summary.docx", original, package(enriched))


@pytest.mark.parametrize("name", ["word/_rels/document.xml.rels", "customXml/_rels/item2.xml.rels"])
def test_added_external_relationship_is_rejected(original, enriched, name):
    root = ET.fromstring(enriched[name])
    root[-1].set("TargetMode", "External")
    root[-1].set("Target", "https://outside.example/metadata.xml")
    enriched[name] = ET.tostring(root)
    assert not stored_content_matches("summary.docx", original, package(enriched))


def test_existing_relationship_cannot_change_target(original, enriched):
    root = ET.fromstring(enriched["word/_rels/document.xml.rels"])
    root[0].set("Target", "different.xml")
    enriched["word/_rels/document.xml.rels"] = ET.tostring(root)
    assert not stored_content_matches("summary.docx", original, package(enriched))


def test_bound_fields_cannot_use_metadata_normalization(original, enriched):
    before = parts(original)
    document = ET.fromstring(before["word/document.xml"])
    ET.SubElement(
        document, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldSimple"
    )
    before["word/document.xml"] = enriched["word/document.xml"] = ET.tostring(document)
    assert not stored_content_matches("summary.docx", package(before), package(enriched))


def test_missing_part_invalid_xml_or_invalid_archive_is_rejected(original, enriched):
    assert not stored_content_matches("summary.docx", original, b"not a ZIP")
    enriched["docProps/core.xml"] = b"<!DOCTYPE root><root/>"
    assert not stored_content_matches("summary.docx", original, package(enriched))
    del enriched["word/document.xml"]
    assert not stored_content_matches("summary.docx", original, package(enriched))


def test_retry_matches_storage_metadata_without_uploading_again(original, enriched, monkeypatch):
    graph = Graph(SimpleNamespace(token=lambda: "synthetic"))
    item = {
        "id": "existing",
        "size": len(package(enriched)),
        "webUrl": "https://demo.sharepoint.com/",
    }
    monkeypatch.setattr(graph, "child", lambda *args, **kwargs: item)
    monkeypatch.setattr(graph, "download", lambda *args: package(enriched))
    monkeypatch.setattr(graph, "request", lambda *args, **kwargs: pytest.fail("No retry write"))
    folder = Folder("drive", "folder", "https://demo.sharepoint.com/sites/Demo/Documents/Output")
    assert graph.upload(folder, "summary.docx", original) is item
    enriched["word/document.xml"] = b"different document"
    with pytest.raises(ServiceError, match="andere Datei"):
        graph.upload(folder, "summary.docx", original)


def test_new_upload_verifies_content_even_when_storage_changes_size(
    original, enriched, monkeypatch
):
    graph = Graph(SimpleNamespace(token=lambda: "synthetic"))
    stored = package(enriched)
    item = {"id": "new", "size": len(stored), "webUrl": "https://demo.sharepoint.com/document"}
    monkeypatch.setattr(graph, "child", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        graph,
        "request",
        lambda *args, **kwargs: {"uploadUrl": "https://demo.sharepoint.com/upload"},
    )
    monkeypatch.setattr(graph, "download", lambda *args: stored)
    client = httpx.Client

    def uploaded(request):
        assert request.method == "PUT"
        assert request.content == original
        return httpx.Response(201, json=item)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(uploaded), **kwargs)
    )
    folder = Folder("drive", "folder", "https://demo.sharepoint.com/sites/Demo/Documents/Output")
    assert graph.upload(folder, "summary.docx", original) == item
