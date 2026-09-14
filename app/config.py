import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import SplitResult, unquote, urlsplit
from uuid import UUID

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _sharepoint_url(value: str) -> tuple[SplitResult, str]:
    message = "Bitte eine gueltige HTTPS-SharePoint-Ordneradresse verwenden."
    if (
        not isinstance(value, str)
        or not value
        or re.search(r"[\x00-\x20\x7f\\]", value)
        or re.search(r"%(?![0-9a-fA-F]{2})", value)
    ):
        raise ValueError(message)
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        path = unquote(parsed.path, errors="strict").rstrip("/")
    except (ValueError, UnicodeError):
        raise ValueError(message) from None
    if (
        parsed.scheme != "https"
        or not host
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.sharepoint\.com", host)
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.netloc.casefold() not in (host, host + ":443")
        or "#" in value
    ):
        raise ValueError(message)
    if (
        re.search(r"[\x00-\x1f\x7f\\]", path)
        or re.search(r"%[0-9a-fA-F]{2}", path)
        or "//" in parsed.path
        or re.search(r"%2f|%5c", parsed.path, re.IGNORECASE)
        or any(part in (".", "..") for part in path.split("/"))
    ):
        raise ValueError("Ungueltiger Ordnerpfad.")
    return parsed, path


def _canonical_path(path: str):
    parts = path.split("/")
    if (
        not path.casefold().startswith(("/sites/", "/teams/"))
        or len(parts) < 4
        or any(not part for part in parts[1:])
        or any(part.casefold() in ("_layouts", "_api", "forms") for part in parts[1:])
        or path.casefold().endswith(".aspx")
    ):
        raise ValueError("Die Adresse muss auf einen Ordner in einer Dokumentbibliothek zeigen.")


def folder_url(value: str) -> tuple[str, str]:
    """Validate a canonical folder webUrl, never a sharing or browser-view URL."""
    parsed, path = _sharepoint_url(value)
    if "?" in value:
        raise ValueError("Eine kanonische Ordneradresse darf keine Abfrage enthalten.")
    _canonical_path(path)
    return parsed.hostname, path


def validate_graph_id(value: str):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9!_.-]+", value):
        raise ValueError("Ungueltige Graph-Ordner-ID.")
    if value in (".", ".."):
        raise ValueError("Ungueltige Graph-Ordner-ID.")


@dataclass(frozen=True)
class FolderReference:
    host: str
    path: str
    sharing: bool


def folder_reference(value: str, *, drive_id: str = "", item_id: str = "") -> FolderReference:
    """Accept a folder sharing link, or a canonical URL pinned to both Graph IDs."""
    if bool(drive_id) != bool(item_id):
        raise ValueError("DRIVE_ID und FOLDER_ID muessen gemeinsam konfiguriert sein.")
    parsed, path = _sharepoint_url(value)
    sharing = path.startswith("/:f:/")
    if sharing:
        if drive_id or item_id:
            raise ValueError(
                "IDs nur mit kanonischer Ordneradresse, nicht mit Freigabelink verwenden."
            )
        tail = path.removeprefix("/:f:/")
        if tail.startswith("r/"):
            _canonical_path("/" + tail[2:])
        elif not (
            re.fullmatch(r"[st]/[^/:]+/[A-Za-z0-9_-]+", tail)
            or re.fullmatch(r"g/(?:[^/:]+/)*[A-Za-z0-9_-]+", tail)
        ):
            raise ValueError("Nicht unterstuetztes Format des Ordner-Freigabelinks.")
    else:
        folder_url(value)
        if not drive_id:
            raise ValueError(
                "Direkte Ordneradresse benoetigt DRIVE_ID und FOLDER_ID; "
                "alternativ einen vorhandenen Ordner-Freigabelink verwenden."
            )
        validate_graph_id(drive_id)
        validate_graph_id(item_id)
    return FolderReference(parsed.hostname, path, sharing)


