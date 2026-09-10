import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docx import Document

from app.config import ROOT, Settings
from app.document_integrity import stored_content_matches
from app.export import OpinionSummary, render_summary
from app.foundry import Foundry
from app.graph import (
    Folder,
    Graph,
    GraphAuth,
    GraphHTTPError,
    ServiceError,
    ensure_separate_folders,
)
from app.graph_permissions import GRAPH_APPLICATION_SCOPE, GRAPH_SCOPES
from app.grounding import load_corpus


class ConsoleAuth(GraphAuth):
    def prompt(self, verification_uri, user_code, expires_on):
        super().prompt(verification_uri, user_code, expires_on)
        print(f"Open {verification_uri} and enter the one-time code {user_code}.", flush=True)


def resolve_folders(graph: Graph, settings: Settings, *, check_both: bool) -> tuple[Folder, Folder]:
    folders = []
    failures = []
    for role, url, drive_id, item_id in (
        ("input", settings.input_url, settings.input_drive_id, settings.input_folder_id),
        ("output", settings.output_url, settings.output_drive_id, settings.output_folder_id),
    ):
        method = "pinned IDs" if drive_id else "sharing link"
        print(f"Checking {role} folder metadata ({method})...", flush=True)
        try:
            folders.append(graph.resolve_folder(url, drive_id=drive_id, item_id=item_id))
        except ServiceError as error:
            message = f"{role.capitalize()} folder failed: {error}"
            if not check_both:
                raise ServiceError(message) from None
            failures.append(role)
            print(message, file=sys.stderr, flush=True)
            if isinstance(error, GraphHTTPError) and error.status_code == 403:
                if "insufficient_claims" in error.codes:
                    print(
                        "Conditional Access requires an additional authentication challenge; "
                        "do not disable the policy.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "Authentication succeeded, but folder access was denied. Check this "
                        "identity's existing SharePoint access. The 403 alone does not "
                        "establish which permission, license, or policy is responsible.",
                        file=sys.stderr,
                    )
        else:
            print(f"{role.capitalize()} folder metadata resolved.", flush=True)
    if failures:
        raise ServiceError(
            f"Folder metadata check failed for {', '.join(failures)}. "
            "No document contents read or uploaded; no permission changes requested. "
            "No successful folder configuration was saved."
        )
    source, output = folders
    ensure_separate_folders(source, output)
    return source, output


