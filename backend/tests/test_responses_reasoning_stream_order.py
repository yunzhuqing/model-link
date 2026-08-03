"""
Regression test: Responses API (/v1/responses) reasoning summary events must be
emitted in the canonical order:

    response.output_item.added           (reasoning)
    response.reasoning_summary_part.added
    response.reasoning_summary_text.delta *
    response.reasoning_summary_text.done
    response.reasoning_summary_part.done
    response.output_item.done            (reasoning)

Every reasoning item must be wrapped by exactly ONE output_item.added / done
pair, and every reasoning item must reference a single consistent item_id.

The adapter accumulates reasoning content from `delta_reasoning_content` chunks
(streamed by OpenAI/DeepSeek/Bailian/Volcengine/Azure providers) and synthesizes
the whole sequence itself — providers must NOT forward reasoning_summary done
events verbatim, otherwise the done events would be duplicated with a
mismatched item_id (see azure_provider / volcengine/base.py).

Run: cd backend && uv run pytest test_responses_reasoning_stream_order.py -q
"""
import asyncio
import json
from typing import AsyncGenerator, List

from app.abstraction.chat import FinishReason, UsageInfo
from app.abstraction.streaming import StreamChunk
from app.adapters.responses_adapter import OpenAIResponsesAdapter


def _collect_sse(chunks: List[StreamChunk]) -> List[str]:
    """Drive create_stream_response and return the raw SSE pieces in order."""
    adapter = OpenAIResponsesAdapter()

    async def gen() -> AsyncGenerator[StreamChunk, None]:
        for c in chunks:
            yield c

    async def run() -> List[str]:
        response = adapter.create_stream_response(gen(), model_name="m")
        body = response.response  # the async generator yield function
        out: List[str] = []
        async for piece in body:
            out.append(piece)
        return out

    return asyncio.run(run())


def _events(sse_pieces: List[str]) -> List[tuple]:
    """Return [(event_type, data_dict), ...] in order, skipping [DONE]."""
    out: List[tuple] = []
    for piece in sse_pieces:
        ev = None
        for line in piece.splitlines():
            if line.startswith("event: "):
                ev = line[len("event: "):]
            elif line.startswith("data: "):
                raw = line[len("data: "):].strip()
                if raw == "[DONE]":
                    ev = None
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = None
                if ev and data:
                    out.append((ev, data))
    return out


def _types(events: List[tuple]) -> List[str]:
    return [ev for ev, _ in events]


def test_reasoning_then_text_emits_canonical_order():
    """Reasoning deltas → text → finish must emit the reasoning sequence in the
    exact canonical order, wrapped by one output_item.added/done pair, followed
    by the message item."""
    usage = UsageInfo(prompt_tokens=10, completion_tokens=20)

    chunks = [
        StreamChunk(id="resp_1", model="m", delta_reasoning_content="Let me think"),
        StreamChunk(id="resp_1", model="m", delta_reasoning_content=" about this."),
        StreamChunk(id="resp_1", model="m", delta_content="The answer is 42."),
        StreamChunk(id="resp_1", model="m",
                    finish_reason=FinishReason.STOP, usage=usage),
    ]

    sse = _collect_sse(chunks)
    events = _events(sse)
    types = _types(events)

    # The reasoning item must be wrapped by exactly one output_item.added/done pair.
    assert types.count("response.output_item.added") == 2, types  # reasoning + message
    assert types.count("response.output_item.done") == 2, types   # reasoning + message

    # Locate the reasoning item by its output_item.added payload (not index 0,
    # which is response.created / response.in_progress).
    rs_added = next(
        (ev, data) for ev, data in events
        if ev == "response.output_item.added"
        and data.get("item", {}).get("type") == "reasoning"
    )
    assert rs_added[1]["item"]["type"] == "reasoning", rs_added

    # Canonical reasoning sequence: extract the slice from the reasoning
    # output_item.added up to (and including) its output_item.done.
    r = _types(events)
    start = r.index("response.output_item.added")
    done_idx = r.index("response.output_item.done", start)
    reasoning_slice = types[start:done_idx + 1]
    assert reasoning_slice == [
        "response.output_item.added",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.done",
        "response.reasoning_summary_part.done",
        "response.output_item.done",
    ], reasoning_slice

    # Exactly one done sequence — no duplicates.
    assert types.count("response.reasoning_summary_text.done") == 1, types
    assert types.count("response.reasoning_summary_part.done") == 1, types

    # A single consistent reasoning item_id across all reasoning events.
    rs_id = rs_added[1]["item"]["id"]
    for ev, data in events[start:done_idx + 1]:
        if ev == "response.output_item.added":
            assert data["item"]["id"] == rs_id, (ev, data)
        elif ev == "response.output_item.done":
            assert data["item"]["id"] == rs_id, (ev, data)
            assert data["item"]["type"] == "reasoning", data
        else:
            assert data.get("item_id") == rs_id, (ev, data)

    # Reasoning done closes BEFORE the message item starts.
    msg_start = r.index("response.output_item.added", done_idx + 1)
    assert r.index("response.output_item.done") < msg_start, types
    assert types[msg_start:] == [
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ], types[msg_start:]


def test_reasoning_only_closes_at_finish():
    """A response with reasoning but no text must still emit output_item.done."""
    usage = UsageInfo(prompt_tokens=5, completion_tokens=15)

    chunks = [
        StreamChunk(id="resp_2", model="m", delta_reasoning_content="thinking..."),
        StreamChunk(id="resp_2", model="m",
                    finish_reason=FinishReason.STOP, usage=usage),
    ]

    sse = _collect_sse(chunks)
    events = _events(sse)
    types = _types(events)

    start = types.index("response.output_item.added")
    done_idx = types.index("response.output_item.done", start)
    reasoning_slice = types[start:done_idx + 1]
    assert reasoning_slice == [
        "response.output_item.added",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.done",
        "response.reasoning_summary_part.done",
        "response.output_item.done",
    ], reasoning_slice

    # No message events for a reasoning-only response.
    assert "response.output_text.delta" not in types, types
    assert types.count("response.output_item.done") == 1, types


if __name__ == "__main__":
    test_reasoning_then_text_emits_canonical_order()
    test_reasoning_only_closes_at_finish()
    print("\nAll Responses API reasoning stream order tests passed.")
