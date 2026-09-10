"""Compare generated DOCX content while allowing SharePoint's property metadata."""

import re
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CONTENT_TYPE = "http://schemas.openxmlformats.org/package/2006/content-types"
METADATA_ROOTS = {
    "{http://schemas.microsoft.com/office/2006/metadata/contentType}contentTypeSchema",
    "{http://schemas.microsoft.com/sharepoint/v3/contenttype/forms}FormTemplates",
    "{http://schemas.microsoft.com/office/2006/metadata/properties}properties",
}


def _package(content: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 256
            or len({entry.filename for entry in entries}) != len(entries)
            or sum(entry.file_size for entry in entries) > 8_000_000
        ):
            raise ValueError("Invalid or oversized Word package.")
        return {entry.filename: archive.read(entry) for entry in entries}


def _xml(content: bytes):
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("Document type declarations are not supported.")
    return ET.fromstring(content)


def _signature(node):
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text or "",
        node.tail or "",
        tuple(_signature(child) for child in node),
    )


def _declarations(content: bytes, root_tag: str) -> dict[str, dict[str, str]]:
    root = _xml(content)
    if root.tag != root_tag or root.attrib:
        raise ValueError("Unexpected package declaration root.")
    result = {}
    for child in root:
        if len(child) or (child.text or "").strip():
            raise ValueError("Unexpected package declaration content.")
        key = child.get("Id") or child.get("PartName") or child.get("Extension")
        if not key or key in result:
            raise ValueError("Ambiguous package declaration.")
        result[key] = {"tag": child.tag, **child.attrib}
    return result


def _added_declarations(name: str, expected: bytes, actual: bytes, added: set[str]) -> bool:
    content_types = name == "[Content_Types].xml"
    root = f"{{{CONTENT_TYPE}}}Types" if content_types else f"{{{REL}}}Relationships"
    before, after = _declarations(expected, root), _declarations(actual, root)
    if any(after.get(key) != value for key, value in before.items()):
        return False
    for key in after.keys() - before.keys():
        item = after[key]
        if content_types:
            part = item.get("PartName", "").removeprefix("/")
            kind = "custom-properties" if part == "docProps/custom.xml" else "customXmlProperties"
            if (
                part not in added
                or not (
                    part == "docProps/custom.xml"
                    or re.fullmatch(r"customXml/itemProps\d+\.xml", part)
                )
                or item
                != {
                    "tag": f"{{{CONTENT_TYPE}}}Override",
                    "PartName": "/" + part,
                    "ContentType": f"application/vnd.openxmlformats-officedocument.{kind}+xml",
                }
            ):
                return False
        else:
            target = item.get("Target", "")
            if name == "_rels/.rels":
                if target != "docProps/custom.xml":
                    return False
                part, kind = target, "custom-properties"
            else:
                if not re.fullmatch(r"\.\./customXml/item\d+\.xml", target):
                    return False
                part, kind = target.removeprefix("../"), "customXml"
            if part not in added or item != {
                "tag": f"{{{REL}}}Relationship",
                "Id": key,
                "Type": OFFICE_REL + kind,
                "Target": target,
            }:
                return False
    return True


def _storage_part(name: str, content: bytes, parts: dict[str, bytes]) -> bool:
    if re.fullmatch(r"\[trash\]/\d+\.dat", name):
        return True
    if name == "docProps/custom.xml":
        return _xml(content).tag == (
            "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}Properties"
        )
    if re.fullmatch(r"customXml/itemProps\d+\.xml", name):
        return _xml(content).tag == (
            "{http://schemas.openxmlformats.org/officeDocument/2006/customXml}datastoreItem"
        )
    if re.fullmatch(r"customXml/item\d+\.xml", name):
        return _xml(content).tag in METADATA_ROOTS
    if match := re.fullmatch(r"customXml/_rels/item(\d+)\.xml\.rels", name):
        target = f"itemProps{match[1]}.xml"
        relations = _declarations(content, f"{{{REL}}}Relationships")
        return (
            f"customXml/{target}" in parts
            and len(relations) == 1
            and all(
                value
                == {
                    "tag": f"{{{REL}}}Relationship",
                    "Id": key,
                    "Type": OFFICE_REL + "customXmlProps",
                    "Target": target,
                }
                for key, value in relations.items()
            )
        )
    return False


def stored_content_matches(filename: str, expected: bytes, actual: bytes) -> bool:
    if expected == actual:
        return True
    if not filename.lower().endswith(".docx"):
        return False
    try:
        before, after = _package(expected), _package(actual)
        if not before.keys() <= after.keys() or "word/document.xml" not in before:
            return False
        # Metadata may only be ignored for our static documents, never bound fields or controls.
        word_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        bound_tags = {
            word_ns + name for name in ("dataBinding", "fldChar", "instrText", "fldSimple")
        }
        if any(node.tag in bound_tags for node in _xml(before["word/document.xml"]).iter()):
            return False
        added = after.keys() - before.keys()
        if any(not _storage_part(name, after[name], after) for name in added):
            return False
        declarations = {"[Content_Types].xml", "_rels/.rels", "word/_rels/document.xml.rels"}
        for name, original in before.items():
            stored = after[name]
            if original == stored:
                continue
            if name in declarations:
                if not _added_declarations(name, original, stored, added):
                    return False
            elif name == "docProps/core.xml" or name.startswith("customXml/"):
                if _signature(_xml(original)) != _signature(_xml(stored)):
                    return False
            else:
                return False
        return True
    except (BadZipFile, ET.ParseError, ValueError, KeyError, RuntimeError):
        return False
