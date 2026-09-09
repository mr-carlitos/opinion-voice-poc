import argparse
import json
import sys
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docx import Document

from app.config import ROOT, Settings
from app.export import OpinionSummary, render_summary
from app.foundry import Foundry
from app.graph import Graph, GraphAuth
from app.grounding import load_corpus


class ConsoleAuth(GraphAuth):
    def prompt(self, verification_uri, user_code, expires_on):
        super().prompt(verification_uri, user_code, expires_on)
        print(f"Open {verification_uri} and enter the one-time code {user_code}.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Explicit live diagnostic; never runs in CI")
    parser.add_argument("--foundry-only", action="store_true", help="Check Azure sign-in and model response; incurs model usage")
    parser.add_argument("--upload-corpus", action="store_true", help="Upload only manifest-listed synthetic PDFs")
    parser.add_argument("--save-example", action="store_true", help="Create and read back a synthetic Word file in the output folder")
    args = parser.parse_args()
    settings = Settings.load()
    if args.foundry_only:
        if not settings.project_endpoint:
            parser.error("FOUNDRY_PROJECT_ENDPOINT is missing")
        foundry = Foundry(settings)
        version = foundry.configure_agent()
        response = foundry.client.responses.create(
            input="Antworte auf Deutsch mit einem kurzen Gruss.",
            store=False,
            extra_body={"agent_reference": {"type": "agent_reference", "name": settings.agent_name, "version": version}},
        )
        print(f"Prompt agent version {version}; response status: {response.status}")
        print(response.output_text)
        return
    if not all((settings.tenant_id, settings.graph_client_id, settings.input_url, settings.output_url)):
        parser.error("Graph tenant/client ID and both SharePoint folder URLs are required in .env")
    auth = ConsoleAuth(settings)
    auth.authenticate()
    if not auth.owner:
        raise RuntimeError(auth.snapshot()["message"])
    graph = Graph(auth)
    source, output = graph.resolve_folder(settings.input_url), graph.resolve_folder(settings.output_url)
    if source.drive_id == output.drive_id and source.item_id == output.item_id:
        raise RuntimeError("Input and output resolve to the same folder")
    state_dir = ROOT / ".local"
    state_dir.mkdir(exist_ok=True)
    manifest = json.loads((ROOT / "sample-data/corpus-manifest.json").read_text())
    if args.upload_corpus:
        state = []
        for entry in manifest["documents"]:
            content = (ROOT / "sample-data/pdfs" / entry["filename"]).read_bytes()
            item = graph.upload(source, entry["filename"], content)
            state.append({"document_id": entry["document_id"], "item_id": item["id"], "drive_id": source.drive_id, "url": item["webUrl"]})
            print(f"Uploaded or already identical: {entry['filename']}")
        (state_dir / "corpus-items.json").write_text(json.dumps(state, indent=2))
    corpus = load_corpus(graph, source)
    print(f"Read {len(corpus.sources)} PDFs, {sum(corpus.pages.values())} pages from SharePoint.")
    print("Distinctive pilot fact found:", "30 Fahrzeuge" in corpus.context)
    if args.save_example:
        path = state_dir / "smoke-summary.docx"
        if not path.exists():
            path.write_bytes(render_summary(
                OpinionSummary(topic="Synthetischer Speichercheck", haltung="Noch unentschieden."),
                sources={}, owner=auth.owner["displayName"], created_at=datetime.now(UTC),
            ))
        item = graph.upload(output, "poc-smoke-summary.docx", path.read_bytes())
        content = graph.download(output, item)
        assert content == path.read_bytes(), "Uploaded bytes differ from downloaded bytes"
        assert any(paragraph.text == "Haltung zum Thema" for paragraph in Document(BytesIO(content)).paragraphs)
        (state_dir / "smoke-item.json").write_text(json.dumps({"drive_id": output.drive_id, "item_id": item["id"], "url": item["webUrl"]}, indent=2))
        print("Verified real Word upload/download:", item["webUrl"])
    print("No voice or cross-user permission claim is implied by this check.")


if __name__ == "__main__":
    main()