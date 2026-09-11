import base64
import logging
import re
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlsplit

import httpx
from azure.identity import ClientSecretCredential, DeviceCodeCredential

from app.config import (
    Settings,
    folder_paths_overlap,
    folder_reference,
    folder_url,
    validate_graph_id,
)
from app.document_integrity import stored_content_matches
from app.graph_permissions import GRAPH_APPLICATION_SCOPE, GRAPH_SCOPES

GRAPH = "https://graph.microsoft.com/v1.0"
logger = logging.getLogger(__name__)


class _HideSharingRequests(logging.Filter):
    def filter(self, record):
        # Sharing tokens and preauthenticated file-transfer URLs are credentials.
        message = record.getMessage()
        return not any(
            marker in message
            for marker in (
                "/shares/u!",
                ".sharepoint.com/",
                ".sharepointonline.com/",
                ".1drv.com/",
            )
        )


logging.getLogger("httpx").addFilter(_HideSharingRequests())


class ServiceError(RuntimeError):
    pass


class GraphHTTPError(ServiceError):
    def __init__(self, response: httpx.Response):
        self.status_code = response.status_code
        self.codes: list[str] = []
        request_id = response.headers.get("request-id")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        detail = payload.get("error") if isinstance(payload, dict) else None
        for _ in range(8):
            if not isinstance(detail, dict):
                break
            code = detail.get("code")
            if (
                isinstance(code, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", code)
                and code not in self.codes
            ):
                self.codes.append(code)
            if not request_id:
                request_id = detail.get("request-id")
            detail = detail.get("innerError", detail.get("innererror"))
        if (
            re.search(
                r'\berror\s*=\s*"insufficient_claims"',
                response.headers.get("www-authenticate", ""),
                re.IGNORECASE,
            )
            and "insufficient_claims" not in self.codes
        ):
            self.codes.append("insufficient_claims")
        self.request_id = (
            request_id
            if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9-]{1,128}", request_id)
            else "unavailable"
        )
        codes = ", ".join(self.codes) or "error code unavailable"
        # Do not include provider messages or request URLs: they can contain sharing credentials.
        super().__init__(f"Graph HTTP {self.status_code} ({codes}); Request-ID: {self.request_id}")


class GraphAuth:
    def __init__(self, settings: Settings):
        if settings.graph_auth_mode not in ("delegated", "application"):
            raise ValueError("Ungueltiger Graph-Authentifizierungsmodus.")
        self.settings = settings
        self.mode = settings.graph_auth_mode
        self.lock = threading.Lock()
        self.state: dict = {"status": "signed_out"}
        self.owner: dict | None = None
        self.credential: DeviceCodeCredential | None = None
        self.application_credential: ClientSecretCredential | None = None
        if self.mode == "delegated":
            self.credential = DeviceCodeCredential(
                tenant_id=settings.tenant_id,
                client_id=settings.graph_client_id,
                prompt_callback=self.prompt,
                disable_automatic_authentication=True,
                timeout=600,
            )

    def prompt(self, verification_uri: str, user_code: str, expires_on: datetime):
        with self.lock:
            self.state = {
                "status": "pending",
                "verification_uri": verification_uri,
                "user_code": user_code,
                "expires_at": expires_on.isoformat(),
            }

    def start(self) -> dict:
        with self.lock:
            if self.state["status"] in ("starting", "pending", "signed_in"):
                return {"mode": self.mode, **self.state}
            self.state = {"status": "starting"}
        threading.Thread(target=self.authenticate, daemon=True).start()
        return self.snapshot()

    def authenticate(self):
        try:
            if self.mode == "application":
                credentials = self.settings.application_credentials()
                if self.application_credential is not None:
                    self.application_credential.close()
                self.application_credential = ClientSecretCredential(
                    credentials.tenant_id, credentials.client_id, credentials.secret
                )
                self.application_credential.get_token(GRAPH_APPLICATION_SCOPE)
                owner = {
                    "id": f"application:{credentials.tenant_id}:{credentials.client_id}",
                    "displayName": "Lokale Demo (Anwendungsidentitaet)",
                }
            else:
                if self.credential is None:
                    raise ServiceError("Delegierte Anmeldung ist nicht konfiguriert.")
                self.credential.authenticate(scopes=GRAPH_SCOPES)
                owner = Graph(self).request("GET", "/me?$select=id,displayName")
            with self.lock:
                self.owner = owner
                self.state = {"status": "signed_in", "name": owner["displayName"]}
        except Exception as error:
            logger.error("Graph authentication failed: %s", type(error).__name__)
            code = re.search(r"\bAADSTS[0-9]+\b", str(error))
            detail = f" ({code.group(0)})" if code else f" ({type(error).__name__})"
            with self.lock:
                self.owner = None
                self.state = {
                    "status": "error",
                    "message": (
                        "App-Authentifizierung fehlgeschlagen"
                        if self.mode == "application"
                        else "Anmeldung fehlgeschlagen"
                    )
                    + detail
                    + ". App-ID, Mandant und Graph-Einwilligung pruefen.",
                }

    def snapshot(self) -> dict:
        with self.lock:
            return {"mode": self.mode, **self.state}

    def token(self) -> str:
        try:
            if self.mode == "application":
                if self.application_credential is None:
                    raise ServiceError("Bitte zuerst den App-Zugriff verbinden.")
                return self.application_credential.get_token(GRAPH_APPLICATION_SCOPE).token
            if self.credential is None:
                raise ServiceError("Delegierte Anmeldung ist nicht konfiguriert.")
            return self.credential.get_token(*GRAPH_SCOPES).token
        except Exception as error:
            raise ServiceError(
                "SharePoint-Authentifizierung fehlgeschlagen; Verbindung und Zugangsdaten pruefen."
            ) from error


