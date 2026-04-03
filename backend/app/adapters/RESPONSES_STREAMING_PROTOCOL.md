# OpenAI Responses API Streaming Protocol

This document defines the exact SSE (Server-Sent Events) sequence that the `/v1/responses` endpoint must emit when `"stream": true`. All providers (Azure, Gemini, Bailian, OpenAI, etc.) are adapted to produce this unified event sequence via `responses_adapter.py`.

---

## Event Sequence Overview

```
response.created
response.in_progress

// [Optional] Reasoning Summary Section
response.output_item.added          → type: "reasoning"
response.reasoning_summary_part.added
response.reasoning_summary_text.delta  (repeated)
response.reasoning_summary_text.done
response.reasoning_summary_part.done   → part.type == "summary_text"
response.output_item.done             → item.type == "reasoning", includes item.summary

// [Optional] Text Content Section
response.output_item.added          → type: "message"
response.content_part.added
response.output_text.delta            (repeated)
response.output_text.done            → includes full concatenated text
response.content_part.done           → includes full concatenated text
response.output_item.done           → type: "message"

// [Optional] Function Call Section (repeated per function call)
response.output_item.added          → type: "function_call"
response.function_call_arguments.delta  (repeated)
response.function_call_arguments.done
response.output_item.done           → type: "function_call"

// End
response.completed                  → output includes ALL data (reasoning, function_calls, message)
```

---

## Detailed Event Definitions

### 1. `response.created`

Emitted once at the start of the stream.

```json
{
  "type": "response.created",
  "response": {
    "id": "resp_xxx",
    "object": "response",
    "created_at": 1234567890,
    "model": "gpt-4o",
    "status": "in_progress",
    "output": []
  }
}
```

### 2. `response.in_progress`

Emitted once immediately after `response.created`.

```json
{
  "type": "response.in_progress",
  "response": {
    "id": "resp_xxx",
    "object": "response",
    "created_at": 1234567890,
    "model": "gpt-4o",
    "status": "in_progress",
    "output": []
  }
}
```

---

### 3. Reasoning Summary Section (Optional)

Only emitted when the model produces reasoning/thinking content (e.g., `o1`, `o3`, `qwen-plus` with thinking enabled).

**Reasoning uses its own `output_index`** (typically `0`), separate from the text message.

#### 3.1 `response.output_item.added` (reasoning)

```json
{
  "type": "response.output_item.added",
  "output_index": 0,
  "item": {
    "type": "reasoning",
    "id": "rs_xxx",
    "status": "in_progress",
    "summary": []
  }
}
```

#### 3.2 `response.reasoning_summary_part.added`

```json
{
  "type": "response.reasoning_summary_part.added",
  "item_id": "rs_xxx",
  "output_index": 0,
  "summary_index": 0,
  "part": {
    "type": "summary_text",
    "text": ""
  }
}
```

#### 3.3 `response.reasoning_summary_text.delta` (repeated)

```json
{
  "type": "response.reasoning_summary_text.delta",
  "item_id": "rs_xxx",
  "output_index": 0,
  "summary_index": 0,
  "delta": "Let me think about this..."
}
```

#### 3.4 `response.reasoning_summary_text.done`

```json
{
  "type": "response.reasoning_summary_text.done",
  "item_id": "rs_xxx",
  "output_index": 0,
  "summary_index": 0,
  "text": "Let me think about this... [full reasoning text]"
}
```

#### 3.5 `response.reasoning_summary_part.done`

```json
{
  "type": "response.reasoning_summary_part.done",
  "item_id": "rs_xxx",
  "output_index": 0,
  "summary_index": 0,
  "part": {
    "type": "summary_text",
    "text": "Let me think about this... [full reasoning text]"
  }
}
```

#### 3.6 `response.output_item.done` (reasoning)

Must include `item.summary` with the full reasoning text.

```json
{
  "type": "response.output_item.done",
  "output_index": 0,
  "item": {
    "type": "reasoning",
    "id": "rs_xxx",
    "status": "completed",
    "summary": [
      {
        "type": "summary_text",
        "text": "Let me think about this... [full reasoning text]"
      }
    ]
  }
}
```

---

### 4. Text Content Section (Optional)

Only emitted when the model produces text content. Skipped for function-call-only responses.

**Text message uses the next available `output_index`** (e.g., `1` if reasoning exists, `0` if not).

#### 4.1 `response.output_item.added` (message)

```json
{
  "type": "response.output_item.added",
  "output_index": 1,
  "item": {
    "type": "message",
    "id": "msg_xxx",
    "role": "assistant",
    "status": "in_progress",
    "content": []
  }
}
```

#### 4.2 `response.content_part.added`

```json
{
  "type": "response.content_part.added",
  "item_id": "msg_xxx",
  "output_index": 1,
  "content_index": 0,
  "part": {
    "type": "output_text",
    "text": "",
    "annotations": []
  }
}
```

