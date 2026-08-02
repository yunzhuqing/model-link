"""
Tests for Responses API `custom_tool_call` / `custom_tool_call_output` support.

Covers:
- Input parsing: custom_tool_call + custom_tool_call_output input items →
  assistant TOOL_CALL / tool TOOL_RESULT messages.
- Lossless round-trip to Responses-API upstreams: build_responses_request
  re-emits the original custom items verbatim (namespace / caller /
  prompt_cache_breakpoint preserved).
- Non-streaming output: a ToolCall with call_type='custom' formats as a
  `custom_tool_call` output item.
- Upstream response parsing: parse_responses_response turns a
  `custom_tool_call` output item into a ToolCall(call_type='custom').
- Streaming output: format_stream_chunk emits response.output_item.added /
  response.custom_tool_call_input.delta / .done / response.output_item.done.

Run: cd backend && uv run pytest test_custom_tool_call.py -q
"""
import json

from app.abstraction.chat import ChatResponse, ChatChoice, FinishReason, UsageInfo
from app.abstraction.messages import Message, MessageRole, ContentType
from app.abstraction.streaming import StreamChunk
from app.abstraction.tools import ToolCall
from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.providers._responses_format import (
    build_responses_request,
    parse_responses_response,
)
from app.providers.openai_provider import OpenAIProvider
from app.providers import ProviderConfig


CUSTOM_CALL_ITEM = {
    "type": "custom_tool_call",
    "id": "ctc_1",
    "name": "my_tool",
    "input": '{"a": 1}',
    "call_id": "call_1",
    "namespace": "my_ns",
    "caller": {"type": "direct"},
}

CUSTOM_CALL_OUTPUT_ITEM = {
    "type": "custom_tool_call_output",
    "id": "ctc_1",
    "caller": {"type": "direct"},
    "call_id": "call_1",
    "output": "the result",
}


def _make_provider() -> OpenAIProvider:
    cfg = ProviderConfig(name="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
    return OpenAIProvider(cfg)


# ── Input parsing ───────────────────────────────────────────────────

def test_custom_tool_call_input_parsed_to_messages():
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [
            {"role": "user", "content": "Please use the custom tool"},
            CUSTOM_CALL_ITEM,
            CUSTOM_CALL_OUTPUT_ITEM,
        ],
    })
    assert len(req.messages) == 3
    assert req.messages[1].role == MessageRole.ASSISTANT
    block = req.messages[1].content[0]
    assert block.type == ContentType.CUSTOM_TOOL_CALL
    assert block.tool_name == "my_tool"
    assert block.tool_arguments == {"a": 1}
    assert block.tool_call_id == "call_1"
    # 独立 ContentType + 固定字段保留 custom 工具元数据
    assert block.namespace == "my_ns"
    assert block.caller == {"type": "direct"}
    assert block.item_id == "ctc_1"
    assert block.input_raw == '{"a": 1}'

    assert req.messages[2].role == MessageRole.TOOL
    tool_block = req.messages[2].content[0]
    assert tool_block.type == ContentType.CUSTOM_TOOL_CALL_OUTPUT
    assert req.messages[2].tool_call_id == "call_1"
    assert tool_block.get_tool_result_text() == "the result"


def test_consecutive_custom_tool_calls_merge_into_one_assistant_message():
    second = dict(CUSTOM_CALL_ITEM, id="ctc_2", call_id="call_2", input='{"b": 2}')
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [CUSTOM_CALL_ITEM, second],
    })
    assert len(req.messages) == 1
    assert req.messages[0].role == MessageRole.ASSISTANT
    assert [b.tool_call_id for b in req.messages[0].content] == ["call_1", "call_2"]


def test_custom_tool_call_output_with_program_caller():
    item = {
        "type": "custom_tool_call_output",
        "id": "ctc_1",
        "caller": {"type": "program", "caller_id": "call_1"},
        "call_id": "call_1",
        "output": [{"type": "input_text", "text": "ok"}],
    }
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [CUSTOM_CALL_ITEM, item],
    })
    assert req.messages[1].role == MessageRole.TOOL
    assert req.messages[1].tool_call_id == "call_1"
    assert req.messages[1].content[0].get_tool_result_text() == "ok"
    assert req.messages[1].content[0].type == ContentType.CUSTOM_TOOL_CALL_OUTPUT
    assert req.messages[1].content[0].caller["type"] == "program"


