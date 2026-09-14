import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.export import SourceReference
from app.source_attribution import attribute_sources


@pytest.mark.parametrize("supported", [True, False])
def test_source_result_is_bound_to_original_item_and_not_spoken(supported):
    socket = SimpleNamespace(send_json=AsyncMock())
    foundry = SimpleNamespace(
        verify_answer=lambda *args: SimpleNamespace(
            supported=supported, sources=[SourceReference(document_id="D01", page=1)]
        )
    )
    asyncio.run(attribute_sources(socket, foundry, None, ["User"], "Answer", "original-item"))
    message = socket.send_json.call_args.args[0]
    assert message["type"] == "assistant_sources"
    assert message["item_id"] == "original-item"
    assert message["source_status"] == ("checked" if supported else "unsupported")
    assert bool(message["sources"]) is supported
    assert "audio" not in message


def test_source_failure_is_visible_and_has_no_invented_references():
    def failure(*args):
        raise RuntimeError("sensitive private data")

    socket = SimpleNamespace(send_json=AsyncMock())
    asyncio.run(
        attribute_sources(
            socket, SimpleNamespace(verify_answer=failure), None, [], "Answer", "item"
        )
    )
    message = socket.send_json.call_args.args[0]
    assert message["source_status"] == "failed" and message["sources"] == []
    assert "sensitive" not in str(message)
