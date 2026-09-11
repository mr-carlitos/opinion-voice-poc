from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.export import OpinionSummary
from app.graph import Folder, ServiceError
from app.grounding import Corpus
from app.sessions import Session


class FakeGraph:
    def __init__(self, failures=0):
        self.failures = failures
        self.uploads = []

    def upload(self, folder, filename, document):
        self.uploads.append((folder, filename, document))
        if self.failures:
            self.failures -= 1
            raise ServiceError("Upload fehlgeschlagen")
        return {"id": "same-item", "webUrl": "https://demo.sharepoint.com/result.docx"}


@pytest.fixture
def session():
    return Session(
        {"id": "demo", "displayName": "App-Identitaet Demo"},
        "conversation",
        Corpus("", {}, {}, {}),
        Folder("drive", "output", "https://demo.sharepoint.com/output"),
    )


def draft(stance="Unentschieden"):
    return OpinionSummary(topic="Pilot", haltung=stance, offene_fragen=["Kosten?"])


def test_draft_creation_and_editing_require_matching_version(session):
    graph = FakeGraph()
    with pytest.raises(ServiceError):
        session.save(graph, 0)
    assert session.set_draft(draft())["version"] == 1
    with pytest.raises(ServiceError):
        session.set_draft(draft())
    session.mark_editing(1)
    with pytest.raises(ServiceError):
        session.save(graph, 1)
    with pytest.raises(ServiceError):
        session.set_draft(draft(), expected_version=0)
    state = session.set_draft(draft("Pilot bevorzugt"), expected_version=1, validation_passed=True)
    assert state["version"] == 2
    assert state["phase"] == "review"
    assert not state["editing"]
    assert not state["frozen"]
    assert not graph.uploads  # Applying a draft is not approval.
    with pytest.raises(ServiceError):
        session.mark_editing(1)
    with pytest.raises(ServiceError):
        session.save(graph, 1)
    assert session.save(graph, 2)["version"] == 2


def test_failed_upload_freezes_exact_bytes_for_retry_and_repeat_save(session):
    graph = FakeGraph(failures=1)
    session.set_draft(draft(), validation_passed=True)
    with pytest.raises(ServiceError, match="Upload fehlgeschlagen"):
        session.save(graph, 1)
    state = session.snapshot()
    assert state["phase"] == "review"
    assert state["frozen"]
    assert state["result"] is None
    with pytest.raises(ServiceError):
        session.mark_editing(1)
    with pytest.raises(ServiceError):
        session.set_draft(draft("Geaendert"), expected_version=1)
    result = session.save(graph, 1)
    assert graph.uploads[0] == graph.uploads[1]
    assert session.save(graph, 1) == result
    assert len(graph.uploads) == 2
    assert session.snapshot()["phase"] == "saved"
    result["item_id"] = "tampered"
    assert session.save(graph, 1)["item_id"] == "same-item"


def test_draft_and_snapshot_are_defensive_copies(session):
    summary = draft()
    state = session.set_draft(summary)
    summary.offene_fragen.append("External mutation")
    state["summary"]["offene_fragen"].append("Snapshot mutation")
    assert session.snapshot()["summary"]["offene_fragen"] == ["Kosten?"]


def test_upload_allows_state_reads_but_rejects_edits_and_serializes_saves(session):
    started, release = Event(), Event()

    class BlockingGraph(FakeGraph):
        def upload(self, *args):
            started.set()
            assert release.wait(5)
            return super().upload(*args)

    graph = BlockingGraph()
    session.set_draft(draft(), validation_passed=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(session.save, graph, 1)
        try:
            assert started.wait(5)
            assert session.snapshot()["phase"] == "saving"
            with pytest.raises(ServiceError):
                session.mark_editing(1)
            with pytest.raises(ServiceError):
                session.set_draft(draft("Race"), expected_version=1)
            second = pool.submit(session.save, graph, 1)
        finally:
            release.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert len(graph.uploads) == 1


def test_unvalidated_or_newly_unvalidated_draft_cannot_be_saved(session):
    graph = FakeGraph()
    session.set_draft(draft())
    assert session.snapshot()["validated"] is False
    with pytest.raises(ServiceError):
        session.save(graph, 1)
    session.set_draft(draft(), expected_version=1, validation_passed=True)
    assert session.snapshot()["validated"] is True
    session.set_draft(draft("Edited"), expected_version=2)
    assert session.snapshot()["validated"] is False
    with pytest.raises(ServiceError):
        session.save(graph, 3)
    assert graph.uploads == []