def folder_paths_overlap(first: tuple[str, str], second: tuple[str, str]) -> bool:
    first_host, first_path = (part.casefold() for part in first)
    second_host, second_path = (part.casefold() for part in second)
    return first_host == second_host and (
        first_path == second_path
        or first_path.startswith(second_path + "/")
        or second_path.startswith(first_path + "/")
    )


@dataclass(frozen=True)
class GraphApplicationCredentials:
    tenant_id: str
    client_id: str
    secret: str = field(repr=False)


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    graph_client_id: str
    input_url: str
    output_url: str
    project_endpoint: str
    agent_name: str
    model: str
    voice_endpoint: str
    voice_name: str
    voice_api_version: str
    input_drive_id: str = ""
    input_folder_id: str = ""
    output_drive_id: str = ""
    output_folder_id: str = ""
    graph_auth_mode: str = "delegated"
    graph_application_credentials_file: str = ""
    voice_delivery_mode: str = "strict"
    avatar_enabled: bool = False
    avatar_character: str = "lisa"
    avatar_style: str = "casual-sitting"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            tenant_id=os.getenv("AZURE_TENANT_ID", ""),
            graph_client_id=os.getenv("GRAPH_CLIENT_ID", ""),
            input_url=os.getenv("SHAREPOINT_INPUT_FOLDER_URL", ""),
            output_url=os.getenv("SHAREPOINT_OUTPUT_FOLDER_URL", ""),
            project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").rstrip("/"),
            agent_name=os.getenv("FOUNDRY_AGENT_NAME", "opinion-voice"),
            model=os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-5.1"),
            voice_endpoint=os.getenv("VOICELIVE_ENDPOINT", "").rstrip("/"),
            voice_name=os.getenv("VOICE_NAME", "de-DE-KatjaNeural"),
            voice_api_version=os.getenv("VOICELIVE_API_VERSION", "2026-04-10"),
            input_drive_id=os.getenv("SHAREPOINT_INPUT_DRIVE_ID", ""),
            input_folder_id=os.getenv("SHAREPOINT_INPUT_FOLDER_ID", ""),
            output_drive_id=os.getenv("SHAREPOINT_OUTPUT_DRIVE_ID", ""),
            output_folder_id=os.getenv("SHAREPOINT_OUTPUT_FOLDER_ID", ""),
            graph_auth_mode=os.getenv("GRAPH_AUTH_MODE", "delegated").strip().lower(),
            graph_application_credentials_file=os.getenv("GRAPH_APPLICATION_CREDENTIALS_FILE", ""),
            voice_delivery_mode=os.getenv("VOICE_DELIVERY_MODE", "strict").strip().lower(),
            avatar_enabled=os.getenv("VOICE_AVATAR_ENABLED", "false").strip().lower() == "true",
            avatar_character=os.getenv("VOICE_AVATAR_CHARACTER", "lisa").strip(),
            avatar_style=os.getenv("VOICE_AVATAR_STYLE", "casual-sitting").strip(),
        )

    def application_credentials_path(self) -> Path:
        if not self.graph_application_credentials_file:
            raise ValueError("GRAPH_APPLICATION_CREDENTIALS_FILE fehlt.")
        path = (ROOT / self.graph_application_credentials_file).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError("Die App-Zugangsdaten-Datei muss im lokalen Projekt vorhanden sein.")
        return path

    def application_credentials(self) -> GraphApplicationCredentials:
        values = dotenv_values(self.application_credentials_path(), interpolate=False)
        required = ("GRAPH_TENANT_ID", "GRAPH_APP_CLIENT_ID", "GRAPH_APP_CLIENT_SECRET")
        if any(not values.get(key) for key in required):
            raise ValueError(
                "App-Zugangsdaten benoetigen GRAPH_TENANT_ID, GRAPH_APP_CLIENT_ID "
                "und GRAPH_APP_CLIENT_SECRET."
            )
        tenant_id = values["GRAPH_TENANT_ID"]
        client_id = values["GRAPH_APP_CLIENT_ID"]
        secret = values["GRAPH_APP_CLIENT_SECRET"]
        if (
            not isinstance(tenant_id, str)
            or not isinstance(client_id, str)
            or not isinstance(secret, str)
        ):
            raise ValueError("Ungueltige App-Zugangsdaten.")
        try:
            tenant = UUID(tenant_id)
            client = UUID(client_id)
            expected_tenant = UUID(self.tenant_id)
        except ValueError:
            raise ValueError("Mandant und App-ID muessen gueltige UUIDs sein.") from None
        if tenant != expected_tenant:
            raise ValueError("Die App-Zugangsdaten gehoeren zu einem anderen Mandanten.")
        return GraphApplicationCredentials(str(tenant), str(client), secret)

    def graph_issues(self) -> list[str]:
        issues = [] if self.tenant_id else ["AZURE_TENANT_ID fehlt"]
        if self.graph_auth_mode == "delegated":
            if not self.graph_client_id:
                issues.append("GRAPH_CLIENT_ID fehlt")
        elif self.graph_auth_mode == "application":
            try:
                self.application_credentials_path()
            except (ValueError, OSError) as error:
                issues.append(
                    str(error)
                    if isinstance(error, ValueError)
                    else "Die App-Zugangsdaten-Datei ist nicht zugreifbar."
                )
        else:
            issues.append("GRAPH_AUTH_MODE muss delegated oder application sein.")
        return issues

    def folder_issues(self) -> list[str]:
        issues = []
        references = []
        roles = (
            ("INPUT", self.input_url, self.input_drive_id, self.input_folder_id),
            ("OUTPUT", self.output_url, self.output_drive_id, self.output_folder_id),
        )
        for role, url, drive_id, item_id in roles:
            name = f"SHAREPOINT_{role}_FOLDER_URL"
            if not url:
                issues.append(f"{name} fehlt")
                if bool(drive_id) != bool(item_id):
                    issues.append(
                        f"SHAREPOINT_{role}_DRIVE_ID und SHAREPOINT_{role}_FOLDER_ID "
                        "muessen gemeinsam konfiguriert sein."
                    )
                continue
            try:
                references.append(folder_reference(url, drive_id=drive_id, item_id=item_id))
            except ValueError as error:
                issues.append(f"{name}: {error}")
        if len(references) == 2:
            first, second = references
            same_link = (
                first.sharing
                and second.sharing
                and (first.host, first.path) == (second.host, second.path)
            )
            canonical_overlap = (
                not first.sharing
                and not second.sharing
                and folder_paths_overlap((first.host, first.path), (second.host, second.path))
            )
            same_ids = self.input_drive_id and (
                (self.input_drive_id, self.input_folder_id)
                == (self.output_drive_id, self.output_folder_id)
            )
            if same_link or canonical_overlap or same_ids:
                issues.append("Eingabe- und Ausgabeordner muessen getrennt sein.")
        return issues

    def issues(self) -> list[str]:
        required = {
            "FOUNDRY_PROJECT_ENDPOINT": self.project_endpoint,
            "VOICELIVE_ENDPOINT": self.voice_endpoint,
        }
        issues = [f"{name} fehlt" for name, value in required.items() if not value]
        issues.extend(self.graph_issues())
        if self.avatar_enabled:
            for name, value in (
                ("VOICE_AVATAR_CHARACTER", self.avatar_character),
                ("VOICE_AVATAR_STYLE", self.avatar_style),
            ):
                if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
                    issues.append(f"{name} muss eine gueltige Standard-Avatar-Bezeichnung sein.")
        if self.voice_delivery_mode not in ("strict", "streaming"):
            issues.append("VOICE_DELIVERY_MODE muss strict oder streaming sein.")
        issues.extend(self.folder_issues())
        for endpoint in (self.project_endpoint, self.voice_endpoint):
            if endpoint:
                parsed = urlsplit(endpoint)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or not parsed.hostname.endswith(
                        (".ai.azure.com", ".cognitiveservices.azure.com")
                    )
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                ):
                    issues.append(
                        "Foundry und Voice Live benoetigen gueltige Azure-HTTPS-Endpunkte."
                    )
        return issues