#### 4.3 `response.output_text.delta` (repeated)

```json
{
  "type": "response.output_text.delta",
  "item_id": "msg_xxx",
  "output_index": 1,
  "content_index": 0,
  "delta": "Hello"
}
```

#### 4.4 `response.output_text.done`

Contains the full concatenated text (all deltas joined).

```json
{
  "type": "response.output_text.done",
  "item_id": "msg_xxx",
  "output_index": 1,
  "content_index": 0,
  "text": "Hello, how can I help you today?"
}
```

#### 4.5 `response.content_part.done`

```json
{
  "type": "response.content_part.done",
  "item_id": "msg_xxx",
  "output_index": 1,
  "content_index": 0,
  "part": {
    "type": "output_text",
    "text": "Hello, how can I help you today?",
    "annotations": []
  }
}
```

#### 4.6 `response.output_item.done` (message)

```json
{
  "type": "response.output_item.done",
  "output_index": 1,
  "item": {
    "type": "message",
    "id": "msg_xxx",
    "role": "assistant",
    "status": "completed",
    "content": [
      {
        "type": "output_text",
        "text": "Hello, how can I help you today?",
        "annotations": []
      }
    ]
  }
}
```

---

### 5. Function Call Section (Optional, Repeated per Function Call)

Each function call is an independent output item with its own `output_index`.

#### 5.1 `response.output_item.added` (function_call)

```json
{
  "type": "response.output_item.added",
  "output_index": 2,
  "item": {
    "id": "fc_xxx",
    "type": "function_call",
    "status": "in_progress",
    "arguments": "",
    "call_id": "call_abc123",
    "name": "get_weather"
  }
}
```

#### 5.2 `response.function_call_arguments.delta` (repeated)

Arguments may arrive as a single complete JSON string (Gemini) or as incremental fragments (Azure/OpenAI).

```json
{
  "type": "response.function_call_arguments.delta",
  "output_index": 2,
  "delta": "{\"location\": \"San Francisco\"}"
}
```

#### 5.3 `response.function_call_arguments.done`

Contains the full accumulated arguments string.

```json
{
  "type": "response.function_call_arguments.done",
  "output_index": 2,
  "arguments": "{\"location\": \"San Francisco\"}"
}
```

#### 5.4 `response.output_item.done` (function_call)

```json
{
  "type": "response.output_item.done",
  "output_index": 2,
  "item": {
    "id": "fc_xxx",
    "type": "function_call",
    "status": "completed",
    "arguments": "{\"location\": \"San Francisco\"}",
    "call_id": "call_abc123",
    "name": "get_weather"
  }
}
```

---

### 6. `response.completed`

Emitted exactly **once** at the very end of the stream. The `output` array must include **ALL** output items (reasoning, function_calls, message) accumulated during the stream.

```json
{
  "type": "response.completed",
  "response": {
    "id": "resp_xxx",
    "object": "response",
    "status": "completed",
    "model": "gpt-4o",
    "output": [
      {
        "type": "reasoning",
        "id": "rs_xxx",
        "summary": [
          { "type": "summary_text", "text": "..." }
        ]
      },
      {
        "type": "function_call",
        "id": "fc_xxx",
        "call_id": "call_abc123",
        "name": "get_weather",
        "arguments": "{\"location\": \"San Francisco\"}",
        "status": "completed"
      },
      {
        "type": "message",
        "id": "msg_xxx",
        "role": "assistant",
        "status": "completed",
        "content": [
          { "type": "output_text", "text": "...", "annotations": [] }
        ]
      }
    ],
    "usage": {
      "input_tokens": 100,
      "output_tokens": 50,
      "total_tokens": 150,
      "input_tokens_details": { "cached_tokens": 0 },
      "output_tokens_details": { "reasoning_tokens": 20 }
    }
  }
}
```

---

## Output Index Rules

The `output_index` field tracks the position of each output item in the response's `output` array. It is assigned dynamically based on the order items appear:

| Section | output_index |
|---------|-------------|
| Reasoning (if present) | 0 |
| Text Message (if present) | next available (0 or 1) |
| Function Call 1 | next available |
| Function Call 2 | next available |
| ... | ... |

**Examples:**

- **Text-only response**: message at index `0`
- **Reasoning + Text**: reasoning at `0`, message at `1`
- **Function-calls only**: function_call_1 at `0`, function_call_2 at `1`
- **Reasoning + Function-calls**: reasoning at `0`, function_call_1 at `1`, function_call_2 at `2`

---

## Common Scenarios

### Scenario A: Simple Text Response

```
response.created
response.in_progress
response.output_item.added          (message, index=0)
response.content_part.added
response.output_text.delta          ×N
response.output_text.done
response.content_part.done
response.output_item.done           (message)
response.completed
```

