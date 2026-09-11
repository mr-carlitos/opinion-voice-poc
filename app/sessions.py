import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.export import OpinionSummary, render_summary
from app.graph import Folder, Graph, ServiceError
from app.grounding import Corpus


@dataclass
class Session:
    owner: dict
    conversation_id: str
    corpus: Corpus
    output: Folder
    session_id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_turns: list[str] = field(default_factory=list)
    draft: OpinionSummary | None = None
    draft_version: int = 0
    validated_version: int = 0
    document: bytes | None = None
    result: dict | None = None
    phase: str = "conversation"
    voice_connected: bool = False
    draft_editing: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    upload_lock: threading.Lock = field(default_factory=threading.Lock)
    avatar_enabled: bool = False

    def add_turn(self, text: str):
        if len(self.user_turns) >= 30 or sum(map(len, self.user_turns)) + len(text) > 30_000:
            raise ServiceError("Sitzungslimit erreicht. Bitte Zusammenfassung erstellen.")
        if (datetime.now(UTC) - self.created_at).total_seconds() > 1800:
            raise ServiceError("Die Sitzung ist auf 30 Minuten begrenzt. Bitte abschliessen.")
        self.user_turns.append(text)

    def _snapshot(self) -> dict:
        return {
            "summary": self.draft.model_dump(mode="json") if self.draft else None,
            "version": self.draft_version,
            "phase": self.phase,
            "editing": self.draft_editing,
            "frozen": self.document is not None,
            "result": dict(self.result) if self.result else None,
            "validated": self.validated_version == self.draft_version and self.draft is not None,
        }

    def snapshot(self) -> dict:
        with self.lock:
            return self._snapshot()

    def mark_editing(self, version: int | None = None):
        with self.lock:
            if self.document is not None or self.phase != "review" or not self.draft:
                raise ServiceError("Der Entwurf kann nicht mehr bearbeitet werden.")
            if version is not None and version != self.draft_version:
                raise ServiceError("Der Entwurf wurde inzwischen geaendert. Bitte neu laden.")
            self.draft_editing = True
            return self._snapshot()

    def set_draft(
        self,
        summary: OpinionSummary,
        *,
        expected_version: int | None = None,
        validation_passed: bool = False,
    ):
        with self.lock:
            if self.document is not None:
                raise ServiceError("Die freigegebene Version ist bereits eingefroren.")
            if expected_version is None:
                if self.phase != "conversation":
                    raise ServiceError("Ein Entwurf ist bereits vorhanden.")
            elif self.phase != "review" or expected_version != self.draft_version:
                raise ServiceError("Der Entwurf wurde inzwischen geaendert. Bitte neu laden.")
            self.draft = summary.model_copy(deep=True)
            self.draft_version += 1
            self.validated_version = self.draft_version if validation_passed else 0
            self.phase = "review"
            self.draft_editing = False
            return self._snapshot()

    def save(self, graph: Graph, version: int) -> dict:
        # Serialize uploads without holding the state lock during network IO.
        with self.upload_lock:
            with self.lock:
                if (
                    self.draft_editing
                    or not self.draft
                    or self.phase not in ("review", "saving", "saved")
                    or version != self.draft_version
                    or self.validated_version != version
                ):
                    raise ServiceError("Keine passende, gepruefte Zusammenfassung vorhanden.")
                if self.result:
                    return dict(self.result)
                if self.document is None:
                    self.document = render_summary(
                        self.draft,
                        sources=self.corpus.sources,
                        owner=self.owner["displayName"],
                        created_at=datetime.now(UTC),
                    )
                self.phase = "saving"
                filename = f"meinung-{self.session_id}-v{version}.docx"
                document = self.document
            try:
                item = graph.upload(self.output, filename, document)
                result = {
                    "filename": filename,
                    "item_id": item["id"],
                    "drive_id": self.output.drive_id,
                    "url": item["webUrl"],
                    "destination": "sharepoint",
                    "version": version,
                }
                with self.lock:
                    self.result = result
                    self.phase = "saved"
                    return dict(result)
            except Exception:
                with self.lock:
                    self.phase = "review"
                raise
