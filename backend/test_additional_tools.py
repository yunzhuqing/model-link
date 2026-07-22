"""
Tests for `additional_tools` input items in the OpenAI Responses API adapter.

Input format:
    {"input": [{"type": "additional_tools", "role": "developer", "tools": [...]}]}

Behavior:
- ChatRequest.tools includes the additional tools (chat/completions upstreams
  serialize them into the global `tools` array) and each is tagged with
  source='additional_tools'.
- The raw items are preserved in metadata['_additional_tools'].
- An empty developer placeholder message (name=ADDITIONAL_TOOLS_MARKER_NAME)
  keeps the item's original position in the conversation.
- Responses-API upstreams (build_responses_request) re-inject the raw items
  into `input` at their original positions and exclude their tools from the
  global `tools` array. Chat/completions upstreams skip the empty placeholder.

Run: cd backend && uv run pytest test_additional_tools.py -q
"""
from app.abstraction.messages import ADDITIONAL_TOOLS_MARKER_NAME, MessageRole
from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.providers._responses_format import build_responses_request
from app.providers.openai_provider import OpenAIProvider

FUNC_TOOL = {
    "type": "function",
    "name": "get_weather",
    "description": "Get weather for a city",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}

ADDITIONAL_ITEM = {"type": "additional_tools", "role": "developer", "tools": [FUNC_TOOL]}


def _parse(extra_input=None, **kwargs):
    payload = {
        "model": "gpt-x",
        "input": [
            {"role": "user", "content": "hi"},
            *(extra_input or [ADDITIONAL_ITEM]),
        ],
    }
    payload.update(kwargs)
    return OpenAIResponsesAdapter().parse_request(payload)


def test_additional_tools_merged_into_request_tools():
    req = _parse()
    assert len(req.tools) == 1
    assert req.tools[0].name == "get_weather"
    assert req.tools[0].get_parameters_schema() == FUNC_TOOL["parameters"]
    assert req.tools[0].source == "additional_tools"


def test_additional_tools_raw_items_preserved_in_metadata():
    req = _parse()
    assert req.metadata["_additional_tools"] == [ADDITIONAL_ITEM]


def test_additional_tools_produces_empty_placeholder_message():
    req = _parse()
    assert len(req.messages) == 2
    assert req.messages[0].role == MessageRole.USER
    marker = req.messages[1]
    assert marker.role == MessageRole.DEVELOPER
    assert marker.name == ADDITIONAL_TOOLS_MARKER_NAME
    assert not marker.get_text_content()


def test_additional_tools_combine_with_top_level_tools():
    top_level = {
        "type": "function",
        "function": {"name": "top_tool", "description": "d", "parameters": {"type": "object"}},
    }
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gpt-x",
        "input": [
            {"role": "user", "content": "hi"},
            {"type": "additional_tools", "role": "developer", "tools": [FUNC_TOOL]},
        ],
        "tools": [top_level],
    })
    assert [t.name for t in req.tools] == ["top_tool", "get_weather"]


def test_responses_mode_keeps_item_in_input_not_global_tools():
    req = _parse()
    body = build_responses_request(req)
    assert body["input"][1] == ADDITIONAL_ITEM
    assert "tools" not in body


def test_responses_mode_top_level_tools_stay_global():
    top_level = {
        "type": "function",
        "function": {"name": "top_tool", "description": "d", "parameters": {"type": "object"}},
    }
    req = _parse(tools=[top_level])
    body = build_responses_request(req)
    assert body["input"][1] == ADDITIONAL_ITEM
    assert [t["name"] for t in body["tools"]] == ["top_tool"]


def test_responses_mode_preserves_original_item_position():
    second_item = {"type": "additional_tools", "role": "developer", "tools": [{
        "type": "function", "name": "second_tool", "description": "d",
        "parameters": {"type": "object"},
    }]}
    req = _parse(extra_input=[
        {"role": "user", "content": "later"},
        ADDITIONAL_ITEM,
        {"role": "assistant", "content": "mid"},
        second_item,
        {"role": "user", "content": "end"},
    ])
    body = build_responses_request(req)
    types = [
        item.get("type") if item.get("type") == "additional_tools" else item.get("role")
        for item in body["input"]
    ]
    assert types == ["user", "user", "additional_tools", "assistant", "additional_tools", "user"]


def test_chat_completions_mode_places_tools_globally():
    req = _parse()
    provider = OpenAIProvider.__new__(OpenAIProvider)
    body = provider.prepare_request(req)
    assert [t["function"]["name"] for t in body["tools"]] == ["get_weather"]
    # additional_tools item and its placeholder must not leak into messages
    assert all(m.get("type") != "additional_tools" for m in body["messages"])
    assert all(m.get("role") != "developer" for m in body["messages"])
