"""
Tool result with image content round-trip tests.

Verifies that an Anthropic tool_result whose content is a list containing an
image survives parsing into the internal abstraction and serialization back out
to the Anthropic and OpenAI provider formats (instead of being silently dropped).

Run: cd backend && uv run pytest test_tool_result_image.py -q
"""
from app.adapters.anthropic_adapter import AnthropicMessagesAdapter
from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.openai_provider import OpenAIProvider
from app.abstraction.messages import ContentType


PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mниколай"  # opaque sample

REQUEST = {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
        {"role": "user", "content": "look at the screenshot"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "screenshot", "input": {}}
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": [
                        {"type": "text", "text": "here is the screen"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": PNG_B64,
                            },
                        },
                    ],
                }
            ],
        },
    ],
}


def _find_tool_result_block(chat_request):
    for msg in chat_request.messages:
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if block.type == ContentType.TOOL_RESULT:
                return block
    return None


def test_parse_preserves_image_in_tool_result():
    req = AnthropicMessagesAdapter().parse_request(REQUEST)
    block = _find_tool_result_block(req)
    assert block is not None
    # tool_result is now a list of sub-blocks, not a flattened string
    assert isinstance(block.tool_result, list)
    types = [b.type for b in block.tool_result]
    assert ContentType.TEXT in types
    assert ContentType.IMAGE_BASE64 in types
    img = next(b for b in block.tool_result if b.type == ContentType.IMAGE_BASE64)
    assert img.data == PNG_B64
    assert img.media_type == "image/png"


def test_text_only_tool_result_stays_string():
    data = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 10,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": [{"type": "text", "text": "plain text"}],
                    }
                ],
            }
        ],
    }
    req = AnthropicMessagesAdapter().parse_request(data)
    block = _find_tool_result_block(req)
    assert isinstance(block.tool_result, str)
    assert block.tool_result == "plain text"


def test_anthropic_provider_serializes_image():
    req = AnthropicMessagesAdapter().parse_request(REQUEST)
    provider = AnthropicProvider.__new__(AnthropicProvider)  # avoid __init__ (needs config)
    # Serialize the tool message directly
    tool_msg = next(m for m in req.messages if _msg_has_tool_result(m))
    out = provider._message_to_anthropic(tool_msg)
    content = out["content"][0]["content"]
    assert isinstance(content, list)
    assert any(c["type"] == "image" for c in content)
    img = next(c for c in content if c["type"] == "image")
    assert img["source"]["data"] == PNG_B64


def test_openai_provider_serializes_image():
    req = AnthropicMessagesAdapter().parse_request(REQUEST)
    provider = OpenAIProvider.__new__(OpenAIProvider)
    expanded = provider._expand_messages_to_openai(req.messages)
    tool_msgs = [m for m in expanded if m.get("role") == "tool"]
    assert tool_msgs
    content = tool_msgs[0]["content"]
    assert isinstance(content, list)
    assert any(p.get("type") == "image_url" for p in content)


def _msg_has_tool_result(msg):
    return isinstance(msg.content, list) and any(
        b.type == ContentType.TOOL_RESULT for b in msg.content
    )


# ── Responses API (function_call_output with input_image) ──────────────────

def test_azure_provider_serializes_image_tool_result():
    from app.providers.azure_provider import AzureProvider

    req = AnthropicMessagesAdapter().parse_request(REQUEST)
    tool_msg = next(m for m in req.messages if _msg_has_tool_result(m))
    provider = AzureProvider.__new__(AzureProvider)
    out = provider._tool_result_to_responses_output(
        next(b for b in tool_msg.content if b.type == ContentType.TOOL_RESULT).tool_result
    )
    assert isinstance(out, list)
    assert any(p.get("type") == "input_image" for p in out)
    img = next(p for p in out if p["type"] == "input_image")
    assert img["image_url"] == f"data:image/png;base64,{PNG_B64}"


def test_responses_adapter_parses_image_function_call_output():
    from app.adapters.responses_adapter import _parse_function_call_output

    output = [
        {"type": "input_text", "text": "screen capture"},
        {"type": "input_image", "image_url": f"data:image/png;base64,{PNG_B64}"},
    ]
    result = _parse_function_call_output(output)
    assert isinstance(result, list)
    types = [b.type for b in result]
    assert ContentType.TEXT in types
    assert ContentType.IMAGE_BASE64 in types
    img = next(b for b in result if b.type == ContentType.IMAGE_BASE64)
    assert img.data == PNG_B64
    assert img.media_type == "image/png"


def test_responses_adapter_text_only_output_stays_string():
    from app.adapters.responses_adapter import _parse_function_call_output

    assert _parse_function_call_output("plain") == "plain"
    assert _parse_function_call_output([{"type": "input_text", "text": "a"}]) == "a"


def test_responses_adapter_parses_input_file():
    from app.adapters.responses_adapter import _parse_function_call_output

    output = [
        {"type": "input_file", "file_data": f"data:application/pdf;base64,{PNG_B64}", "filename": "doc.pdf"},
    ]
    result = _parse_function_call_output(output)
    assert isinstance(result, list)
    f = result[0]
    assert f.type == ContentType.FILE_BASE64
    assert f.filename == "doc.pdf"
    assert f.media_type == "application/pdf"


def test_responses_adapter_preserves_input_file_url_in_role_message():
    req = OpenAIResponsesAdapter().parse_request({
        "model": "gemini-3.1-pro-preview",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "文档里的内容是啥?"},
                    {
                        "type": "input_file",
                        "file_data": "https://cdn.coohom.com/coohom/ai-home/2026/05/25/NIJ75G5MDTO2QAABAAAAADA8.pdf",
                        "filename": "NIJ75G5MDTO2QAABAAAAADA8.pdf",
                    },
                ],
            }
        ],
    })

    user_msg = req.messages[0]
    assert isinstance(user_msg.content, list)
    file_block = next(b for b in user_msg.content if b.type == ContentType.FILE_URL)
    assert file_block.url == "https://cdn.coohom.com/coohom/ai-home/2026/05/25/NIJ75G5MDTO2QAABAAAAADA8.pdf"
    assert file_block.filename == "NIJ75G5MDTO2QAABAAAAADA8.pdf"


def test_tencentvod_provider_serializes_file_url_block_to_chat_file_payload():
    from app.providers.tencent.vod.base import TencentVODProvider

    req = OpenAIResponsesAdapter().parse_request({
        "model": "gemini-3.1-pro-preview",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "文档里的内容是啥?"},
                    {
                        "type": "input_file",
                        "file_data": "https://cdn.coohom.com/coohom/ai-home/2026/05/25/NIJ75G5MDTO2QAABAAAAADA8.pdf",
                        "filename": "NIJ75G5MDTO2QAABAAAAADA8.pdf",
                    },
                ],
            }
        ],
    })
    provider = TencentVODProvider.__new__(TencentVODProvider)

    expanded = provider._expand_messages_to_openai(req.messages)
    content = expanded[0]["content"]

    assert isinstance(content, list)
    file_part = next(p for p in content if p.get("type") == "file")
    assert file_part["file_url"] == "https://cdn.coohom.com/coohom/ai-home/2026/05/25/NIJ75G5MDTO2QAABAAAAADA8.pdf"
