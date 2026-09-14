"""Post-response source attribution for streaming speech; never gates playback."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def attribute_sources(socket, foundry, corpus, user_turns, text, item_id):
    try:
        verdict = await asyncio.to_thread(foundry.verify_answer, text, corpus, user_turns)
        sources = (
            [reference.model_dump() for reference in verdict.sources] if verdict.supported else []
        )
        state = "checked" if verdict.supported else "unsupported"
    except Exception as error:
        logger.warning("Post-response source check failed (%s).", type(error).__name__)
        sources, state = [], "failed"
    await socket.send_json(
        {
            "type": "assistant_sources",
            "item_id": item_id,
            "sources": sources,
            "source_status": state,
        }
    )
