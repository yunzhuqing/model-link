"""
Regression test: 百炼 incremental_output 等供应商会把最后一段增量文本和
finish_reason 放在同一个 StreamChunk 里。/v1/messages 路径此前会丢弃这段文本。

运行: cd backend && uv run python test_anthropic_finish_chunk.py
"""
import asyncio
from typing import AsyncGenerator

from app.abstraction.streaming import StreamChunk, StreamEventType
from app.abstraction.chat import UsageInfo, FinishReason
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter


async def _collect_sse(chunks: list[StreamChunk]) -> list[str]:
    adapter = AnthropicMessagesAdapter()

    async def gen() -> AsyncGenerator[StreamChunk, None]:
        for c in chunks:
            yield c

    # create_stream_response returns a Quart Response whose body is the
    # async generator. Pull the underlying generator and drive it directly.
    response = adapter.create_stream_response(gen(), model_name="qwen3.7-plus")
    body = response.response  # the async generator yield function
    out: list[str] = []
    async for piece in body:
        out.append(piece)
    return out


def _events(sse_pieces: list[str]) -> list[str]:
    """Extract the `event: <type>` lines in order."""
    events: list[str] = []
    for piece in sse_pieces:
        for line in piece.splitlines():
            if line.startswith("event: "):
                events.append(line[len("event: "):])
    return events


def _joined_text(sse_pieces: list[str]) -> str:
    """Concatate all text_delta pieces."""
    import json
    text = ""
    for piece in sse_pieces:
        for line in piece.splitlines():
            if line.startswith("data: "):
                try:
                    data = json.loads(line[len("data: "):])
                except Exception:
                    continue
                if data.get("type") == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text += delta.get("text", "")
    return text


async def main() -> None:
    # Simulate a Bailian-style stream: incremental text chunks, then a FINAL
    # chunk that carries the last text fragment AND finish_reason=STOP together.
    usage = UsageInfo(prompt_tokens=10, completion_tokens=20)

    chunks = [
        StreamChunk(id="chatcmpl-1", model="qwen3.7-plus",
                    delta_content="秋天是", is_first_chunk=True),
        StreamChunk(id="chatcmpl-1", model="qwen3.7-plus",
                    delta_content="一个关于"),
        # Final chunk: incremental text + finish_reason bundled (Bailian behavior)
        StreamChunk(id="chatcmpl-1", model="qwen3.7-plus",
                    delta_content="、纯真等主题。",
                    finish_reason=FinishReason.STOP, usage=usage),
    ]

    sse = await _collect_sse(chunks)
    events = _events(sse)
    text = _joined_text(sse)

    print("Event sequence:")
    for e in events:
        print("  ", e)
    print("Joined text:", repr(text))

    # 1. The final fragment must NOT be dropped.
    assert "、纯真等主题。" in text, f"final fragment dropped! got: {text!r}"

    # 2. Full text reassembled.
    assert text == "秋天是一个关于、纯真等主题。", f"unexpected text: {text!r}"

    # 3. Event order must be: message_start, content_block_start,
    #    content_block_delta(s), content_block_stop, message_delta, message_stop.
    assert events[0] == "message_start", events
    assert "content_block_start" in events, events
    assert events[-1] == "message_stop", events
    cbs_idx = events.index("content_block_stop")
    # all content_block_delta must come BEFORE content_block_stop
    for i, e in enumerate(events):
        if e == "content_block_delta":
            assert i < cbs_idx, f"content_block_delta after stop: {events}"
    # message_delta must come after content_block_stop
    md_idx = events.index("message_delta")
    assert md_idx > cbs_idx, f"message_delta before stop: {events}"

    print("\nPASS: final incremental text preserved with correct event order.")

    # --- Scenario 2: MiniMax-style — the ONLY content arrives in the final
    # chunk bundled with finish_reason. Block must be opened for it. ---
    chunks2 = [
        StreamChunk(id="chatcmpl-2", model="qwen3.7-plus",
                    delta_content="hello world",
                    finish_reason=FinishReason.STOP, is_first_chunk=True),
    ]
    sse2 = await _collect_sse(chunks2)
    events2 = _events(sse2)
    text2 = _joined_text(sse2)
    print("\nScenario 2 (single finish chunk):")
    print("Event sequence:")
    for e in events2:
        print("  ", e)
    print("Joined text:", repr(text2))
    assert text2 == "hello world", f"unexpected text: {text2!r}"
    assert events2 == [
        "message_start", "content_block_start", "content_block_delta",
        "content_block_stop", "message_delta", "message_stop",
    ], events2
    print("\nPASS: single finish-chunk content preserved with correct block lifecycle.")

    # --- Scenario 3: Volcengine/Azure-style — the finish chunk carries the
    # FULL assembled text (already streamed) flagged via
    # _skip_content_on_finish_reason=True. It must NOT be re-emitted. ---
    chunks3 = [
        StreamChunk(id="c3", model="m", delta_content="hello "),
        StreamChunk(id="c3", model="m", delta_content="world"),
        StreamChunk(id="c3", model="m",
                    delta_content="hello world",  # full assembled text
                    finish_reason=FinishReason.STOP,
                    _skip_content_on_finish_reason=True),
    ]
    sse3 = await _collect_sse(chunks3)
    events3 = _events(sse3)
    text3 = _joined_text(sse3)
    print("\nScenario 3 (skip-flag full-text finish chunk):")
    print("Joined text:", repr(text3))
    # full text must appear exactly once (from the two deltas), not duplicated
    assert text3 == "hello world", f"unexpected text: {text3!r}"
    assert text3.count("hello world") == 1 or text3 == "hello world"
    # exactly one content_block_start / content_block_stop pair
    assert events3.count("content_block_start") == 1, events3
    assert events3.count("content_block_stop") == 1, events3
    print("PASS: full-text finish chunk (skip flag) not re-emitted on /v1/messages")


if __name__ == "__main__":
    asyncio.run(main())
