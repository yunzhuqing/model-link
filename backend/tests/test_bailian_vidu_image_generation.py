"""
百炼托管 Vidu 图像生成 provider 单元测试。

覆盖: Vidu 模型检测、image-generation/generation API 请求构建
(URL / 模型名 / 消息格式 / size 参数)、响应解析、自定义域名、
以及 BailianProvider 对 Vidu 模型的自动路由。

不访问网络 / 数据库。
Run: cd backend && uv run pytest tests/test_bailian_vidu_image_generation.py -q
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.abstraction.chat import ChatRequest
from app.abstraction.messages import ContentBlock, ContentType, Message, MessageRole
from app.providers import BailianProvider
from app.providers.base import ProviderConfig
from app.providers.bailian.image_generation import (
    BAILIAN_IMAGE_GENERATION_API_URL,
    BAILIAN_VIDU_IMAGE_MODELS,
    QWEN_IMAGE_API_URL,
    _resolve_bailian_vidu_size,
    check_bailian_image_task_status,
    execute_qwen_image_generation,
    is_bailian_vidu_image_model,
    is_qwen_image_model,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload
        self.headers = {"x-request-id": payload.get("request_id", "")}

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload, ensure_ascii=False)


class _FakeClient:
    """Stand-in for the shared httpx async client context manager."""

    def __init__(self, responses: List[Any]):
        self._responses = list(responses)
        self.requests: List[Dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, **kwargs):
        self.requests.append({"method": "POST", "url": url, "json": json, "headers": headers})
        return self._responses.pop(0)

    async def get(self, url, headers=None, **kwargs):
        self.requests.append({"method": "GET", "url": url, "headers": headers})
        return self._responses.pop(0)


def _generation_payload(
    image_url: str = "https://dashscope-result.oss-cn-beijing.aliyuncs.com/vidu.png",
    request_id: str = "req-vidu-001",
) -> Dict[str, Any]:
    return {
        "request_id": request_id,
        "output": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": [{"image": image_url}],
                        "role": "assistant",
                    },
                }
            ]
        },
        "usage": {"image_count": 1, "width": 1024, "height": 1024},
    }


def _submit_payload(task_id: str = "0385dc79-5ff8-4d82-bcb6-1234567890ab") -> Dict[str, Any]:
    """异步任务提交响应（任务创建成功，尚未完成）。"""
    return {
        "output": {
            "task_status": "PENDING",
            "task_id": task_id,
        },
        "request_id": "req-submit-001",
    }


def _query_success_payload(
    image_url: str = "https://dashscope-result.oss-cn-beijing.aliyuncs.com/vidu.png",
    task_id: str = "0385dc79-5ff8-4d82-bcb6-1234567890ab",
    request_id: str = "req-query-001",
) -> Dict[str, Any]:
    """异步任务查询响应（SUCCEEDED，含 choices 与 usage）。"""
    return {
        "request_id": request_id,
        "output": {
            "task_id": task_id,
            "task_status": "SUCCEEDED",
            "submit_time": "2026-07-13 20:27:41.291",
            "scheduled_time": "2026-07-13 20:27:41.320",
            "end_time": "2026-07-13 20:28:39.767",
            "finished": True,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": [{"image": image_url, "type": "image"}],
                    },
                }
            ],
        },
        "usage": {
            "SR": "2K",
            "size": "2048*2048",
            "image_count": 1,
        },
    }


def _chat_request(
    model: str,
    prompt: str = "一间有着精致窗户的花店",
    image_url: str = "https://example.com/reference.png",
    metadata: Dict[str, Any] | None = None,
) -> ChatRequest:
    return ChatRequest(
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentBlock(type=ContentType.TEXT, text=prompt),
                    ContentBlock(type=ContentType.IMAGE_URL, url=image_url),
                ],
            )
        ],
        model=model,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 模型检测
# ---------------------------------------------------------------------------

def test_bailian_vidu_model_detection():
    assert set(BAILIAN_VIDU_IMAGE_MODELS) == {
        "vidu/vidu-image_reference2image",
        "vidu/viduq3-fast_reference2image",
        "vidu/viduq2-pro_reference2image",
        "vidu/viduq2-fast_reference2image",
    }
    for model in BAILIAN_VIDU_IMAGE_MODELS:
        assert is_bailian_vidu_image_model(model)
        assert is_bailian_vidu_image_model(model.upper())
    assert not is_bailian_vidu_image_model("qwen-image-2.0-pro")
    assert not is_bailian_vidu_image_model("viduq2")
    assert not is_bailian_vidu_image_model("gpt-image-2")
    # Qwen 检测不受影响
    assert is_qwen_image_model("qwen-image-2.0-pro")
    assert not is_qwen_image_model("vidu/vidu-image_reference2image")


# ---------------------------------------------------------------------------
# 固定尺寸校验与归一化
# ---------------------------------------------------------------------------

def test_bailian_vidu_size_whitelist_and_normalization():
    """WxH / W*H / 大写 X / 带空格 均归一化为 W*H, 且只接受固定尺寸。"""
    model = "vidu/vidu-image_reference2image"
    # WxH 小写
    assert _resolve_bailian_vidu_size(model, {"size": "1024x1024"}) == "1024*1024"
    # WxH 大写 X
    assert _resolve_bailian_vidu_size(model, {"size": "1024X1024"}) == "1024*1024"
    # 上游 W*H 格式直通
    assert _resolve_bailian_vidu_size(model, {"size": "1024*1024"}) == "1024*1024"
    # 带空格
    assert _resolve_bailian_vidu_size(model, {"size": " 1920 x 1088 "}) == "1920*1088"
    # vidu-image 特有的非标准尺寸
    assert _resolve_bailian_vidu_size(model, {"size": "1920x1088"}) == "1920*1088"
    assert _resolve_bailian_vidu_size(model, {"size": "816x1920"}) == "816*1920"
    assert _resolve_bailian_vidu_size(model, {"size": "3840x1648"}) == "3840*1648"


def test_bailian_vidu_unsupported_size_raises():
    model = "vidu/vidu-image_reference2image"
    with pytest.raises(ValueError, match="does not support size '999x999'"):
        _resolve_bailian_vidu_size(model, {"size": "999x999"})
    with pytest.raises(ValueError, match="does not support size"):
        _resolve_bailian_vidu_size(model, {"size": "999*999"})


def test_bailian_vidu_q2_fast_only_1k():
    """viduq2-fast 仅支持 1K 档，2K/4K 尺寸应被拒绝。"""
    model = "vidu/viduq2-fast_reference2image"
    assert _resolve_bailian_vidu_size(model, {"size": "1024x1024"}) == "1024*1024"
    assert _resolve_bailian_vidu_size(model, {"size": "1584x672"}) == "1584*672"
    with pytest.raises(ValueError, match="does not support size '2048x2048'"):
        _resolve_bailian_vidu_size(model, {"size": "2048x2048"})
    with pytest.raises(ValueError, match="could not resolve size"):
        _resolve_bailian_vidu_size(model, {"resolution": "2K"})


def test_bailian_vidu_q3_fast_extra_sizes():
    """viduq3-fast 支持 1:4 / 1:8 竖幅与横幅尺寸。"""
    model = "vidu/viduq3-fast_reference2image"
    assert _resolve_bailian_vidu_size(model, {"size": "512x2064"}) == "512*2064"
    assert _resolve_bailian_vidu_size(model, {"size": "2928x352"}) == "2928*352"
    assert _resolve_bailian_vidu_size(model, {"size": "1024x4128"}) == "1024*4128"
    assert _resolve_bailian_vidu_size(model, {"size": "1408x11712"}) == "1408*11712"


def test_bailian_vidu_resolution_tier_parsing():
    """按 tier (1K/2K/4K) 与比例解析出具体像素尺寸。"""
    # vidu-image: 1K 默认 → 1024*1024
    assert _resolve_bailian_vidu_size(
        "vidu/vidu-image_reference2image", {"resolution": "1K"}
    ) == "1024*1024"
    # vidu-image: 1K + 16:9 → 1920*1088
    assert _resolve_bailian_vidu_size(
        "vidu/vidu-image_reference2image",
        {"resolution": "1K", "aspect_ratio": "16:9"},
    ) == "1920*1088"
    # vidu-image: 4K + 2:1 → 2880*1440
    assert _resolve_bailian_vidu_size(
        "vidu/vidu-image_reference2image",
        {"resolution": "4K", "aspect_ratio": "2:1"},
    ) == "2880*1440"
    # viduq3-fast: 2K + 4:5 → 1856*2304
    assert _resolve_bailian_vidu_size(
        "vidu/viduq3-fast_reference2image",
        {"resolution": "2K", "aspect_ratio": "4:5"},
    ) == "1856*2304"
    # 无任何尺寸信息 → 默认 1024*1024
    assert _resolve_bailian_vidu_size(
        "vidu/viduq2-pro_reference2image", {}
    ) == "1024*1024"


# ---------------------------------------------------------------------------
# 非流式 API 调用
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_bailian_vidu_image_generation_success(monkeypatch):
    """异步任务流程：提交 PENDING → 轮询 SUCCEEDED → 解析图片。"""
    task_id = "0385dc79-5ff8-4d82-bcb6-1234567890ab"
    fake = _FakeClient([
        _FakeResponse(200, _submit_payload(task_id)),
        _FakeResponse(200, _query_success_payload(task_id=task_id)),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    response = await execute_qwen_image_generation(
        api_key="sk-test",
        model="vidu/vidu-image_reference2image",
        messages=_chat_request(
            "vidu/vidu-image_reference2image",
            prompt="一间有着精致窗户的花店,漂亮的木质门,摆放着花朵",
            image_url="https://example.com/reference.png",
        ).messages,
        metadata={"size": "1024*1024", "response_format": "url"},
    )

    req = fake.requests[0]
    assert req["method"] == "POST"
    assert req["url"] == BAILIAN_IMAGE_GENERATION_API_URL
    assert req["url"].endswith("/api/v1/services/aigc/image-generation/generation")
    assert req["headers"]["Authorization"] == "Bearer sk-test"
    # Vidu 图片生成必须开启 Dashscope 异步任务模式
    assert req["headers"]["X-DashScope-Async"] == "enable"

    body = req["json"]
    assert body["model"] == "vidu/vidu-image_reference2image"
    messages = body["input"]["messages"]
    assert messages == [
        {
            "role": "user",
            "content": [
                {"text": "一间有着精致窗户的花店,漂亮的木质门,摆放着花朵"},
                {"image": "https://example.com/reference.png"},
            ],
        }
    ]
    # Vidu 路径只携带 size 参数，不携带 n / watermark
    assert body["parameters"] == {"size": "1024*1024"}

    # 轮询任务查询接口
    poll = fake.requests[1]
    assert poll["method"] == "GET"
    assert poll["url"] == f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

    # 响应解析为 image_generation_call 项
    items = json.loads(response.choices[0].message.get_text_content())
    assert items == [
        {
            "type": "image_generation_call",
            "status": "completed",
            "result": "https://dashscope-result.oss-cn-beijing.aliyuncs.com/vidu.png",
        }
    ]
    assert response.provider == "bailian"
    assert response.usage.extra["output_image_number"] == 1
    # 异步 usage 无 width/height：从 SR 与 size 推导
    assert response.usage.extra["output_image_resolution"] == "2K"
    assert response.usage.extra["output_image_aspect"] == "1:1"
    assert response.usage.extra["_task_id"] == "req-query-001"


@pytest.mark.asyncio
async def test_execute_bailian_vidu_submit_already_succeeded(monkeypatch):
    """提交响应直接 SUCCEEDED（罕见）→ 无需轮询，直接解析。"""
    task_id = "0385dc79-5ff8-4d82-bcb6-already-done"
    payload = _query_success_payload(task_id=task_id)
    payload["request_id"] = "req-submit-done"
    fake = _FakeClient([_FakeResponse(200, payload)])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    response = await execute_qwen_image_generation(
        api_key="sk-test",
        model="vidu/vidu-image_reference2image",
        messages=_chat_request("vidu/vidu-image_reference2image").messages,
        metadata={"size": "1024*1024"},
    )

    # 只提交，无轮询请求
    assert len(fake.requests) == 1
    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["result"].endswith("vidu.png")


@pytest.mark.asyncio
async def test_execute_bailian_vidu_task_failed(monkeypatch):
    """轮询返回 FAILED → RuntimeError 带 code/message。"""
    task_id = "0385dc79-5ff8-4d82-bcb6-failed-task"
    fake = _FakeClient([
        _FakeResponse(200, _submit_payload(task_id)),
        _FakeResponse(200, {
            "request_id": "req-failed",
            "output": {
                "task_id": task_id,
                "task_status": "FAILED",
                "code": "ImageGenerationFailed",
                "message": "image content check failed",
            },
        }),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    with pytest.raises(RuntimeError, match="Image generation task .* failed: \\[ImageGenerationFailed\\] image content check failed"):
        await execute_qwen_image_generation(
            api_key="sk-test",
            model="vidu/vidu-image_reference2image",
            messages=_chat_request("vidu/vidu-image_reference2image").messages,
            metadata={"size": "1024*1024"},
        )


@pytest.mark.asyncio
async def test_execute_bailian_vidu_no_task_id(monkeypatch):
    """提交响应缺少 task_id → RuntimeError。"""
    fake = _FakeClient([_FakeResponse(200, {"output": {}, "request_id": "req-empty"})])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    with pytest.raises(RuntimeError, match="No task_id in image generation response"):
        await execute_qwen_image_generation(
            api_key="sk-test",
            model="vidu/vidu-image_reference2image",
            messages=_chat_request("vidu/vidu-image_reference2image").messages,
            metadata={"size": "1024*1024"},
        )


@pytest.mark.asyncio
async def test_execute_bailian_vidu_poll_timeout(monkeypatch):
    """轮询超过 timeout → RuntimeError。"""
    task_id = "0385dc79-5ff8-4d82-bcb6-timeout"

    async def _fake_poll(api_key, task_id, domain=None, timeout=600, poll_interval=5.0, tracer=None):
        raise TimeoutError("Image generation task timed out")

    monkeypatch.setattr(
        "app.providers.bailian.image_generation._poll_bailian_image_task",
        _fake_poll,
    )
    fake = _FakeClient([_FakeResponse(200, _submit_payload(task_id))])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    with pytest.raises(RuntimeError, match="timed out after 600s"):
        await execute_qwen_image_generation(
            api_key="sk-test",
            model="vidu/vidu-image_reference2image",
            messages=_chat_request("vidu/vidu-image_reference2image").messages,
            metadata={"size": "1024*1024"},
        )


@pytest.mark.asyncio
async def test_execute_bailian_vidu_on_task_created_hook(monkeypatch):
    """提交成功后调用 _on_task_created hook 记录任务 ID。"""
    task_id = "0385dc79-5ff8-4d82-bcb6-hook-task"
    captured = []

    def _hook(tid: str) -> None:
        captured.append(tid)

    fake = _FakeClient([
        _FakeResponse(200, _submit_payload(task_id)),
        _FakeResponse(200, _query_success_payload(task_id=task_id)),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    await execute_qwen_image_generation(
        api_key="sk-test",
        model="vidu/vidu-image_reference2image",
        messages=_chat_request("vidu/vidu-image_reference2image").messages,
        metadata={"size": "1024*1024", "_on_task_created": _hook},
    )

    assert captured == [task_id]


@pytest.mark.asyncio
async def test_check_bailian_image_task_status(monkeypatch):
    """单次任务状态查询：成功与 HTTP 错误。"""
    task_id = "0385dc79-5ff8-4d82-bcb6-status-query"

    fake_ok = _FakeClient([_FakeResponse(200, _query_success_payload(task_id=task_id))])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake_ok)
    result = await check_bailian_image_task_status("sk-test", task_id)
    assert result["output"]["task_status"] == "SUCCEEDED"
    assert fake_ok.requests[0]["url"] == (
        f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
    )

    # 自定义域名
    fake_domain = _FakeClient([_FakeResponse(200, _query_success_payload(task_id=task_id))])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake_domain)
    await check_bailian_image_task_status("sk-test", task_id, domain="https://dashscope.example.com")
    assert fake_domain.requests[0]["url"] == (
        f"https://dashscope.example.com/api/v1/tasks/{task_id}"
    )

    # HTTP 4xx → UNKNOWN
    fake_err = _FakeClient([_FakeResponse(404, {"message": "not found"})])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake_err)
    result = await check_bailian_image_task_status("sk-test", task_id)
    assert result == {"output": {"task_status": "UNKNOWN"}}


@pytest.mark.asyncio
async def test_execute_bailian_vidu_size_normalization(monkeypatch):
    fake = _FakeClient([
        _FakeResponse(200, _submit_payload()),
        _FakeResponse(200, _query_success_payload()),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    await execute_qwen_image_generation(
        api_key="sk-test",
        model="vidu/viduq2-pro_reference2image",
        messages=_chat_request("vidu/viduq2-pro_reference2image").messages,
        metadata={"size": "1024x1024"},
    )

    body = fake.requests[0]["json"]
    # "x" 分隔的尺寸归一化为 Dashscope 的 "*" 格式
    assert body["parameters"]["size"] == "1024*1024"


@pytest.mark.asyncio
async def test_execute_bailian_vidu_default_size(monkeypatch):
    fake = _FakeClient([
        _FakeResponse(200, _submit_payload()),
        _FakeResponse(200, _query_success_payload()),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    await execute_qwen_image_generation(
        api_key="sk-test",
        model="vidu/viduq2-fast_reference2image",
        messages=_chat_request("vidu/viduq2-fast_reference2image").messages,
        metadata={},
    )

    body = fake.requests[0]["json"]
    assert body["parameters"] == {"size": "1024*1024"}


@pytest.mark.asyncio
async def test_execute_bailian_vidu_base64_image(monkeypatch):
    fake = _FakeClient([
        _FakeResponse(200, _submit_payload()),
        _FakeResponse(200, _query_success_payload()),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    request = ChatRequest(
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentBlock(type=ContentType.TEXT, text="把猫换成狗"),
                    ContentBlock(
                        type=ContentType.IMAGE_BASE64,
                        data="aGVsbG8=",
                        media_type="image/png",
                    ),
                ],
            )
        ],
        model="vidu/vidu-image_reference2image",
        metadata={},
    )

    await execute_qwen_image_generation(
        api_key="sk-test",
        model="vidu/vidu-image_reference2image",
        messages=request.messages,
        metadata=request.metadata,
    )

    body = fake.requests[0]["json"]
    content = body["input"]["messages"][0]["content"]
    assert {"image": "data:image/png;base64,aGVsbG8="} in content


@pytest.mark.asyncio
async def test_execute_bailian_vidu_custom_domain(monkeypatch):
    fake = _FakeClient([
        _FakeResponse(200, _submit_payload()),
        _FakeResponse(200, _query_success_payload()),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    await execute_qwen_image_generation(
        api_key="sk-test",
        model="vidu/viduq3-fast_reference2image",
        messages=_chat_request("vidu/viduq3-fast_reference2image").messages,
        metadata={},
        domain="https://dashscope.example.com",
    )

    req = fake.requests[0]
    assert req["url"] == "https://dashscope.example.com/api/v1/services/aigc/image-generation/generation"


@pytest.mark.asyncio
async def test_qwen_path_still_uses_multimodal_api(monkeypatch):
    """回归：qwen-image 模型继续走 multimodal-generation API 并携带 n/watermark。"""
    fake = _FakeClient([_FakeResponse(200, _generation_payload())])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    await execute_qwen_image_generation(
        api_key="sk-test",
        model="qwen-image-2.0-pro",
        messages=_chat_request("qwen-image-2.0-pro").messages,
        metadata={"size": "1024x1024", "n": 2, "watermark": True},
    )

    req = fake.requests[0]
    assert req["url"] == QWEN_IMAGE_API_URL
    assert req["url"].endswith("/api/v1/services/aigc/multimodal-generation/generation")
    # qwen 同步路径不携带异步任务头
    assert "X-DashScope-Async" not in req["headers"]
    body = req["json"]
    assert body["parameters"] == {
        "size": "1024*1024",
        "n": 2,
        "watermark": True,
    }


# ---------------------------------------------------------------------------
# Provider 路由
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bailian_provider_routes_vidu_models(monkeypatch):
    fake = _FakeClient([
        _FakeResponse(200, _submit_payload()),
        _FakeResponse(200, _query_success_payload()),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    provider = BailianProvider(ProviderConfig(name="bailian", api_key="sk-test", base_url=None))
    request = _chat_request(
        "vidu/vidu-image_reference2image",
        metadata={"size": "1024*1024"},
    )

    response = await provider.chat(request)

    req = fake.requests[0]
    assert req["url"] == BAILIAN_IMAGE_GENERATION_API_URL
    assert req["json"]["model"] == "vidu/vidu-image_reference2image"
    assert req["json"]["parameters"] == {"size": "1024*1024"}
    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["type"] == "image_generation_call"

    # 模型列表包含 Vidu 模型
    model_ids = {m["id"] for m in provider.list_models()}
    assert model_ids >= set(BAILIAN_VIDU_IMAGE_MODELS)


@pytest.mark.asyncio
async def test_bailian_provider_is_image_generation_model():
    provider = BailianProvider(ProviderConfig(name="bailian", api_key="sk-test", base_url=None))
    assert provider.is_image_generation_model("vidu/vidu-image_reference2image")
    assert provider.is_image_generation_model("vidu/viduq2-fast_reference2image")
    assert provider.is_image_generation_model("qwen-image-2.0-pro")
    assert not provider.is_image_generation_model("qwen-plus")


# ---------------------------------------------------------------------------
# 后台任务状态检查（resync）
# ---------------------------------------------------------------------------

def test_langfuse_detect_type_image_generation_body():
    """Dashscope 风格请求体（input.messages 为 dict）不应导致 _detect_type 抛异常。"""
    from app.monitoring.langfuse_tracer import _detect_type, _derive_model_prefix

    body = {
        "model": "vidu/vidu-image_reference2image",
        "input": {"messages": [{"role": "user", "content": [{"text": "hi"}]}]},
        "parameters": {"size": "1024*1024"},
    }
    assert _detect_type(body) == "generation"
    # 带 / 前缀的模型名 → 干净的 provider 前缀
    assert _derive_model_prefix("vidu/vidu-image_reference2image") == "vidu"
    assert _derive_model_prefix("qwen-image-2.0-pro") == "qwen"


@pytest.mark.asyncio
async def test_execute_bailian_vidu_tracing_uses_generation_obs(monkeypatch):
    """langfuse span 必须以 generation 类型记录生图请求明细。"""
    class _FakeSpan:
        def __init__(self):
            self.outputs = []
            self.ended = False

        def log_input(self, data):
            self.inputs = data

        def log_output(self, data):
            self.outputs.append(data)

        def end(self, error=None):
            self.ended = True

    class _FakeTracer:
        def __init__(self):
            self.calls = []
            self.span = _FakeSpan()

        def start_child(self, name, model=None, provider_type="", obs_type=None, input_data=None):
            self.calls.append({
                "name": name,
                "obs_type": obs_type,
                "provider_type": provider_type,
                "input_data": input_data,
            })
            return self.span

    task_id = "0385dc79-5ff8-4d82-bcb6-trace-task"
    fake = _FakeClient([
        _FakeResponse(200, _submit_payload(task_id)),
        _FakeResponse(200, _query_success_payload(task_id=task_id)),
    ])
    monkeypatch.setattr("app.providers.bailian.image_generation.shared_client", lambda: fake)

    tracer = _FakeTracer()
    await execute_qwen_image_generation(
        api_key="sk-test",
        model="vidu/vidu-image_reference2image",
        messages=_chat_request("vidu/vidu-image_reference2image").messages,
        metadata={"size": "1024*1024"},
        tracer=tracer,
    )

    # 生图主 span：显式 generation 类型 + 请求体作为 input
    assert tracer.calls[0]["obs_type"] == "generation"
    assert tracer.calls[0]["provider_type"] == "bailian"
    assert tracer.calls[0]["input_data"]["model"] == "vidu/vidu-image_reference2image"
    # 轮询 span：span 类型，并记录每次轮询状态
    assert tracer.calls[1]["obs_type"] == "span"
    assert any(o.get("task_status") == "SUCCEEDED" for o in tracer.span.outputs)
    assert tracer.span.ended


@pytest.mark.asyncio
async def test_task_status_checker_bailian_image_output(monkeypatch):
    """后台 resync：百炼图片任务 SUCCEEDED → 解析出 image_generation_call 输出。"""
    from app.usagerecord.task_status_checker import (
        TaskStatus,
        resolve_and_check_task_status_async,
    )

    task_id = "0385dc79-5ff8-4d82-bcb6-resync-task"

    async def _fake_creds(provider_id):
        return {
            "id": provider_id,
            "type": "bailian",
            "api_key": "sk-test",
            "base_url": "",
            "extra_config": {},
        }

    class _PollClient:
        def __init__(self, payload):
            self._payload = payload

        async def get(self, url, headers=None):
            return _FakeResponse(200, self._payload)

    monkeypatch.setattr(
        "app.usagerecord.task_status_checker._lookup_provider_credentials_async",
        _fake_creds,
    )

    async def _fake_poll_client():
        return _PollClient(_query_success_payload(task_id=task_id))

    monkeypatch.setattr(
        "app.usagerecord.task_status_checker._get_poll_client",
        _fake_poll_client,
    )

    result = await resolve_and_check_task_status_async({
        "task_id": task_id,
        "provider_id": 1,
        "model": "vidu/vidu-image_reference2image",
    })

    assert result.status == TaskStatus.COMPLETED
    assert result.output_items == [{
        "type": "image_generation_call",
        "status": "completed",
        "result": "https://dashscope-result.oss-cn-beijing.aliyuncs.com/vidu.png",
    }]