@dataclass(frozen=True)
class Folder:
    drive_id: str
    item_id: str
    url: str


def ensure_separate_folders(source: Folder, output: Folder):
    if (source.drive_id, source.item_id) == (output.drive_id, output.item_id):
        raise ServiceError("Eingabe und Ausgabe zeigen auf denselben Ordner.")
    try:
        overlap = folder_paths_overlap(folder_url(source.url), folder_url(output.url))
    except ValueError:
        raise ServiceError(
            "Graph hat keine gueltigen kanonischen Ordneradressen geliefert."
        ) from None
    if overlap:
        raise ServiceError("Eingabe- und Ausgabeordner duerfen sich nicht ueberlappen.")


class Graph:
    def __init__(self, auth: GraphAuth):
        self.auth = auth
        self._client: httpx.Client | None = None

    def __enter__(self):
        if self._client is not None:
            raise RuntimeError("Graph connection scope is already open.")
        self._client = httpx.Client(timeout=45)
        return self

    def __exit__(self, *args):
        if self._client is not None:
            self._client.close()
            self._client = None

    def _connection(self):
        return nullcontext(self._client) if self._client is not None else httpx.Client(timeout=45)

    def request(self, method: str, path: str, *, body=None, missing_ok=False):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Graph requests must use relative paths")
        try:
            with self._connection() as client:
                response = client.request(
                    method,
                    GRAPH + path,
                    headers={"Authorization": f"Bearer {self.auth.token()}"},
                    json=body,
                )
            if response.status_code == 404 and missing_ok:
                return None
            if response.is_error:
                error = GraphHTTPError(response)
                logger.warning("%s", error)
                raise error
            return response.json() if response.content else {}
        except httpx.RequestError as error:
            raise ServiceError(
                "Graph ist nicht erreichbar oder hat das Zeitlimit ueberschritten."
            ) from error

    def resolve_folder(self, url: str, *, drive_id: str = "", item_id: str = "") -> Folder:
        try:
            reference = folder_reference(url, drive_id=drive_id, item_id=item_id)
        except ValueError as error:
            raise ServiceError(str(error)) from None
        if reference.sharing:
            token = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
            try:
                item = self.request("GET", f"/shares/u!{token}/driveItem")
            except ServiceError as error:
                raise error from None
        else:
            item = self.request(
                "GET", f"/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}"
            )
        if (
            not isinstance(item, dict)
            or "remoteItem" in item
            or not isinstance(item.get("folder"), dict)
            or "file" in item
        ):
            raise ServiceError(
                "Die konfigurierte Adresse ist kein direkter Ordner (keine Verknuepfung)."
            )
        parent = item.get("parentReference")
        if not isinstance(parent, dict):
            raise ServiceError("Graph-Ordnerantwort enthaelt keine Laufwerk-ID.")
        try:
            validate_graph_id(item.get("id"))
            validate_graph_id(parent.get("driveId"))
            canonical_host, canonical_path = folder_url(item.get("webUrl"))
        except ValueError:
            raise ServiceError(
                "Graph-Ordnerantwort enthaelt ungueltige IDs oder Ordneradresse."
            ) from None
        if canonical_host != reference.host:
            raise ServiceError("Graph-Ordner liegt ausserhalb des konfigurierten SharePoint-Hosts.")
        if not reference.sharing and (
            canonical_path.casefold() != reference.path.casefold()
            or parent["driveId"] != drive_id
            or item["id"] != item_id
        ):
            raise ServiceError(
                "Graph-Ordner stimmt nicht mit konfigurierter Adresse und IDs ueberein."
            )
        return Folder(parent["driveId"], item["id"], item["webUrl"])

    def child(self, folder: Folder, filename: str, *, missing_ok=False):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", filename) or filename.startswith("."):
            raise ValueError("Ungueltiger Dateiname")
        return self.request(
            "GET",
            f"/drives/{folder.drive_id}/items/{folder.item_id}:/{quote(filename)}",
            missing_ok=missing_ok,
        )

    def download(self, folder: Folder, item: dict, *, limit=2_000_000) -> bytes:
        if item.get("size", limit + 1) > limit:
            raise ServiceError("Datei ueberschreitet das PoC-Groessenlimit.")
        # Use the URL from the just-fetched item immediately; never cache or persist it.
        metadata = (
            item
            if item.get("@microsoft.graph.downloadUrl")
            else self.request("GET", f"/drives/{folder.drive_id}/items/{item['id']}")
        )
        url = metadata.get("@microsoft.graph.downloadUrl", "")
        self.validate_transfer_url(url)
        content = bytearray()
        try:
            with self._connection() as client:
                with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise ServiceError(
                            f"Dateidownload fehlgeschlagen: HTTP {response.status_code}"
                        )
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > limit:
                            raise ServiceError("Datei ueberschreitet das PoC-Groessenlimit.")
        except httpx.RequestError as error:
            raise ServiceError("Dateidownload unterbrochen; bitte erneut versuchen.") from error
        return bytes(content)

    @staticmethod
    def validate_transfer_url(url: str):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(
                (".sharepoint.com", ".1drv.com", ".sharepointonline.com")
            )
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ServiceError("Nicht unterstuetzte Graph-Dateiuebertragungsadresse.")

    def upload(self, folder: Folder, filename: str, content: bytes) -> dict:
        existing = self.child(folder, filename, missing_ok=True)
        if existing:
            if not stored_content_matches(filename, content, self.download(folder, existing)):
                raise ServiceError(
                    "Eine andere Datei belegt diesen Namen; nichts wurde ueberschrieben."
                )
            return existing
        upload = self.request(
            "POST",
            f"/drives/{folder.drive_id}/items/{folder.item_id}:/{quote(filename)}:/createUploadSession",
            body={"item": {"@microsoft.graph.conflictBehavior": "fail", "name": filename}},
        )
        self.validate_transfer_url(upload["uploadUrl"])
        try:
            with httpx.Client(timeout=60) as client:
                response = client.put(
                    upload["uploadUrl"],
                    content=content,
                    headers={"Content-Range": f"bytes 0-{len(content) - 1}/{len(content)}"},
                )
            if response.status_code not in (200, 201):
                raise ServiceError(
                    f"Upload nicht bestaetigt: HTTP {response.status_code}. Erneut versuchen."
                )
            item = response.json()
            if (
                not item.get("id")
                or not item.get("webUrl")
                or not isinstance(item.get("size"), int)
                or item["size"] <= 0
            ):
                raise ServiceError("Uploadantwort unvollstaendig; Speicherung nicht bestaetigt.")
            if filename.lower().endswith(".docx"):
                if not stored_content_matches(filename, content, self.download(folder, item)):
                    raise ServiceError(
                        "Gespeicherter Word-Inhalt weicht vom freigegebenen Entwurf ab."
                    )
            elif item["size"] != len(content):
                raise ServiceError("Uploadgroesse stimmt nicht mit der Quelldatei ueberein.")
            return item
        except httpx.RequestError as error:
            raise ServiceError(
                "Upload unterbrochen. Derselbe Speichervorgang kann wiederholt werden."
            ) from error
