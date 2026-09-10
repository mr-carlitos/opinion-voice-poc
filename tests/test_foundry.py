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
    summary = foundry.summary("existing-conversation", corpus)
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
