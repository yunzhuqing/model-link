# Fix: reasoning input item dropped when forwarding to Volcengine/Doubao

## Context

Multi-turn `/v1/responses` 请求中，如果 input 包含上一轮返回的 `reasoning` item：

```json
{"type": "reasoning", "id": "rs_...", "summary": [{"type": "summary_text", "text": "..."}]}
```

转发给 Volcengine/Doubao 时 reasoning 被丢弃，导致模型缺少推理上下文。

### 数据流追踪

1. **responses_adapter.py:340** `_handle_reasoning_item()` — 正确解析为 `Message(role=ASSISTANT, reasoning_content="...")`
2. **volcengine/base.py:140** `_prepare_responses_request()` — 调用 `_message_to_input_item()` 逐条转换
3. **volcengine/base.py:227** `_message_to_input_item()` — **没有处理 `reasoning_content`**，走到 "Regular message" 路径，生成 `{"role": "assistant", "content": [{"type": "output_text", "text": "(empty)"}]}`
4. **volcengine/base.py:172-191** partial assistant 逻辑 — 检测到空 assistant，直接 pop 删除

### 共享函数同样有此问题

`_responses_format.py:182` `_message_to_responses_items()` 也没有处理 ASSISTANT 消息的 `reasoning_content`，影响 Azure、OpenAI Responses Compatible、Tencent VOD 等使用该函数的 provider。

## 修改方案

### 1. `backend/app/providers/volcengine/base.py` — `_message_to_input_item()` (line 279)

在现有 ASSISTANT 处理块之前，加入 reasoning_content 检查。重写 ASSISTANT 分支使其同时处理 reasoning + text + tool_calls：

```python
# ── Handle assistant messages (reasoning / tool_calls / text) ──
if message.role == MessageRole.ASSISTANT:
    items = []

    # Emit reasoning item if present
    if message.reasoning_content:
        items.append({
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": message.reasoning_content}]
        })

    # Handle tool calls in content blocks
    if isinstance(message.content, list):
        has_tool_calls = any(
            isinstance(b, ContentBlock) and b.type == ContentType.TOOL_CALL
            for b in message.content
        )
        if has_tool_calls:
            for block in message.content:
                if isinstance(block, ContentBlock) and block.type == ContentType.TOOL_CALL:
                    args = block.tool_arguments
                    if isinstance(args, dict):
                        args = json.dumps(args, ensure_ascii=False)
                    items.append({
                        "type": "function_call",
                        "call_id": block.tool_call_id or "",
                        "name": block.tool_name or "",
                        "arguments": args or "{}"
                    })
            # Also include text content as a regular message if present
            text_blocks = [b for b in message.content
                           if isinstance(b, ContentBlock) and b.type == ContentType.TEXT and b.text]
            if text_blocks:
                content_parts = [{"type": "output_text", "text": b.text} for b in text_blocks]
                # Insert message item before function_call items
                msg_item = {"type": "message", "role": "assistant", "content": content_parts, "status": "completed"}
                # Find first function_call index and insert before it
                fc_idx = next((i for i, it in enumerate(items) if it.get("type") == "function_call"), len(items))
                items.insert(fc_idx, msg_item)
            return items

    # Regular message (text content only or empty)
    if items:
        # Has reasoning but also has regular content — append message item
        content = self._convert_content(message)
        if isinstance(content, str) and content and content != "(empty)":
            items.append({"role": "assistant", "content": content, "type": "message", "status": "completed"})
        elif isinstance(content, list):
            has_real = any(
                p.get("text", "").strip() and p.get("text") != "(empty)"
                for p in content if isinstance(p, dict)
            )
            if has_real:
                items.append({"role": "assistant", "content": content, "type": "message", "status": "completed"})
        return items

    # No reasoning — fall through to existing regular message logic
    content = self._convert_content(message)
    item = {"role": "assistant", "content": content, "type": "message", "status": "completed"}
    return item
```

### 2. `backend/app/providers/_responses_format.py` — `_message_to_responses_items()` (line 211)

在 ASSISTANT 分支中添加 reasoning item 输出（用于 Azure、OpenAI Compatible 等 provider）：

```python
if role == MessageRole.ASSISTANT:
    result = []

    # Emit reasoning item if present
    if message.reasoning_content:
        result.append({
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": message.reasoning_content}]
        })

    # ...existing tool_call + text handling...
```

## 验证

1. `cd backend && uv run pytest` — 确认现有测试不受影响
2. 新增测试用例：创建含 `reasoning_content` 的 ASSISTANT Message → `_prepare_responses_request()` → 断言 output 包含 `reasoning` input item
3. 手动测试：向 doubao-seed 发送含 reasoning item 的多轮 `/v1/responses` 请求，确认推理上下文被保留
