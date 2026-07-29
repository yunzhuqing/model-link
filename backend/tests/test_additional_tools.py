"""
Tests for `additional_tools` input items in the OpenAI Responses API adapter.

Input format:
    {"input": [{"type": "additional_tools", "role": "developer", "tools": [...]}]}

Behavior:
- ChatRequest.tools includes the additional FUNCTION tools (top-level
  function tools and namespace-flattened function members), each tagged
  with source='additional_tools'; custom and tool_search are not
  representable as function tools and are not added to the list.
- The raw items are preserved in metadata['_additional_tools'].
- An empty developer placeholder message (name=ADDITIONAL_TOOLS_MARKER_NAME)
  keeps the item's original position in the conversation.
- Responses-API upstreams (build_responses_request, incl. the Volcengine
  variant that rebuilds `input`) re-inject the raw items into `input` at
  their original positions and exclude their tools from the global `tools`
  array — additional_tools is part of the Responses API input.
- Chat/Completions upstreams skip the empty placeholder and place the
  function-shaped tools into the global `tools` array.

Run: cd backend && uv run pytest test_additional_tools.py -q
"""
from app.abstraction.messages import ADDITIONAL_TOOLS_MARKER_NAME, MessageRole
from app.abstraction.tools import ToolType
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


def test_volcengine_responses_mode_keeps_additional_tools_in_input():
    """Volcengine rebuilds `input` from messages; it must re-inject the raw
    additional_tools item at the placeholder's position (not drop it)."""
    from app.providers.volcengine.base import VolcengineProvider

    req = _parse()
    provider = VolcengineProvider.__new__(VolcengineProvider)
    body = provider._prepare_responses_request(req)
    assert body["input"][1] == ADDITIONAL_ITEM
    # additional tools are not duplicated into the global tools field
    assert "tools" not in body


def test_chat_completions_mode_places_tools_globally():
    req = _parse()
    provider = OpenAIProvider.__new__(OpenAIProvider)
    body = provider.prepare_request(req)
    assert [t["function"]["name"] for t in body["tools"]] == ["get_weather"]
    # additional_tools item and its placeholder must not leak into messages
    assert all(m.get("type") != "additional_tools" for m in body["messages"])
    assert all(m.get("role") != "developer" for m in body["messages"])


# ── Non-function additional tool types: custom / namespace / tool_search ──

CUSTOM_TOOL = {
    "type": "custom",
    "name": "draw",
    "description": "Draw something",
    "defer_loading": True,
    "allowed_callers": "direct",
    "format": {
        "type": "object",
        "properties": {"shape": {"type": "string"}},
        "required": ["shape"],
    },
}

NAMESPACE_ITEM = {
    "type": "additional_tools", "role": "developer",
    "tools": [
        {
            "type": "namespace", "name": "collaboration",
            "description": "Tools for spawning and managing sub-agents.",
            "tools": [
                {"type": "function", "name": "spawn", "description": "d",
                 "parameters": {"type": "object"}},
                CUSTOM_TOOL,
            ],
        },
        {"type": "tool_search", "description": "search tools",
         "execution": "server", "parameters": {"type": "object"}},
    ],
}


def test_custom_tool_parsed_as_custom_with_raw():
    """custom tools are carried as a ToolType.CUSTOM ToolDefinition (not
    lossy-converted to FUNCTION) with the original dict in ``raw``, so the
    Chat-Completions path can re-emit them as ``type=custom``."""
    item = {"type": "additional_tools", "role": "developer", "tools": [CUSTOM_TOOL]}
    req = _parse(extra_input=[item])
    assert len(req.tools) == 1
    t = req.tools[0]
    assert t.name == "draw"
    assert t.tool_type == ToolType.CUSTOM
    assert t.source == "additional_tools"
    assert t.raw == CUSTOM_TOOL
    # raw item also preserved for Responses-API re-injection
    assert req.metadata["_additional_tools"] == [item]


def test_namespace_flattened_into_tools():
    """namespace is recursively flattened; function members (spawn) and
    custom members (draw) both make it into ChatRequest.tools."""
    req = _parse(extra_input=[NAMESPACE_ITEM])
    assert [t.name for t in req.tools] == ["spawn", "draw"]
    assert all(t.source == "additional_tools" for t in req.tools)
    assert req.tools[1].tool_type == ToolType.CUSTOM


def test_tool_search_not_a_global_tool_but_preserved_raw():
    item = {"type": "additional_tools", "role": "developer", "tools": [
        {"type": "tool_search", "description": "d", "execution": "client",
         "parameters": {"type": "object"}},
    ]}
    req = _parse(extra_input=[item])
    # tool_search is not representable as a function tool → not in global tools
    assert req.tools == []
    # but the raw item is preserved for Responses-API upstreams
    assert req.metadata["_additional_tools"] == [item]


def test_responses_mode_keeps_custom_namespace_tool_search_in_input():
    req = _parse(extra_input=[NAMESPACE_ITEM])
    body = build_responses_request(req)
    # Raw additional_tools item (with namespace + tool_search) re-injected verbatim
    assert body["input"][1] == NAMESPACE_ITEM
    # None of the additional tools leak into the global tools array
    assert "tools" not in body


def test_chat_completions_mode_serializes_custom_and_namespace_tools():
    req = _parse(extra_input=[NAMESPACE_ITEM])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    body = provider.prepare_request(req)
    tools = body["tools"]
    # spawn (function) → nested "function" wrapper
    spawn = next(t for t in tools if t.get("type") == "function")
    assert spawn["function"]["name"] == "spawn"
    # draw (custom) → nested "custom" wrapper (NOT flat, NOT function);
    # preserves format / defer_loading / allowed_callers.
    draw = next(t for t in tools if t.get("type") == "custom")
    assert draw["custom"]["name"] == "draw"
    assert draw["custom"]["format"] == CUSTOM_TOOL["format"]
    assert draw["custom"]["defer_loading"] is True
    assert draw["custom"]["allowed_callers"] == "direct"
    # tool_search dropped (not a function tool); placeholder developer skipped
    assert all(m.get("role") != "developer" for m in body["messages"])
