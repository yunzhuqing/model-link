"""Test that /v1/responses reasoning items merge with subsequent assistant
message items that contain content + tool_calls.

Reproduces the bug where a `reasoning` input item followed by an assistant
`message` with content blocks (text + function_call) would produce duplicate
assistant messages: one carrying only reasoning_content, another carrying
content + tool_calls.
"""
import json
import pytest

from app.adapters.responses_adapter import OpenAIResponsesAdapter
from app.abstraction.messages import MessageRole, ContentType


@pytest.fixture
def adapter():
    return OpenAIResponsesAdapter()


def test_reasoning_merges_with_assistant_message_content_list(adapter):
    """A reasoning item followed by an assistant message with content list
    (text + function_call) should merge into a single assistant message."""
    data = {
        "model": "deepseek-chat",
        "input": [
            {
                "type": "function_call_output",
                "id": "fco_1",
                "call_id": "call_001",
                "output": "result data",
            },
            {
                "type": "reasoning",
                "id": "rs_001",
                "summary": [
                    {
                        "type": "summary_text",
                        "text": "I need to fix the polling logic.",
                    }
                ],
                "content": None,
                "encrypted_content": None,
            },
            {
                "role": "assistant",
                "id": "msg_001",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Let me fix the polling logic.",
                    },
                    {
                        "type": "function_call",
                        "id": "fc_001",
                        "call_id": "call_002",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "sed -n 160,260p backend/app/http_client.py"}),
                    },
                ],
            },
        ],
    }

    request = adapter.parse_request(data)

    # Count assistant messages — should be exactly 1 (the merged one)
    assistant_msgs = [m for m in request.messages if m.role == MessageRole.ASSISTANT]
    assert len(assistant_msgs) == 1, (
        f"Expected 1 assistant message, got {len(assistant_msgs)}: "
        f"{[(m.reasoning_content, m.content) for m in assistant_msgs]}"
    )

    msg = assistant_msgs[0]
    assert msg.reasoning_content == "I need to fix the polling logic."
    assert msg.content is not None
    assert isinstance(msg.content, list)
    assert len(msg.content) == 2  # text + tool_call

    # First block should be text
    assert msg.content[0].type == ContentType.TEXT
    assert msg.content[0].text == "Let me fix the polling logic."

    # Second block should be tool_call
    assert msg.content[1].type in (
        ContentType.TOOL_CALL,
        ContentType.CUSTOM_TOOL_CALL,
    )
    assert msg.content[1].tool_name == "exec_command"
    assert msg.content[1].tool_call_id == "call_002"


def test_reasoning_merges_with_function_call_item(adapter):
    """A reasoning item followed by a function_call item should merge into
    a single assistant message with reasoning_content + tool_calls."""
    data = {
        "model": "deepseek-chat",
        "input": [
            {
                "type": "reasoning",
                "id": "rs_001",
                "summary": [
                    {
                        "type": "summary_text",
                        "text": "Thinking about the next step.",
                    }
                ],
            },
            {
                "type": "function_call",
                "id": "fc_001",
                "call_id": "call_002",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "ls -la"}),
            },
        ],
    }

    request = adapter.parse_request(data)

    assistant_msgs = [m for m in request.messages if m.role == MessageRole.ASSISTANT]
    assert len(assistant_msgs) == 1, (
        f"Expected 1 assistant message, got {len(assistant_msgs)}"
    )

    msg = assistant_msgs[0]
    assert msg.reasoning_content == "Thinking about the next step."
    assert isinstance(msg.content, list)
    assert len(msg.content) == 1
    assert msg.content[0].tool_name == "exec_command"


def test_reasoning_alone_creates_assistant_message(adapter):
    """A reasoning item alone (no following assistant content) should still
    create a reasoning-only assistant message."""
    data = {
        "model": "deepseek-chat",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello"}],
            },
            {
                "type": "reasoning",
                "id": "rs_001",
                "summary": [
                    {"type": "summary_text", "text": "Just thinking."}
                ],
            },
        ],
    }

    request = adapter.parse_request(data)

    assistant_msgs = [m for m in request.messages if m.role == MessageRole.ASSISTANT]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].reasoning_content == "Just thinking."