def test_custom_tool_call_output_falls_back_to_caller_id():
    """兼容旧字段名：无 call_id 时回退到 caller_id / caller.caller_id。"""
    item = {
        "type": "custom_tool_call_output",
        "id": "ctco_1",
        "caller": {"type": "direct"},
        "caller_id": "call_1",
        "output": "result",
    }
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [CUSTOM_CALL_ITEM, item],
    })
    assert req.messages[1].tool_call_id == "call_1"


def test_custom_tool_call_output_with_image_content():
    item = {
        "type": "custom_tool_call_output",
        "id": "ctc_1",
        "caller": {"type": "direct"},
        "caller_id": "call_1",
        "output": [
            {"type": "input_text", "text": "here you go"},
            {"type": "input_image", "image_url": "https://example.com/a.png"},
        ],
    }
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [CUSTOM_CALL_ITEM, item],
    })
    blocks = req.messages[1].content[0].tool_result
    assert isinstance(blocks, list)
    assert any(b.type == ContentType.IMAGE_URL for b in blocks)
    image_block = next(b for b in blocks if b.type == ContentType.IMAGE_URL)
    assert image_block.url == "https://example.com/a.png"


# ── Round-trip to Responses-API upstreams ───────────────────────────

def test_custom_tool_call_output_preserves_prompt_cache_breakpoint():
    item = {
        "type": "custom_tool_call_output",
        "id": "ctc_1",
        "caller": {"type": "direct"},
        "call_id": "call_1",
        "output": [
            {"type": "input_text", "text": "hi", "prompt_cache_breakpoint": {"mode": "explicit"}},
        ],
    }
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [CUSTOM_CALL_ITEM, item],
    })
    body = build_responses_request(req)
    output_item = body["input"][1]
    assert output_item["type"] == "custom_tool_call_output"
    assert output_item["output"] == [
        {"type": "input_text", "text": "hi", "prompt_cache_breakpoint": {"mode": "explicit"}},
    ]


def test_build_responses_request_preserves_message_before_tool_calls():
    """assistant 文本 message 必须排在 custom_tool_call 之前（Responses API 输出顺序）。

    Regression: _message_to_responses_items 曾把工具调用排在 message 之前，导致
    Azure 等上游收到的 input 顺序与客户端发送的不一致。
    """
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [
            {"type": "message", "id": "msg_1", "role": "assistant",
             "content": [{"type": "output_text", "text": ""}]},
            CUSTOM_CALL_ITEM,
            CUSTOM_CALL_OUTPUT_ITEM,
        ],
    })
    body = build_responses_request(req)
    types = [it["type"] for it in body["input"]]
    assert types == ["message", "custom_tool_call", "custom_tool_call_output"]
    assert body["input"][0]["content"] == [{"type": "output_text", "text": ""}]
    assert body["input"][1] == CUSTOM_CALL_ITEM
    assert body["input"][2] == CUSTOM_CALL_OUTPUT_ITEM


def test_build_responses_request_preserves_message_before_function_call():
    """同样约束适用于普通 function_call：message 在 function_call 之前。"""
    fc_item = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "get_weather",
        "arguments": '{"city": "sh"}',
    }
    fc_output = {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "sunny",
    }
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [
            {"type": "message", "id": "msg_1", "role": "assistant",
             "content": [{"type": "output_text", "text": "checking..."}]},
            fc_item,
            fc_output,
        ],
    })
    body = build_responses_request(req)
    types = [it["type"] for it in body["input"]]
    assert types == ["message", "function_call", "function_call_output"]


def test_build_responses_request_round_trips_custom_items():
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [
            {"role": "user", "content": "hi"},
            CUSTOM_CALL_ITEM,
            CUSTOM_CALL_OUTPUT_ITEM,
        ],
    })
    body = build_responses_request(req)
    # [user message, custom_tool_call, custom_tool_call_output]
    assert body["input"][1] == CUSTOM_CALL_ITEM
    assert body["input"][2] == CUSTOM_CALL_OUTPUT_ITEM


# ── Non-streaming output formatting ─────────────────────────────────

