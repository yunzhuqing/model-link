# Anthropic Messages API Streaming Protocol

This document defines the exact SSE (Server-Sent Events) sequence that the `/v1/messages` endpoint must emit when `"stream": true`. All providers (Gemini, Bailian, OpenAI, etc.) are adapted to produce this unified Anthropic-compatible event sequence via `anthropic_adapter.py`.

---

## Event Sequence Overview

```
message_start

// [Optional] Thinking/Reasoning Block
content_block_start          → content_block.type == "thinking"
content_block_delta          → delta.type == "thinking_delta" (repeated)
content_block_stop

// [Optional] Text Block
content_block_start          → content_block.type == "text"
content_block_delta          → delta.type == "text_delta" (repeated)
content_block_stop

// [Optional] Tool Use Block (repeated per tool call)
content_block_start          → content_block.type == "tool_use"
content_block_delta          → delta.type == "input_json_delta" (repeated)
content_block_stop

// End
message_delta               → includes stop_reason + usage
message_stop
```

---

## Detailed Event Definitions

### 1. `message_start`

Emitted once at the start of the stream. Must contain a complete message object with all required fields.

```json
{
  "type": "message_start",
  "message": {
    "id": "msg_xxx",
    "type": "message",
    "role": "assistant",
    "content": [],
    "model": "claude-3-opus-20240229",
    "stop_reason": null,
    "stop_sequence": null,
    "usage": {
      "input_tokens": 100,
      "output_tokens": 0
    }
  }
}
```

**Required fields in `message`:**
- `id` — Must start with `msg_` prefix (non-Claude IDs are normalized)
- `type` — Always `"message"`
- `role` — Always `"assistant"`
- `content` — Empty array `[]`
- `model` — Model name string
- `stop_reason` — `null` (set later in `message_delta`)
- `stop_sequence` — `null`
- `usage` — Must include `input_tokens` (can include `cache_read_input_tokens`, `cache_creation_input_tokens`)

> **Note:** The Anthropic SDK (pydantic-based) validates this object strictly. Missing fields cause client-side validation errors.

---

### 2. Thinking/Reasoning Block (Optional)

Emitted when the model produces thinking/reasoning content (e.g., models with `thinking: {type: "enabled"}`).

#### 2.1 `content_block_start` (thinking)

```json
{
  "type": "content_block_start",
  "index": 0,
  "content_block": {
    "type": "thinking",
    "thinking": ""
  }
}
```

#### 2.2 `content_block_delta` (thinking_delta) — repeated

```json
{
  "type": "content_block_delta",
  "index": 0,
  "delta": {
    "type": "thinking_delta",
    "thinking": "Let me analyze this step by step..."
  }
}
```

#### 2.3 `content_block_stop` (thinking)

```json
{
  "type": "content_block_stop",
  "index": 0
}
```

---

### 3. Text Block (Optional)

Emitted when the model produces text content.

#### 3.1 `content_block_start` (text)

```json
{
  "type": "content_block_start",
  "index": 1,
  "content_block": {
    "type": "text",
    "text": ""
  }
}
```

#### 3.2 `content_block_delta` (text_delta) — repeated

```json
{
  "type": "content_block_delta",
  "index": 1,
  "delta": {
    "type": "text_delta",
    "text": "Hello, how can I help you?"
  }
}
```

#### 3.3 `content_block_stop` (text)

```json
{
  "type": "content_block_stop",
  "index": 1
}
```

---

### 4. Tool Use Block (Optional, Repeated per Tool Call)

Emitted when the model calls a tool/function. Each tool call is a separate content block.

#### 4.1 `content_block_start` (tool_use)

```json
{
  "type": "content_block_start",
  "index": 2,
  "content_block": {
    "type": "tool_use",
    "id": "toolu_abc123",
    "name": "get_weather",
    "input": {}
  }
}
```

#### 4.2 `content_block_delta` (input_json_delta) — repeated

Tool call arguments arrive as incremental JSON fragments.

