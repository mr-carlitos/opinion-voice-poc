from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.foundry import Foundry
from app.graph import ServiceError
from app.grounding import Corpus


def test_summary_uses_regional_model_and_existing_conversation_without_agent_override():
    foundry = Foundry.__new__(Foundry)
    foundry.settings = SimpleNamespace(model="gpt-5.1", agent_name="demo")
    foundry.client = SimpleNamespace(responses=Mock())
    foundry.client.responses.create.return_value = SimpleNamespace(
        status="completed",
        output_text='{"topic":"Pilot","haltung":"Unentschieden",'
        '"offene_fragen":[],"gegenpositionen":[],"sources":[]}',
    )
    corpus = Corpus("[]", {}, {}, {})
    foundry.validate_summary = Mock()
    summary = foundry.summary("existing-conversation", corpus, user_turns=[])
    foundry.validate_summary.assert_called_once_with(summary, corpus, [])
    assert summary.haltung == "Unentschieden"
    arguments = foundry.client.responses.create.call_args.kwargs
    assert arguments["model"] == "gpt-5.1"
    assert arguments["conversation"] == "existing-conversation"
    assert arguments["instructions"]
    assert arguments["text"]["format"]["strict"] is True
    assert "extra_body" not in arguments
    assert arguments["truncation"] == "disabled"


def test_incomplete_summary_is_not_returned():
    foundry = Foundry.__new__(Foundry)
    foundry.settings = SimpleNamespace(model="gpt-5.1")
    foundry.client = SimpleNamespace(responses=Mock())
    foundry.client.responses.create.return_value = SimpleNamespace(status="incomplete")
    with pytest.raises(ServiceError, match="vollstaendig"):
        foundry.summary("existing-conversation", Corpus("[]", {}, {}, {}))


def test_evidence_uses_complete_corpus_without_mutating_conversation():
    import json

    foundry = Foundry.__new__(Foundry)
    foundry.settings = SimpleNamespace(model="gpt-5.1")
    foundry.client = SimpleNamespace(responses=Mock())
    foundry.client.responses.create.return_value = SimpleNamespace(
        status="completed",
        output_text='{"supported":true,"sources":[]}',
    )
    corpus = Corpus(
        '[{"document_id":"A","text":"First"},{"document_id":"B","text":"Second"}]', {}, {}, {}
    )
    assert foundry.verify_answer("Eine offene Frage?", corpus, ["Meine Haltung"]).supported
    arguments = foundry.client.responses.create.call_args.kwargs
    data = json.loads(arguments["input"])
    assert data["corpus"] == json.loads(corpus.context)
    assert data["user_turns"] == ["Meine Haltung"]
    assert arguments["store"] is False
    assert arguments["truncation"] == "disabled"
    assert arguments["model"] == "gpt-5.1"
    assert "conversation" not in arguments


@pytest.mark.parametrize(
    "flag", ["factual_claims_supported", "position_faithful", "sources_adequate", None]
)
def test_summary_semantic_validation_blocks_any_failed_dimension(flag):
    import json
    from app.export import OpinionSummary

    foundry = Foundry.__new__(Foundry)
    foundry.settings = SimpleNamespace(model="gpt-5.1")
    foundry.client = SimpleNamespace(responses=Mock())
    verdict = dict(factual_claims_supported=True, position_faithful=True, sources_adequate=True)
    if flag:
        verdict[flag] = False
    foundry.client.responses.create.return_value = SimpleNamespace(
        status="completed", output_text=json.dumps(verdict)
    )
    args = (OpinionSummary(topic="Pilot", haltung="Meine Praeferenz"), Corpus("[]", {}, {}, {}), [])
    if flag:
        with pytest.raises(ServiceError, match="nicht freigegeben"):
            foundry.validate_summary(*args, user_edited=True)
    else:
        foundry.validate_summary(*args, user_edited=True)
    kwargs = foundry.client.responses.create.call_args.kwargs
    assert kwargs["store"] is False and "conversation" not in kwargs
    assert json.loads(kwargs["input"])["user_edited"] is True
    assert kwargs["model"] == "gpt-5.1"
