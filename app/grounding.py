import json
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from app.config import ROOT
from app.export import RetrievedSource
from app.graph import Folder, Graph, ServiceError


@dataclass(frozen=True)
class Corpus:
    context: str
    sources: dict[str, RetrievedSource]
    pages: dict[str, int]
    versions: dict[str, str]


def load_corpus(graph: Graph, folder: Folder) -> Corpus:
    manifest = json.loads((ROOT / "sample-data/corpus-manifest.json").read_text())
    entries = manifest["documents"]
    if not 1 <= len(entries) <= 6:
        raise ServiceError("Der PoC unterstuetzt ein bis sechs freigegebene PDFs.")
    sources, pages, versions, sections = {}, {}, {}, []
    total = 0
    for entry in entries:
        document_id = entry["document_id"]
        if document_id in sources or not entry["filename"].endswith(".pdf"):
            raise ServiceError("Ungueltiges Korpusmanifest.")
        item = graph.child(folder, entry["filename"])
        if (
            "file" not in item
            or item.get("parentReference", {}).get("id") != folder.item_id
            or item.get("parentReference", {}).get("driveId") != folder.drive_id
        ):
            raise ServiceError("Quelldokument liegt nicht direkt im freigegebenen Eingabeordner.")
        if not item.get("id") or not item.get("eTag"):
            raise ServiceError("Quelldokument hat keine pruefbare ID oder Quellenversion.")
        content = graph.download(folder, item)
        latest = graph.child(folder, entry["filename"])
        if latest.get("eTag") != item["eTag"] or latest.get("id") != item["id"]:
            raise ServiceError(
                "Quelle wurde waehrend des Lesens geaendert. Sitzung erneut starten."
            )
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 8:
            raise ServiceError(
                "Nur unverschluesselte Text-PDFs mit maximal acht Seiten sind erlaubt."
            )
        source = RetrievedSource(document_id=document_id, title=entry["title"], url=item["webUrl"])
        sources[document_id] = source
        pages[document_id] = len(reader.pages)
        versions[document_id] = item["eTag"]
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                raise ServiceError(f"{document_id}, Seite {page_number}: kein extrahierbarer Text.")
            total += len(text)
            if total > 100_000:
                raise ServiceError(
                    "Korpus zu gross: maximal 100000 Zeichen; keine stille Kuerzung."
                )
            sections.append({"document_id": document_id, "page": page_number, "text": text})
    return Corpus(json.dumps(sections, ensure_ascii=False), sources, pages, versions)
