import hashlib
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlsplit

import httpx
from azure.identity import DeviceCodeCredential

from app.config import Settings, folder_url

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = [
    "https://graph.microsoft.com/Files.ReadWrite.All",
    "https://graph.microsoft.com/Sites.Read.All",
    "https://graph.microsoft.com/User.Read",
]
logger = logging.getLogger(__name__)


class ServiceError(RuntimeError):
    pass


class GraphAuth:
    def __init__(self, settings: Settings):
        self.lock = threading.Lock()
        self.state: dict = {"status": "signed_out"}
        self.owner: dict | None = None
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
                return dict(self.state)
            self.state = {"status": "starting"}
        threading.Thread(target=self.authenticate, daemon=True).start()
        return self.snapshot()

    def authenticate(self):
        try:
            self.credential.authenticate(scopes=SCOPES)
            owner = Graph(self).request("GET", "/me?$select=id,displayName")
            with self.lock:
                self.owner = owner
                self.state = {"status": "signed_in", "name": owner["displayName"]}
        except Exception as error:
            logger.error("Graph authentication failed: %s", type(error).__name__)
            with self.lock:
                self.state = {
                    "status": "error",
                    "message": "Anmeldung fehlgeschlagen. App-ID, Mandant und Graph-Einwilligung pruefen.",
                }

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.state)

    def token(self) -> str:
        try:
            return self.credential.get_token(*SCOPES).token
        except Exception as error:
            raise ServiceError("Microsoft-365-Anmeldung erforderlich oder abgelaufen.") from error


@dataclass(frozen=True)
class Folder:
    drive_id: str
    item_id: str
    url: str


class Graph:
    def __init__(self, auth: GraphAuth):
        self.auth = auth

    def request(self, method: str, path: str, *, body=None, missing_ok=False):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Graph requests must use relative paths")
        try:
            with httpx.Client(timeout=45) as client:
                response = client.request(
                    method,
                    GRAPH + path,
                    headers={"Authorization": f"Bearer {self.auth.token()}"},
                    json=body,
                )
            if response.status_code == 404 and missing_ok:
                return None
            if response.is_error:
                request_id = response.headers.get("request-id", "unbekannt")
                logger.warning("Graph HTTP %s; request-id %s", response.status_code, request_id)
                raise ServiceError(f"Graph HTTP {response.status_code}; Request-ID: {request_id}")
            return response.json() if response.content else {}
        except httpx.RequestError as error:
            raise ServiceError("Graph ist nicht erreichbar oder hat das Zeitlimit ueberschritten.") from error

    def resolve_folder(self, url: str) -> Folder:
        host, path = folder_url(url)
        site_path = "/".join(path.split("/")[:3])
        site = self.request("GET", f"/sites/{host}:{quote(site_path, safe='/')}")
        libraries = self.request("GET", f"/sites/{site['id']}/drives")
        while True:
            for library in libraries["value"]:
                _, root = folder_url(library["webUrl"] + "/placeholder")
                root = root.removesuffix("/placeholder")
                if path.casefold().startswith(root.casefold() + "/"):
                    relative = quote(path[len(root) + 1 :], safe="/")
                    item = self.request("GET", f"/drives/{library['id']}/root:/{relative}")
                    if "folder" not in item:
                        raise ServiceError("Die konfigurierte Adresse ist kein Ordner.")
                    return Folder(library["id"], item["id"], item["webUrl"])
            next_url = libraries.get("@odata.nextLink")
            if not next_url:
                break
            if not next_url.startswith(GRAPH + "/"):
                raise ServiceError("Ungueltige Graph-Folgeseite.")
            libraries = self.request("GET", next_url[len(GRAPH) :])
        raise ServiceError("Die Dokumentbibliothek wurde nicht gefunden.")

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
        metadata = self.request("GET", f"/drives/{folder.drive_id}/items/{item['id']}")
        url = metadata.get("@microsoft.graph.downloadUrl", "")
        self.validate_transfer_url(url)
        content = bytearray()
        try:
            with httpx.stream("GET", url, timeout=45) as response:
                if response.status_code != 200:
                    raise ServiceError(f"Dateidownload fehlgeschlagen: HTTP {response.status_code}")
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
            or not parsed.hostname.endswith((".sharepoint.com", ".1drv.com", ".sharepointonline.com"))
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ServiceError("Nicht unterstuetzte Graph-Dateiuebertragungsadresse.")

    def upload(self, folder: Folder, filename: str, content: bytes) -> dict:
        existing = self.child(folder, filename, missing_ok=True)
        if existing:
            if hashlib.sha256(self.download(folder, existing)).digest() != hashlib.sha256(content).digest():
                raise ServiceError("Eine andere Datei belegt diesen Namen; nichts wurde ueberschrieben.")
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
                raise ServiceError(f"Upload nicht bestaetigt: HTTP {response.status_code}. Erneut versuchen.")
            item = response.json()
            if not item.get("id") or not item.get("webUrl") or item.get("size") != len(content):
                raise ServiceError("Uploadantwort unvollstaendig; Speicherung nicht bestaetigt.")
            return item
        except httpx.RequestError as error:
            raise ServiceError("Upload unterbrochen. Derselbe Speichervorgang kann wiederholt werden.") from error