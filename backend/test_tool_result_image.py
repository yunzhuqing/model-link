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

# ── Gateway _convert_image_urls_to_base64: tool_result nesting ─────────

from unittest.mock import AsyncMock, MagicMock, patch
import base64
import pytest

SAMPLE_IMAGE_DATA = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"


def _build_chat_request_with_nested_images():
    """Build a ChatRequest with IMAGE_URL blocks in top-level and tool_result content."""
    from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
    from app.abstraction.chat import ChatRequest

    return ChatRequest(
        model="claude-opus-4-7",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentBlock.from_text("describe this image"),
                    ContentBlock.from_image_url("https://example.com/photo.jpg"),
                ],
            ),
            Message(
                role=MessageRole.USER,
                content=[
                    ContentBlock(
                        type=ContentType.TOOL_RESULT,
                        tool_call_id="toolu_1",
                        tool_result=[
                            ContentBlock.from_text("here is a screenshot"),
                            ContentBlock.from_image_url("https://example.com/screen.png"),
                        ],
                    )
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_gateway_converts_nested_tool_result_images():
    """Gateway _convert_image_urls_to_base64 should traverse tool_result content."""
    from app.middleware.gateway_service import GatewayService, _get_media_fetch_client
    from app.abstraction.messages import ContentType

    request = _build_chat_request_with_nested_images()

    # Mock the media fetch client
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {"content-type": "image/png"}
    mock_resp.content = SAMPLE_IMAGE_DATA

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("app.middleware.gateway_service._get_media_fetch_client", return_value=mock_client):
        await GatewayService._convert_image_urls_to_base64(request)

    # Top-level image block should be converted
    top_block = request.messages[0].content[1]
    assert top_block.type == ContentType.IMAGE_BASE64
    assert top_block.data == base64.b64encode(SAMPLE_IMAGE_DATA).decode("ascii")
    assert top_block.media_type == "image/png"

    # Nested tool_result image block should also be converted
    tr_block = request.messages[1].content[0]
    nested_img = tr_block.tool_result[1]
    assert nested_img.type == ContentType.IMAGE_BASE64
    assert nested_img.data == base64.b64encode(SAMPLE_IMAGE_DATA).decode("ascii")
    assert nested_img.media_type == "image/png"

    # Text blocks should be untouched
    assert request.messages[0].content[0].type == ContentType.TEXT
    assert tr_block.tool_result[0].type == ContentType.TEXT
    assert tr_block.tool_result[0].text == "here is a screenshot"


@pytest.mark.asyncio
async def test_gateway_preserves_base64_in_tool_result():
    """Already-base64 images in tool_result should not be touched."""
    from app.middleware.gateway_service import GatewayService, _get_media_fetch_client
    from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
    from app.abstraction.chat import ChatRequest

    request = ChatRequest(
        model="claude-opus-4-7",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentBlock(
                        type=ContentType.TOOL_RESULT,
                        tool_call_id="toolu_1",
                        tool_result=[
                            ContentBlock.from_image_base64("abc123", "image/jpeg"),
                        ],
                    )
                ],
            ),
        ],
    )

    mock_client = AsyncMock()
    with patch("app.middleware.gateway_service._get_media_fetch_client", return_value=mock_client):
        await GatewayService._convert_image_urls_to_base64(request)

    nested_img = request.messages[0].content[0].tool_result[0]
    assert nested_img.type == ContentType.IMAGE_BASE64
    assert nested_img.data == "abc123"
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_gateway_handles_download_failure_in_tool_result():
    """When a nested image URL fails, keep the original URL block."""
    from app.middleware.gateway_service import GatewayService, _get_media_fetch_client
    from app.abstraction.messages import Message, MessageRole, ContentBlock, ContentType
    from app.abstraction.chat import ChatRequest

    request = ChatRequest(
        model="claude-opus-4-7",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentBlock(
                        type=ContentType.TOOL_RESULT,
                        tool_call_id="toolu_1",
                        tool_result=[
                            ContentBlock.from_image_url("https://example.com/broken.png"),
                        ],
                    )
                ],
            ),
        ],
    )

    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Connection refused")

    with patch("app.middleware.gateway_service._get_media_fetch_client", return_value=mock_client):
        await GatewayService._convert_image_urls_to_base64(request)

    nested_img = request.messages[0].content[0].tool_result[0]
    assert nested_img.type == ContentType.IMAGE_URL
    assert nested_img.url == "https://example.com/broken.png"