```json
{
  "type": "content_block_delta",
  "index": 2,
  "delta": {
    "type": "input_json_delta",
    "partial_json": "{\"location\": \"San"
  }
}
```

```json
{
  "type": "content_block_delta",
  "index": 2,
  "delta": {
    "type": "input_json_delta",
    "partial_json": " Francisco\"}"
  }
}
```

#### 4.3 `content_block_stop` (tool_use)

```json
{
  "type": "content_block_stop",
  "index": 2
}
```

---

### 5. `message_delta`

Emitted once after all content blocks are closed. Contains the final `stop_reason` and output token usage.

```json
{
  "type": "message_delta",
  "delta": {
    "stop_reason": "end_turn",
    "stop_sequence": null
  },
  "usage": {
    "output_tokens": 42
  }
}
```

**`stop_reason` values:**

| Value | Description | Mapped from |
|-------|-------------|-------------|
| `"end_turn"` | Normal completion | `FinishReason.STOP` |
| `"max_tokens"` | Hit token limit | `FinishReason.LENGTH` |
| `"tool_use"` | Model called a tool | `FinishReason.TOOL_CALLS` |

---

### 6. `message_stop`

Final event signaling the end of the stream. No payload data.

```json
{
  "type": "message_stop"
}
```

---

## Content Block Index Rules

The `index` field in content block events is a zero-based counter that increments for each new content block:

| Block | index |
|-------|-------|
| Thinking (if present) | 0 |
| Text (if present) | next (0 or 1) |
| Tool Call 1 | next |
| Tool Call 2 | next |
| ... | ... |

**Important:** Every `content_block_start` MUST have a matching `content_block_stop`. The adapter manages this lifecycle:
- When a new block type is detected, the previous open block is closed first
- At the end of the stream, any remaining open block is closed before `message_delta`

---

## Common Scenarios

### Scenario A: Simple Text Response

```
message_start              (usage.input_tokens populated)
content_block_start        (index=0, type="text")
content_block_delta        (index=0, text_delta) ×N
content_block_stop         (index=0)
message_delta              (stop_reason="end_turn", usage.output_tokens)
message_stop
```

### Scenario B: Thinking + Text Response

```
message_start
content_block_start        (index=0, type="thinking")
content_block_delta        (index=0, thinking_delta) ×N
content_block_stop         (index=0)
content_block_start        (index=1, type="text")
content_block_delta        (index=1, text_delta) ×N
content_block_stop         (index=1)
message_delta              (stop_reason="end_turn")
message_stop
```

### Scenario C: Text + Tool Use

```
message_start
content_block_start        (index=0, type="text")
content_block_delta        (index=0, text_delta) ×N
content_block_stop         (index=0)
content_block_start        (index=1, type="tool_use", id="toolu_xxx", name="func1")
content_block_delta        (index=1, input_json_delta) ×N
content_block_stop         (index=1)
message_delta              (stop_reason="tool_use")
message_stop
```

### Scenario D: Multiple Tool Calls

```
message_start
content_block_start        (index=0, type="tool_use", id="toolu_1", name="func1")
content_block_delta        (index=0, input_json_delta) ×N
content_block_stop         (index=0)
content_block_start        (index=1, type="tool_use", id="toolu_2", name="func2")
content_block_delta        (index=1, input_json_delta) ×N
content_block_stop         (index=1)
message_delta              (stop_reason="tool_use")
message_stop
```

### Scenario E: Thinking + Tool Use (No Text)

```
message_start
content_block_start        (index=0, type="thinking")
content_block_delta        (index=0, thinking_delta) ×N
content_block_stop         (index=0)
content_block_start        (index=1, type="tool_use", id="toolu_xxx", name="func1")
content_block_delta        (index=1, input_json_delta) ×N
content_block_stop         (index=1)
message_delta              (stop_reason="tool_use")
message_stop
```

---

## Non-Streaming Response Format

For reference, the non-streaming response format:

