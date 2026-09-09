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
    document: bytes | None = None
    result: dict | None = None
    phase: str = "conversation"
    voice_connected: bool = False
    draft_editing: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_turn(self, text: str):
        if len(self.user_turns) >= 30 or sum(map(len, self.user_turns)) + len(text) > 30_000:
            raise ServiceError("Sitzungslimit erreicht. Bitte Zusammenfassung erstellen.")
        if (datetime.now(UTC) - self.created_at).total_seconds() > 1800:
            raise ServiceError("Die Sitzung ist auf 30 Minuten begrenzt. Bitte abschliessen.")
        self.user_turns.append(text)

    def set_draft(self, summary: OpinionSummary):
        with self.lock:
            if self.document is not None:
                raise ServiceError("Die freigegebene Version ist bereits eingefroren.")
            self.draft = summary.model_copy(deep=True)
            self.draft_version += 1
            self.phase = "review"
            self.draft_editing = False

    def save(self, graph: Graph, version: int) -> dict:
        with self.lock:
            if self.draft_editing or not self.draft or self.phase not in ("review", "saving", "saved") or version != self.draft_version:
                raise ServiceError("Keine passende, gepruefte Zusammenfassung vorhanden.")
            if self.result:
                return self.result
            if self.document is None:
                self.document = render_summary(
                    self.draft, sources=self.corpus.sources, owner=self.owner["displayName"],
                    created_at=datetime.now(UTC),
                )
            self.phase = "saving"
            filename = f"meinung-{self.session_id}-v{version}.docx"
            try:
                item = graph.upload(self.output, filename, self.document)
                self.result = {
                    "filename": filename, "item_id": item["id"],
                    "drive_id": self.output.drive_id, "url": item["webUrl"],
                    "destination": "sharepoint", "version": version,
                }
                self.phase = "saved"
                return self.result
            except Exception:
                self.phase = "review"
                raise