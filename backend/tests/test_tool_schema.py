"""
Tool JSON Schema passthrough tests.

Verifies that advanced JSON Schema keywords ($defs / $ref / definitions /
nested objects / additionalProperties) survive parsing into the internal
ToolDefinition abstraction and serialization back out to provider formats,
instead of being silently flattened by the ToolParameter list.

Run: cd backend && uv run pytest test_tool_schema.py -q
"""
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter
from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.providers._schema_utils import inline_jsonschema_refs
from app.providers.gemini.base import GeminiProvider
from app.providers.openai_provider import OpenAIProvider, parse_openai_request

COLOR_ENUM = ["red", "green", "blue"]


def _schema_with_defs():
    return {
        "type": "object",
        "$defs": {"Color": {"type": "string", "enum": COLOR_ENUM}},
        "properties": {
            "fg": {"$ref": "#/$defs/Color"},
            "bg": {"$ref": "#/$defs/Color", "description": "background"},
        },
        "required": ["fg"],
    }


def test_openai_parser_preserves_defs_and_ref():
    req = parse_openai_request({
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "paint",
                "description": "d",
                "parameters": _schema_with_defs(),
            },
        }],
    })
    tool = req.tools[0]
    schema = tool.get_parameters_schema()
    assert "$defs" in schema
    assert schema["properties"]["fg"] == {"$ref": "#/$defs/Color"}
    assert tool.parameters_schema is not None  # raw passthrough populated


def test_openai_provider_output_preserves_defs():
    req = parse_openai_request({
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "paint",
                "description": "d",
                "parameters": _schema_with_defs(),
            },
        }],
    })
    provider = OpenAIProvider.__new__(OpenAIProvider)
    out = provider._tool_to_openai(req.tools[0])
    params = out["function"]["parameters"]
    assert "$defs" in params
    assert params["properties"]["bg"]["description"] == "background"


def test_anthropic_parser_preserves_defs():
    req = AnthropicMessagesAdapter().parse_request({
        "model": "claude-x",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{
            "name": "paint",
            "description": "d",
            "input_schema": _schema_with_defs(),
        }],
    })
    schema = req.tools[0].get_parameters_schema()
    assert "$defs" in schema
    assert schema["properties"]["fg"] == {"$ref": "#/$defs/Color"}


def test_responses_parser_preserves_defs():
    adapter = OpenAIResponsesAdapter()
    req = adapter.parse_request({
        "model": "gpt-x",
        "input": [{"role": "user", "content": "hi"}],
        "tools": [{
            "type": "function",
            "name": "paint",
            "description": "d",
            "parameters": _schema_with_defs(),
        }],
    })
    schema = req.tools[0].get_parameters_schema()
    assert "$defs" in schema
    assert schema["properties"]["fg"] == {"$ref": "#/$defs/Color"}


def test_gemini_provider_inlines_refs_and_drops_defs():
    req = AnthropicMessagesAdapter().parse_request({
        "model": "claude-x",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{
            "name": "paint",
            "description": "d",
            "input_schema": _schema_with_defs(),
        }],
    })
    provider = GeminiProvider.__new__(GeminiProvider)
    out = provider._tool_to_gemini(req.tools[0])
    schema = out["parameters"]
    # Gemini cannot represent $defs/$ref — they must be inlined.
    assert "$defs" not in schema
    assert "$ref" not in str(schema)
    fg = schema["properties"]["fg"]
    assert fg["type"] == "string"
    assert fg["enum"] == COLOR_ENUM
    bg = schema["properties"]["bg"]
    assert bg["enum"] == COLOR_ENUM
    assert bg["description"] == "background"  # sibling keys survive inlining


def test_inline_helper_strips_additional_properties():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "additionalProperties": False,
    }
    out = inline_jsonschema_refs(schema)
    assert "additionalProperties" not in out


def test_inline_helper_handles_definitions_alias():
    schema = {
        "definitions": {"Color": {"type": "string", "enum": COLOR_ENUM}},
        "properties": {"c": {"$ref": "#/definitions/Color"}},
    }
    out = inline_jsonschema_refs(schema)
    assert "definitions" not in out
    assert out["properties"]["c"]["enum"] == COLOR_ENUM


def test_inline_helper_terminates_on_circular_refs():
    schema = {
        "$defs": {
            "A": {"type": "object", "properties": {"b": {"$ref": "#/$defs/B"}}},
            "B": {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}}},
        },
        "properties": {"x": {"$ref": "#/$defs/A"}},
    }
    # Must not hang; result may retain a back-ref (acceptable for Gemini).
    out = inline_jsonschema_refs(schema)
    assert "x" in out["properties"]


def test_simple_schema_still_round_trips():
    req = parse_openai_request({
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "echo",
                "description": "d",
                "parameters": {
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                    "required": ["msg"],
                },
            },
        }],
    })
    schema = req.tools[0].get_parameters_schema()
    assert schema["properties"]["msg"] == {"type": "string"}
    assert schema["required"] == ["msg"]