```json
{
  "id": "msg_xxx",
  "type": "message",
  "role": "assistant",
  "content": [
    {"type": "thinking", "thinking": "..."},
    {"type": "text", "text": "Hello!"},
    {
      "type": "tool_use",
      "id": "toolu_abc123",
      "name": "get_weather",
      "input": {"location": "San Francisco"}
    }
  ],
  "model": "claude-3-opus-20240229",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 100,
    "output_tokens": 42
  }
}
```

---

## Error Event

Errors during streaming are emitted as:

```json
{
  "type": "error",
  "error": {
    "type": "api_error",
    "message": "Internal server error"
  }
}
```

**Error types:**

| HTTP Status | Error Type |
|-------------|-----------|
| 400 | `invalid_request_error` |
| 401 | `authentication_error` |
| 403 | `permission_error` |
| 404 | `not_found_error` |
| 429 | `rate_limit_error` |
| 500 | `api_error` |
| 529 | `overloaded_error` |

---

## Implementation Notes for New Providers

When building a new provider that works with the Anthropic Messages adapter (`anthropic_adapter.py`), your `stream_chat()` method must yield `StreamChunk` objects. The adapter converts them to Anthropic SSE events via `StreamChunk.to_anthropic_events()`.

### StreamChunk Fields Used by the Adapter

| Field | Anthropic Event |
|-------|----------------|
| `delta_reasoning_content` | `content_block_delta` with `thinking_delta` |
| `delta_content` | `content_block_delta` with `text_delta` |
| `tool_calls[0].id` + `function.name` | `content_block_start` with `tool_use` |
| `tool_calls[0].function.arguments` | `content_block_delta` with `input_json_delta` |
| `finish_reason` | `content_block_stop` + `message_delta` with `stop_reason` |
| `usage` | Accumulated, emitted in `message_delta.usage` |

### Key Rules

1. **Content block lifecycle**: The adapter manages `content_block_start` and `content_block_stop` events automatically. It detects transitions between block types (thinking → text → tool_use) and emits the appropriate start/stop events.

2. **Thinking → Text transition**: When the first `delta_content` arrives after `delta_reasoning_content`, the adapter closes the thinking block and opens a text block.

3. **Tool call start**: A tool call chunk with an `id` field triggers a new `content_block_start` (tool_use). The previous open block is closed first.

4. **Finish handling**: The adapter buffers the finish chunk (with `finish_reason`) and waits for the usage chunk to arrive. It then combines them into a single `message_delta` event with both `stop_reason` and `usage.output_tokens`.

5. **Usage accumulation**: Usage data from ALL chunks is accumulated. The final `message_delta` contains the total `output_tokens`.

6. **ID normalization**: All response IDs are normalized to `msg_` prefix. Provider-specific prefixes (`chatcmpl-`, `gemini-`, `resp_`) are stripped and replaced.

7. **No duplicate stops**: Each `content_block_start` has exactly one matching `content_block_stop`. The adapter prevents duplicates.

### Delta Type Summary

| Delta Type | SSE Event Type | Delta Field |
|-----------|---------------|-------------|
| Thinking text | `content_block_delta` | `{"type": "thinking_delta", "thinking": "..."}` |
| Response text | `content_block_delta` | `{"type": "text_delta", "text": "..."}` |
| Tool arguments | `content_block_delta` | `{"type": "input_json_delta", "partial_json": "..."}` |

### Request Format Differences from OpenAI

| Anthropic | OpenAI Equivalent |
|-----------|-------------------|
| `system` (top-level string) | System message in `messages` array |
| `max_tokens` (required) | `max_tokens` (optional) |
| `stop_sequences` | `stop` |
| `tools[].input_schema` | `tools[].function.parameters` |
| `tool_choice.type` | `tool_choice` (string or object) |
| `thinking.type: "enabled"` | `reasoning_effort: "high"` |
| Content type `tool_use` | `tool_calls` in assistant message |
| Content type `tool_result` | Tool role message |
