"""
Regression test: Volcengine responses-mode streamed through /v1/chat/completions
must NOT (1) re-emit the full assembled text on the finish chunk, nor (2) emit
two usage chunks. Exactly one usage chunk (with price) is expected.

运行: cd backend && uv run python test_volcengine_responses_chatcompletions.py
"""
import json
from app.providers import ProviderConfig
from app.providers.volcengine.base import VolcengineProvider
from app.abstraction.chat import UsageInfo, FinishReason
from app.abstraction.streaming import StreamChunk, StreamEventType


def _sse_events(sse_str: str) -> list[dict]:
    out = []
    for raw in sse_str.split("\n\n"):
        for line in raw.splitlines():
            if line.startswith("data: "):
                try:
                    out.append(json.loads(line[6:]))
                except Exception:
                    pass
    return out


def _build_completed_chunk():
    """Simulate the response.completed chunk as Volcengine builds it."""
    usage = UsageInfo(prompt_tokens=50, completion_tokens=203, total_tokens=253,
                      reasoning_tokens=147)
    return StreamChunk(
        id="resp_021",
        model="doubao-seed-2-0-pro-260215",
        delta_content="我是豆包，是由字节跳动开发训练的人工智能助手~\n我能帮你做很多事哦",  # full assembled text
        finish_reason=FinishReason.STOP,
        usage=usage,
        event_type=StreamEventType.CONTENT_DELTA,
        _skip_content_on_finish_reason=True,   # the fix
    )


def test_response_completed_chunk_has_skip_flag():
    p = VolcengineProvider(ProviderConfig(name="volcengine", api_key="x", base_url=None))
    completed_event = {
        "type": "response.completed",
        "response": {
            "id": "resp_021",
            "model": "doubao-seed-2-0-pro-260215",
            "status": "completed",
            "created_at": 1784715392,
            "usage": {
                "input_tokens": 50, "output_tokens": 203, "total_tokens": 253,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 147},
            },
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "全文"}]},
            ],
        },
    }
    chunk = p._parse_responses_stream_event("response.completed", completed_event, "resp_021", "m")
    assert chunk is not None
    assert chunk._skip_content_on_finish_reason is True, "finish chunk must set skip flag"
    assert chunk.delta_content == "全文"
    assert chunk.finish_reason == FinishReason.STOP
    assert chunk.usage is not None
    print("PASS: response.completed chunk carries _skip_content_on_finish_reason=True")


def test_finish_chunk_sse_skips_full_text():
    chunk = _build_completed_chunk()
    # Gateway strips inline usage for the chat_completions path (simulated).
    chunk.usage = None
    events = _sse_events(chunk.to_sse("openai"))
    # Exactly one event: the finish chunk with empty delta, no full text.
    assert len(events) == 1, events
    choices = events[0].get("choices", [])
    assert len(choices) == 1
    assert choices[0]["finish_reason"] == "stop"
    # full assembled text must NOT appear in the delta
    delta = choices[0].get("delta", {})
    assert "content" not in delta or delta["content"] == "", delta
    assert "usage" not in events[0], "finish chunk must not carry usage after strip"
    print("PASS: finish chunk SSE has empty delta, no full text, no inline usage")


def test_price_chunk_is_sole_usage():
    chunk = _build_completed_chunk()
    usage = chunk.usage
    # Simulate gateway: calculate_price attaches price to last_usage,
    # then emits a price_chunk (no delta, no finish_reason).
    usage.price = type("P", (), {"to_dict": lambda self: {"payable_amount": 0.003408,
                  "currency": "CNY", "exchange_rate": 7.0}})()
    price_chunk = StreamChunk(id=chunk.id, model=chunk.model, created=chunk.created, usage=usage)
    events = _sse_events(price_chunk.to_sse("openai"))
    assert len(events) == 1, events
    assert events[0].get("choices") == [], events[0]
    assert "usage" in events[0]
    assert events[0]["usage"]["prompt_tokens"] == 50
    assert "price" in events[0]["usage"], "price must be attached"
    print("PASS: price_chunk emits exactly one usage (with price)")


def test_combined_stream_has_one_usage():
    """End-to-end-ish: content deltas + finish chunk (stripped) + price_chunk."""
    all_events = []
    # incremental content
    for txt in ["我是豆包", "，是由字节跳动", "开发训练的"]:
        all_events += _sse_events(StreamChunk(id="r", model="m", delta_content=txt).to_sse("openai"))
    # finish chunk (skip full text, usage stripped by gateway)
    finish = _build_completed_chunk()
    finish.usage = None
    all_events += _sse_events(finish.to_sse("openai"))
    # price chunk (sole usage)
    usage = _build_completed_chunk().usage
    usage.price = type("P", (), {"to_dict": lambda self: {"payable_amount": 0.003}})()
    all_events += _sse_events(StreamChunk(id="r", model="m", usage=usage).to_sse("openai"))

    usage_events = [e for e in all_events if "usage" in e]
    assert len(usage_events) == 1, f"expected exactly 1 usage, got {len(usage_events)}"
    # No event re-emits the full assembled text
    full = "我是豆包，是由字节跳动开发训练的人工智能助手~\n我能帮你做很多事哦"
    for e in all_events:
        for c in e.get("choices", []):
            d = c.get("delta", {})
            assert d.get("content", "") != full, "full text must not be re-emitted"
    print(f"PASS: stream has exactly 1 usage event, no full-text re-emit (total {len(all_events)} events)")


if __name__ == "__main__":
    test_response_completed_chunk_has_skip_flag()
    test_finish_chunk_sse_skips_full_text()
    test_price_chunk_is_sole_usage()
    test_combined_stream_has_one_usage()
    print("\nAll Volcengine chat/completions streaming tests passed.")
