"""
Regression test: OpenAIProvider._parse_stream_chunk must forward
delta.reasoning_content into StreamChunk.delta_reasoning_content.

运行: cd backend && uv run python test_openai_stream_reasoning.py
"""
from app.providers import ProviderConfig
from app.providers.openai_provider import OpenAIProvider
from app.abstraction.streaming import StreamEventType


def _make_provider() -> OpenAIProvider:
    cfg = ProviderConfig(name="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
    return OpenAIProvider(cfg)


def test_stream_chunk_parses_reasoning_content():
    p = _make_provider()
    # Simulate a DeepSeek-style streaming delta carrying reasoning_content.
    data = {
        "id": "chatcmpl-1",
        "model": "deepseek-reasoner",
        "created": 1,
        "choices": [{
            "index": 0,
            "delta": {
                "reasoning_content": "let me think...",
                "content": "answer",
            },
            "finish_reason": None,
        }],
    }
    chunk = p._parse_stream_chunk(data, response_id="chatcmpl-1", model="deepseek-reasoner")
    assert chunk is not None
    assert chunk.delta_reasoning_content == "let me think...", chunk
    assert chunk.delta_content == "answer", chunk


def test_stream_chunk_reasoning_only():
    p = _make_provider()
    # Some providers stream reasoning without delta.content in early chunks.
    data = {
        "id": "chatcmpl-2",
        "model": "m",
        "created": 1,
        "choices": [{
            "index": 0,
            "delta": {"reasoning_content": "step 1"},
        }],
    }
    chunk = p._parse_stream_chunk(data, response_id="x", model="m")
    assert chunk is not None
    assert chunk.delta_reasoning_content == "step 1"
    assert chunk.delta_content is None


def test_stream_chunk_no_reasoning_is_none():
    p = _make_provider()
    data = {
        "id": "chatcmpl-3",
        "model": "m",
        "created": 1,
        "choices": [{
            "index": 0,
            "delta": {"content": "hi"},
            "finish_reason": "stop",
        }],
    }
    chunk = p._parse_stream_chunk(data, response_id="x", model="m")
    assert chunk is not None
    assert chunk.delta_reasoning_content is None
    assert chunk.delta_content == "hi"


def test_stream_chunk_to_openai_format_emits_reasoning():
    """Downstream OpenAI SSE format must surface reasoning_content."""
    p = _make_provider()
    data = {
        "id": "chatcmpl-4",
        "model": "m",
        "created": 1,
        "choices": [{
            "index": 0,
            "delta": {"reasoning_content": "think"},
            "finish_reason": None,
        }],
    }
    chunk = p._parse_stream_chunk(data, response_id="x", model="m")
    formatted = chunk.to_openai_format()
    delta = formatted["choices"][0]["delta"]
    assert delta.get("reasoning_content") == "think", formatted


if __name__ == "__main__":
    test_stream_chunk_parses_reasoning_content()
    test_stream_chunk_reasoning_only()
    test_stream_chunk_no_reasoning_is_none()
    test_stream_chunk_to_openai_format_emits_reasoning()
    print("All OpenAI streaming reasoning_content tests passed.")
