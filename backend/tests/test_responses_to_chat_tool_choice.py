"""Regression tests for Responses API to Chat Completions tool choice conversion."""

from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.providers.openai_provider import OpenAIProvider


def _to_chat_completions(payload):
    request = OpenAIResponsesAdapter().parse_request(payload)
    provider = OpenAIProvider.__new__(OpenAIProvider)
    return provider.prepare_request(request)


def test_omits_tool_choice_when_responses_request_has_no_tools():
    body = _to_chat_completions({
        "model": "gpt-x",
        "input": "hello",
        "tool_choice": "auto",
    })

    assert "tools" not in body
    assert "tool_choice" not in body


def test_preserves_tool_choice_when_responses_request_has_tools():
    body = _to_chat_completions({
        "model": "gpt-x",
        "input": "What is the weather?",
        "tools": [{
            "type": "function",
            "name": "get_weather",
            "parameters": {"type": "object", "properties": {}},
        }],
        "tool_choice": "auto",
    })

    assert body["tools"][0]["function"]["name"] == "get_weather"
    assert body["tool_choice"] == "auto"