def test_format_response_emits_custom_tool_call_item():
    tc = ToolCall(
        id="call_1",
        name="my_tool",
        arguments={"a": 1},
        call_type="custom",
        namespace="my_ns",
        caller={"type": "direct"},
        item_id="ctc_1",
    )
    choice = ChatChoice(
        index=0,
        message=Message(role=MessageRole.ASSISTANT, content=""),
        finish_reason=FinishReason.TOOL_CALLS,
        tool_calls=[tc],
    )
    usage = UsageInfo(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    resp = ChatResponse(id="resp_1", model="gpt-x", choices=[choice], usage=usage)

    formatted = OpenAIResponsesAdapter().format_response(resp)
    item = formatted["output"][0]
    assert item["type"] == "custom_tool_call"
    assert item["id"] == "ctc_1"
    assert item["call_id"] == "call_1"
    assert item["name"] == "my_tool"
    assert item["input"] == '{"a": 1}'
    assert item["namespace"] == "my_ns"
    assert item["caller"] == {"type": "direct"}


def test_format_response_keeps_function_call_for_function_tools():
    tc = ToolCall(id="call_1", name="get_weather", arguments={"city": "sh"})
    choice = ChatChoice(
        index=0,
        message=Message(role=MessageRole.ASSISTANT, content=""),
        finish_reason=FinishReason.TOOL_CALLS,
        tool_calls=[tc],
    )
    resp = ChatResponse(id="resp_1", model="gpt-x", choices=[choice],
                        usage=UsageInfo(prompt_tokens=1, completion_tokens=1, total_tokens=2))
    item = OpenAIResponsesAdapter().format_response(resp)["output"][0]
    assert item["type"] == "function_call"


# ── Upstream response parsing ───────────────────────────────────────

def test_parse_responses_response_parses_custom_tool_call():
    data = {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "output": [
            {"type": "custom_tool_call", "id": "ctc_1", "call_id": "call_1",
             "name": "my_tool", "input": '{"a": 1}', "namespace": "my_ns",
             "caller": {"type": "direct"}},
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    resp = parse_responses_response(data, "gpt-x")
    tc = resp.choices[0].tool_calls[0]
    assert tc.call_type == "custom"
    assert tc.name == "my_tool"
    assert tc.arguments == {"a": 1}
    assert tc.namespace == "my_ns"
    assert tc.item_id == "ctc_1"
    assert tc.input_raw == '{"a": 1}'

    # Formatting the parsed response back must re-emit a custom_tool_call item.
    formatted = OpenAIResponsesAdapter().format_response(resp)
    assert formatted["output"][0]["type"] == "custom_tool_call"


def test_parse_and_format_round_trip_preserves_input_raw():
    data = {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "output": [
            {"type": "custom_tool_call", "id": "ctc_1", "call_id": "call_1",
             "name": "my_tool", "input": '{ "a" : 1 }', "namespace": "",
             "caller": {"type": "direct"}},
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    resp = parse_responses_response(data, "gpt-x")
    tc = resp.choices[0].tool_calls[0]
    formatted = OpenAIResponsesAdapter().format_response(resp)
    # input_raw preserved the exact upstream string (no re-jsonification)
    assert formatted["output"][0]["input"] == '{ "a" : 1 }'


# ── Streaming output formatting ─────────────────────────────────────

def test_format_stream_chunk_emits_custom_tool_call_events():
    adapter = OpenAIResponsesAdapter()
    adapter._stream_msg_id = "msg_1"

    # 1. output_item.added for the custom tool call
    chunk = StreamChunk(id="resp_1", model="gpt-x", tool_calls=[{
        "index": 0,
        "id": "call_1",
        "type": "custom",
        "custom": {"name": "my_tool", "input": ""},
        "namespace": "my_ns",
        "caller": {"type": "direct"},
        "item_id": "ctc_1",
    }])
    sse = adapter.format_stream_chunk(chunk)
    assert "response.output_item.added" in sse
    assert '"type": "custom_tool_call"' in sse
    assert '"call_id": "call_1"' in sse
    assert '"name": "my_tool"' in sse
    assert '"namespace": "my_ns"' in sse

    # 2. input delta that completes the JSON → delta + done + output_item.done
    chunk2 = StreamChunk(id="resp_1", model="gpt-x", tool_calls=[{
        "index": 0,
        "id": "call_1",
        "type": "custom",
        "custom": {"name": "my_tool", "input": '{"a": 1}'},
    }])
    sse2 = adapter.format_stream_chunk(chunk2)
    assert "response.custom_tool_call_input.delta" in sse2
    assert "response.custom_tool_call_input.done" in sse2
    assert "response.output_item.done" in sse2
    assert '"input": "{\\"a\\": 1}"' in sse2

    # 3. Finish chunk → response.completed carries the custom_tool_call output item
    sse3 = adapter.format_stream_chunk(StreamChunk(
        id="resp_1", model="gpt-x",
        finish_reason=FinishReason.TOOL_CALLS,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    ))
    assert "response.completed" in sse3
    assert '"type": "custom_tool_call"' in sse3
    assert '"call_id": "call_1"' in sse3


# ── Chat-Completions upstream custom tool call shape ────────────────

def test_openai_provider_parses_custom_tool_call_shape():
    provider = _make_provider()
    data = {
        "id": "call_1",
        "type": "custom",
        "custom": {"name": "my_tool", "input": '{"a": 1}'},
    }
    tc = provider._parse_tool_call(data)
    assert tc.call_type == "custom"
    assert tc.name == "my_tool"
    assert tc.arguments == {"a": 1}


def test_cc_upstream_serializes_custom_blocks_as_function_tools():
    """Chat-Completions 上游把 CUSTOM_TOOL_CALL / CUSTOM_TOOL_CALL_OUTPUT 降级为
    普通 function tool_call / tool 消息（跨 provider 一致行为）。"""
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [CUSTOM_CALL_ITEM, CUSTOM_CALL_OUTPUT_ITEM],
    })
    body = _make_provider().prepare_request(req)
    tc_msg = next(m for m in body["messages"] if m.get("tool_calls"))
    assert tc_msg["tool_calls"][0]["type"] == "function"
    assert tc_msg["tool_calls"][0]["function"]["name"] == "my_tool"
    tool_msg = next(m for m in body["messages"] if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"] == "the result"


# ── Responses-API upstream streaming events ─────────────────────────

def test_responses_compt_provider_streams_custom_tool_call():
    from app.providers.openai_responses_compt_provider import OpenAIResponsesCompatProvider
    cfg = ProviderConfig(name="rc", api_key="sk-test", base_url="https://api.example.com/v1")
    provider = OpenAIResponsesCompatProvider(cfg)

    accum: dict = {}
    id_map: dict = {}

    # 1. output_item.added for the custom tool call
    c1 = provider._parse_responses_event(
        {"type": "response.output_item.added", "output_index": 0, "item": {
            "id": "ctc_1", "type": "custom_tool_call", "call_id": "call_1",
            "name": "my_tool", "input": "", "namespace": "my_ns",
            "caller": {"type": "direct"}}},
        None, "resp_1", "gpt-x", accum, id_map,
    )
    assert c1 is not None
    tc1 = c1.tool_calls[0]
    assert tc1["type"] == "custom"
    assert tc1["id"] == "call_1"
    assert tc1["custom"] == {"name": "my_tool", "input": ""}
    assert tc1["namespace"] == "my_ns"
    assert tc1["caller"] == {"type": "direct"}

    # 2. input delta referencing the item by item_id only — must resolve to call_1.
    #    Delta chunks intentionally carry no id (the adapter would treat any id as
    #    a new tool-call start); resolution is via output_index → call_id.
    c2 = provider._parse_responses_event(
        {"type": "response.custom_tool_call_input.delta", "item_id": "ctc_1",
         "output_index": 0, "delta": '{"a": 1}'},
        None, "resp_1", "gpt-x", accum, id_map,
    )
    assert c2 is not None
    tc2 = c2.tool_calls[0]
    assert tc2["type"] == "custom"
    assert "id" not in tc2
    assert tc2["index"] == 0
    assert tc2["custom"]["input"] == '{"a": 1}'
    assert accum["call_1"]["args"] == '{"a": 1}'
    assert id_map.get("ctc_1") == "call_1"


def test_real_world_custom_tool_call_stream_end_to_end():
    """Lock in the exact streaming event sequence the gateway must handle.

    Mirrors the observed upstream format: output_item.added carries call_id +
    id (no namespace/caller); deltas carry only item_id; done events carry the
    full input.
    """
    from app.providers.openai_responses_compt_provider import OpenAIResponsesCompatProvider
    cfg = ProviderConfig(name="rc", api_key="sk-test", base_url="https://api.example.com/v1")
    provider = OpenAIResponsesCompatProvider(cfg)

    accum: dict = {}
    id_map: dict = {}
    ctc_id = "ctc_0e054f37822baf80006a6ee8524eac81939192d6b60f2829ae"
    call_id = "call_WARb3aJWOVMjYsIMrhVQXdKm"

    # output_item.added
    added = provider._parse_responses_event({
        "type": "response.output_item.added",
        "item": {"id": ctc_id, "type": "custom_tool_call", "status": "in_progress",
                 "call_id": call_id, "input": "", "name": "exec"},
        "output_index": 2, "sequence_number": 116,
    }, None, "resp_1", "gpt-x", accum, id_map)
    assert added is not None
    assert added.tool_calls[0]["id"] == call_id
    assert added.tool_calls[0]["index"] == 2  # real output_index preserved

    # custom_tool_call_input.delta (item_id only, no call_id)
    chunks = []
    for delta_text in ("const", " patch"):
        ch = provider._parse_responses_event({
            "type": "response.custom_tool_call_input.delta", "delta": delta_text,
            "item_id": ctc_id, "obfuscation": "x", "output_index": 2, "sequence_number": 117,
        }, None, "resp_1", "gpt-x", accum, id_map)
        assert ch is not None
        chunks.append(ch)

    # .done events carry full input — no chunk needed (input accumulated via deltas)
    done = provider._parse_responses_event({
        "type": "response.custom_tool_call_input.done", "item_id": ctc_id,
        "output_index": 2, "input": "const patch = ...", "sequence_number": 158,
    }, None, "resp_1", "gpt-x", accum, id_map)
    assert done is None
    assert accum[call_id]["args"] == "const patch"

    # Route through the adapter and verify the client-facing SSE event names.
    adapter = OpenAIResponsesAdapter()
    adapter._stream_msg_id = "msg_1"
    sse = "".join(adapter.format_stream_chunk(c) for c in [added] + chunks)

    assert "response.output_item.added" in sse
    assert '"type": "custom_tool_call"' in sse
    assert f'"call_id": "{call_id}"' in sse
    assert '"name": "exec"' in sse
    assert "response.custom_tool_call_input.delta" in sse
    assert f'"item_id": "{ctc_id}"' in sse

    # Custom input is NOT JSON (code patch) — JSON-completion never fires, so done
    # events are emitted by the finish-chunk cleanup (custom calls always close).
    sse2 = adapter.format_stream_chunk(StreamChunk(
        id="resp_1", model="gpt-x",
        finish_reason=FinishReason.TOOL_CALLS,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    ))
    assert "response.custom_tool_call_input.done" in sse2
    assert "response.output_item.done" in sse2
    assert '"input": "const patch"' in sse2
    assert "response.completed" in sse2
    assert '"type": "custom_tool_call"' in sse2


# ── Empty namespace is omitted on output ────────────────────────────

def test_format_response_omits_empty_namespace():
    """custom_tool_call output item omits ``namespace`` when empty."""
    tc = ToolCall(
        id="call_1",
        name="my_tool",
        arguments={"a": 1},
        call_type="custom",
        caller={"type": "direct"},
        item_id="ctc_1",
    )
    choice = ChatChoice(
        index=0,
        message=Message(role=MessageRole.ASSISTANT, content=""),
        finish_reason=FinishReason.TOOL_CALLS,
        tool_calls=[tc],
    )
    resp = ChatResponse(id="resp_1", model="gpt-x", choices=[choice],
                        usage=UsageInfo(prompt_tokens=1, completion_tokens=1, total_tokens=2))
    item = OpenAIResponsesAdapter().format_response(resp)["output"][0]
    assert item["type"] == "custom_tool_call"
    assert "namespace" not in item
    assert item["caller"] == {"type": "direct"}


def test_build_responses_request_omits_empty_namespace():
    """Round-trip to Responses-API upstream omits ``namespace`` when empty."""
    item = {
        "type": "custom_tool_call",
        "id": "ctc_1",
        "call_id": "call_1",
        "name": "my_tool",
        "input": '{"a": 1}',
        "namespace": "",
        "caller": {"type": "direct"},
    }
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [item],
    })
    body = build_responses_request(req)
    out_item = body["input"][0]
    assert out_item["type"] == "custom_tool_call"
    assert "namespace" not in out_item


def test_format_stream_chunk_omits_empty_namespace():
    """Streaming SSE omits ``namespace`` when the tool call carries none."""
    adapter = OpenAIResponsesAdapter()
    adapter._stream_msg_id = "msg_1"
    chunk = StreamChunk(id="resp_1", model="gpt-x", tool_calls=[{
        "index": 0,
        "id": "call_1",
        "type": "custom",
        "custom": {"name": "my_tool", "input": ""},
        "item_id": "ctc_1",
    }])
    sse = adapter.format_stream_chunk(chunk)
    assert "response.output_item.added" in sse
    assert '"type": "custom_tool_call"' in sse
    assert "namespace" not in sse
