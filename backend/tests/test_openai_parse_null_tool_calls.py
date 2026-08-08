"""Regression: parsing an OpenAI/vLLM chat completion whose assistant message
carries ``"tool_calls": null`` must not raise ``TypeError: 'NoneType' object
is not iterable``.

Some vLLM deployments (e.g. GLM models) emit ``tool_calls: null`` on the
assistant message instead of omitting the key. The parser used to only check
``"tool_calls" in data`` and then iterate ``data["tool_calls"]``, which crashed
when the value was ``None``.
"""

from app.providers.base import ProviderConfig
from app.providers.openai_provider import OpenAIProvider
from app.providers.vllm_provider import VLLMProvider
from app.abstraction.chat import FinishReason


def _null_tool_calls_payload():
    return {
        "id": "chatcmpl-abc",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "qunhe/glm-5.2-nvfp4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "hello",
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_openai_provider_parses_null_tool_calls():
    provider = OpenAIProvider(
        ProviderConfig(name="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
    )
    resp = provider.parse_response(_null_tool_calls_payload(), "qunhe/glm-5.2-nvfp4")

    assert resp.choices
    choice = resp.choices[0]
    assert choice.message.role.value == "assistant"
    assert choice.message.content and choice.message.content[0].text == "hello"
    assert choice.tool_calls == []
    assert choice.finish_reason == FinishReason.STOP


def test_vllm_provider_parses_null_tool_calls():
    """Reproduces the production crash from the traceback:
    vllm_provider._parse_message -> openai_provider._parse_message iterating
    data["tool_calls"] which was None.
    """
    provider = VLLMProvider(
        ProviderConfig(name="vllm", api_key="sk-test", base_url="https://vllm.example.com/v1")
    )
    resp = provider.parse_response(_null_tool_calls_payload(), "qunhe/glm-5.2-nvfp4")

    assert resp.choices
    choice = resp.choices[0]
    assert choice.message.content and choice.message.content[0].text == "hello"
    assert choice.tool_calls == []


def test_openai_provider_parses_absent_tool_calls():
    """Omitting the key entirely must keep working (no behavior change)."""
    provider = OpenAIProvider(
        ProviderConfig(name="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
    )
    data = _null_tool_calls_payload()
    del data["choices"][0]["message"]["tool_calls"]
    resp = provider.parse_response(data, "qunhe/glm-5.2-nvfp4")
    assert resp.choices[0].tool_calls == []


def test_openai_provider_parses_real_tool_calls():
    """A real tool_calls list must still be parsed into blocks/calls."""
    provider = OpenAIProvider(
        ProviderConfig(name="openai", api_key="sk-test", base_url="https://api.openai.com/v1")
    )
    data = _null_tool_calls_payload()
    data["choices"][0]["message"]["tool_calls"] = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "sh"}'},
        }
    ]
    data["choices"][0]["finish_reason"] = "tool_calls"
    resp = provider.parse_response(data, "qunhe/glm-5.2-nvfp4")
    choice = resp.choices[0]
    assert len(choice.tool_calls) == 1
    assert choice.tool_calls[0].name == "get_weather"
    assert choice.tool_calls[0].arguments == {"city": "sh"}