### Scenario B: Reasoning + Text Response

```
response.created
response.in_progress
response.output_item.added          (reasoning, index=0)
response.reasoning_summary_part.added
response.reasoning_summary_text.delta   ×N
response.reasoning_summary_text.done
response.reasoning_summary_part.done
response.output_item.done           (reasoning)
response.output_item.added          (message, index=1)
response.content_part.added
response.output_text.delta          ×N
response.output_text.done
response.content_part.done
response.output_item.done           (message)
response.completed
```

### Scenario C: Function Calls Only (No Text)

```
response.created
response.in_progress
response.output_item.added          (function_call_1, index=0)
response.function_call_arguments.delta   ×N
response.function_call_arguments.done
response.output_item.done           (function_call_1)
response.output_item.added          (function_call_2, index=1)
response.function_call_arguments.delta   ×N
response.function_call_arguments.done
response.output_item.done           (function_call_2)
response.completed
```

### Scenario D: Text + Function Calls

```
response.created
response.in_progress
response.output_item.added          (message, index=0)
response.content_part.added
response.output_text.delta          ×N
response.output_text.done
response.content_part.done
response.output_item.done           (message)
response.output_item.added          (function_call_1, index=1)
response.function_call_arguments.delta   ×N
response.function_call_arguments.done
response.output_item.done           (function_call_1)
response.completed
```

### Scenario E: Reasoning + Function Calls (No Text)

```
response.created
response.in_progress
response.output_item.added          (reasoning, index=0)
response.reasoning_summary_part.added
response.reasoning_summary_text.delta   ×N
response.reasoning_summary_text.done
response.reasoning_summary_part.done
response.output_item.done           (reasoning)
response.output_item.added          (function_call_1, index=1)
response.function_call_arguments.delta   ×N
response.function_call_arguments.done
response.output_item.done           (function_call_1)
response.completed
```

---

## Implementation Notes for New Providers

When building a new provider that works with the Responses API adapter (`responses_adapter.py`), your `stream_chat()` method must yield `StreamChunk` objects. The adapter handles all event formatting. Here are the key rules:

### StreamChunk Fields Used by the Adapter

| Field | Purpose |
|-------|---------|
| `id` | Response ID (used in `response.completed`) |
| `model` | Model name |
| `delta_content` | Incremental text content (each chunk is one delta) |
| `delta_reasoning_content` | Incremental reasoning/thinking text |
| `delta_role` | Role string (`"assistant"` for role-only marker chunks) |
| `tool_calls` | List of tool call dicts (see format below) |
| `finish_reason` | `FinishReason` enum value when generation is complete |
| `usage` | Dict with `prompt_tokens`, `completion_tokens`, `total_tokens` |
| `raw_sse_passthrough` | List of raw SSE strings to forward verbatim |

### Tool Call Dict Format

Each entry in `tool_calls` list:

```python
# First chunk for a new tool call (must have "id"):
{
    "id": "call_abc123",       # REQUIRED for new tool call start
    "index": 0,                # Optional: used for index→call_id mapping
    "function": {
        "name": "get_weather", # Function name
        "arguments": "..."     # Arguments (complete or partial JSON string)
    }
}

# Subsequent delta chunks (arguments only, no "id"):
{
    "index": 0,                # Used to identify which tool call
    "function": {
        "arguments": "..."     # Incremental argument fragment
    }
}
```

### Key Rules

1. **Text content**: Yield chunks with `delta_content` set to each text fragment. The adapter accumulates the full text and emits `output_text.done` with the complete text at the end.

2. **Reasoning**: Yield chunks with `delta_reasoning_content`. The adapter handles all reasoning summary events.

3. **Tool calls**: For each new tool call, yield a chunk with `tool_calls` containing an entry with `id` (the call_id) and `function.name`. For argument deltas, yield chunks with `tool_calls` containing entries with just `function.arguments`.

4. **Finish**: Yield a chunk with `finish_reason` set (e.g., `FinishReason.STOP` or `FinishReason.TOOL_CALLS`).

5. **Usage**: Yield a chunk with `usage` dict. Can be combined with the finish chunk or sent separately.

6. **Argument accumulation**: The adapter accumulates tool call arguments across multiple deltas. It emits `function_call_arguments.done` and `output_item.done` automatically when the accumulated arguments form valid JSON.

7. **No duplicate events**: The adapter prevents duplicate `response.completed` events via internal tracking.

8. **Gemini-style providers**: If your provider sends all function call arguments in a single chunk (complete JSON), the adapter handles this correctly — `arguments.done` and `output_item.done` fire immediately.

9. **Azure-style providers**: If your provider sends arguments as incremental fragments across multiple chunks, the adapter accumulates them and fires done events only when the full JSON is assembled.