def main():
    parser = argparse.ArgumentParser(description="Explicit live diagnostic; never runs in CI")
    parser.add_argument(
        "--foundry-only",
        action="store_true",
        help="Check Azure sign-in and model response; incurs model usage",
    )
    parser.add_argument(
        "--resolve-folders",
        action="store_true",
        help="Sign in and resolve folder IDs without reading or uploading documents",
    )
    parser.add_argument(
        "--upload-corpus", action="store_true", help="Upload only manifest-listed synthetic PDFs"
    )
    parser.add_argument(
        "--save-example",
        action="store_true",
        help="Create and read back a synthetic Word file in the output folder",
    )
    args = parser.parse_args()
    if (args.foundry_only or args.resolve_folders) and (
        args.upload_corpus or args.save_example or (args.foundry_only and args.resolve_folders)
    ):
        parser.error("--foundry-only and --resolve-folders cannot be combined with other checks")
    settings = Settings.load()
    if args.foundry_only:
        if not settings.project_endpoint:
            parser.error("FOUNDRY_PROJECT_ENDPOINT is missing")
        foundry = Foundry(settings)
        version = foundry.configure_agent()
        response = foundry.client.responses.create(
            input="Antworte auf Deutsch mit einem kurzen Gruss.",
            store=False,
            extra_body={
                "agent_reference": {
                    "type": "agent_reference",
                    "name": settings.agent_name,
                    "version": version,
                }
            },
        )
        if response.status != "completed":
            raise ServiceError(f"Foundry response was not completed: {response.status}")
        print(f"Prompt agent version {version}; response status: {response.status}")
        print(response.output_text)
        return
    if issues := settings.graph_issues():
        parser.error("; ".join(issues))
    if issues := settings.folder_issues():
        parser.error("; ".join(issues))
    if settings.graph_auth_mode == "application":
        print("Graph mode: application identity; no per-user SharePoint permission trimming.")
        print("App token scope:", GRAPH_APPLICATION_SCOPE)
        auth = GraphAuth(settings)
    else:
        print("Delegated Graph scopes:", ", ".join(GRAPH_SCOPES))
        auth = ConsoleAuth(settings)
    auth.authenticate()
    if not auth.owner:
        raise ServiceError(auth.snapshot()["message"])
    print(
        "Application authentication succeeded; no user profile lookup."
        if settings.graph_auth_mode == "application"
        else "Sign-in and Graph profile lookup succeeded.",
        flush=True,
    )
    graph = Graph(auth)
    source, output = resolve_folders(graph, settings, check_both=args.resolve_folders)
    state_dir = ROOT / ".local"
    state_dir.mkdir(mode=0o700, exist_ok=True)
    folder_state = {
        role: {"drive_id": folder.drive_id, "item_id": folder.item_id, "url": folder.url}
        for role, folder in (("input", source), ("output", output))
    }
    (state_dir / "sharepoint-folders.json").write_text(json.dumps(folder_state, indent=2) + "\n")
    print(
        "Resolved separate SharePoint folders; "
        "canonical IDs saved to .local/sharepoint-folders.json."
    )
    if args.resolve_folders:
        print("No documents read or uploaded; no permission changes requested.")
        return
    manifest = json.loads((ROOT / "sample-data/corpus-manifest.json").read_text())
    if args.upload_corpus:
        state = []
        for entry in manifest["documents"]:
            content = (ROOT / "sample-data/pdfs" / entry["filename"]).read_bytes()
            item = graph.upload(source, entry["filename"], content)
            state.append(
                {
                    "document_id": entry["document_id"],
                    "item_id": item["id"],
                    "drive_id": source.drive_id,
                    "url": item["webUrl"],
                }
            )
            (state_dir / "corpus-items.json").write_text(json.dumps(state, indent=2) + "\n")
            print(f"Uploaded or already identical: {entry['filename']}")
    if args.upload_corpus or not args.save_example:
        corpus = load_corpus(graph, source)
        print(
            f"Read {len(corpus.sources)} PDFs, {sum(corpus.pages.values())} pages from SharePoint."
        )
        if "30 Fahrzeuge" not in corpus.context:
            raise ServiceError("The expected distinctive pilot fact '30 Fahrzeuge' was not found.")
        print("Distinctive pilot fact verified: 30 Fahrzeuge.")
    if args.save_example:
        path = state_dir / "smoke-summary.docx"
        if not path.exists():
            path.write_bytes(
                render_summary(
                    OpinionSummary(
                        topic="Synthetischer Speichercheck", haltung="Noch unentschieden."
                    ),
                    sources={},
                    owner=auth.owner["displayName"],
                    created_at=datetime.now(UTC),
                )
            )
        item = graph.upload(output, "poc-smoke-summary.docx", path.read_bytes())
        content = graph.download(output, item)
        expected = path.read_bytes()
        if not stored_content_matches("poc-smoke-summary.docx", expected, content):
            raise ServiceError("The stored Word content differs from the generated document.")
        headings = {
            "Haltung zum Thema",
            "Fragen, die noch geklärt werden müssen",
            "Gegenpositionen",
        }
        if not headings <= {paragraph.text for paragraph in Document(BytesIO(content)).paragraphs}:
            raise ServiceError("The downloaded Word file is missing required headings.")
        (state_dir / "smoke-item.json").write_text(
            json.dumps(
                {
                    "drive_id": output.drive_id,
                    "item_id": item["id"],
                    "url": item["webUrl"],
                    "exact_bytes_equal": expected == content,
                    "authored_package_content_verified": True,
                    "source_sha256": hashlib.sha256(expected).hexdigest(),
                    "stored_sha256": hashlib.sha256(content).hexdigest(),
                },
                indent=2,
            )
        )
        print("Verified real Word upload/download:", item["webUrl"])
        if content != expected:
            print(
                "SharePoint added package metadata; "
                "authored Word content verified, not byte equality."
            )
    print("No voice or cross-user permission claim is implied by this check.")


def run() -> int:
    try:
        main()
    except ServiceError as error:
        print(f"Live check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
