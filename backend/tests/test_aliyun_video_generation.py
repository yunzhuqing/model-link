"""
阿里云 (yike) 视频生成 provider 单元测试。

覆盖: RPC 签名 (与官方 tea-openapi 算法一致), SubmitVideoGenerationJob /
GetVideoGenerationJob 请求构造与响应解析, Input JSON / Medias 构建,
JobType 推断, 非流式/流式执行流程, Provider 配置解析与分发。

不访问网络 / 数据库。
Run: cd backend && uv run pytest tests/test_aliyun_video_generation.py -q
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from typing import Any, Dict, List
from urllib.parse import quote, quote_plus

import pytest

from app.abstraction.chat import ChatRequest, FinishReason
from app.abstraction.messages import ContentBlock, ContentType, Message, MessageRole
from app.abstraction.streaming import StreamEventType
from app.providers import AliyunProvider, get_provider_class
from app.providers.base import ProviderConfig
from app.providers.aliyun.video_generation import (
    ALIYUN_VIDEO_MODELS,
    DEFAULT_ENDPOINT,
    YIKE_API_VERSION,
    _build_media_list,
    _extract_text_prompt,
    _fetch_job_credit,
    _normalize_duration,
    build_input_json,
    build_rpc_params,
    execute_video_generation,
    get_video_generation_job,
    _substitute_prompt_vars,
    delete_medias,
    get_yike_job_credit,
    import_media,
    infer_job_type,
    is_aliyun_video_model,
    parse_output_medias,
    resolve_yike_endpoint,
    stream_video_generation,
    submit_video_generation_job,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload, ensure_ascii=False)


class _FakeClient:
    """Stand-in for the shared httpx async client."""

    def __init__(self, responses: List[Any]):
        self._responses = list(responses)
        self.requests: List[Dict[str, Any]] = []

    async def post(self, url, content=None, headers=None, **kwargs):
        self.requests.append({
            "url": url, "content": content or "", "headers": headers or {}, "kwargs": kwargs,
        })
        return self._responses.pop(0)


def _submit_ok_payload(job_id: str = "job-12345", request_id: str = "req-abcde") -> Dict[str, Any]:
    return {"RequestId": request_id, "JobId": job_id}


def _job_payload(
    status: str,
    *,
    job_id: str = "job-12345",
    output_medias: str = "",
    error_message: str = "",
) -> Dict[str, Any]:
    job: Dict[str, Any] = {
        "JobId": job_id,
        "Status": status,
        "Model": "wonder-pro",
        "Resolution": "720P",
        "AspectRatio": "16:9",
        "Duration": "5s",
        "N": 1,
        "JobType": "text_to_video",
        "Scene": "general",
    }
    if output_medias:
        job["Output"] = output_medias
    if error_message:
        job["ErrorMessage"] = error_message
    return {"RequestId": "req-abcde", "VideoGenerationJob": job}


def _credit_payload(cost: float = 12.5, status: str = "Generated") -> Dict[str, Any]:
    return {
        "RequestId": "req-credit",
        "JobId": "job-12345",
        "JobCreditCost": cost,
        "CreditStatus": status,
    }


def _chat_request(model: str = "wonder-pro", prompt: str = "一只猫", metadata: Dict[str, Any] | None = None, messages: List[Message] | None = None) -> ChatRequest:
    return ChatRequest(
        messages=messages or [Message(role=MessageRole.USER, content=prompt)],
        model=model,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# RPC 签名
# ---------------------------------------------------------------------------

def _reference_rpc_signature(signed_params: Dict[str, Any], method: str, secret: str) -> str:
    """官方 tea-openapi get_rpcsignature 的逐行复刻, 用于交叉验证。"""
    queries = signed_params.copy()
    keys = sorted(queries)
    canonicalized = ""
    for k in keys:
        if queries[k] is not None:
            canonicalized += f'&{quote(k, safe="~")}={quote(str(queries[k]), safe="~")}'
    string_to_sign = f'{method}&%2F&{quote_plus(canonicalized[1:], safe="~")}'
    digest = hmac.new(
        bytes(secret + "&", encoding="utf-8"),
        bytes(string_to_sign, encoding="utf-8"),
        digestmod=hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_rpc_signature_matches_official_sdk_algorithm():
    params = {
        "AccessKeyId": "testid",
        "Action": "SubmitVideoGenerationJob",
        "Format": "json",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": "3ee8c1b8-83d3-44af-a94f-4e0ad82fd6cf",
        "SignatureVersion": "1.0",
        "Timestamp": "2016-02-23T12:46:24Z",
        "Version": "2014-05-26",
        "JobType": "text_to_video",
        "Model": "wonder-pro",
        "Input": '{"Prompt": "一只猫", "Medias": [{"Type": "image", "URL": "https://x/1.jpg"}]}',
    }
    # 固定 nonce/timestamp, 保证确定性
    query = build_rpc_params(
        action="SubmitVideoGenerationJob",
        version="2014-05-26",
        access_key_id="testid",
        access_key_secret="testsecret",
        params={k: v for k, v in params.items() if k not in (
            "Action", "Format", "SignatureMethod", "SignatureNonce",
            "SignatureVersion", "Timestamp", "Version", "AccessKeyId",
        )},
        timestamp="2016-02-23T12:46:24Z",
        signature_nonce="3ee8c1b8-83d3-44af-a94f-4e0ad82fd6cf",
    )
    expected = _reference_rpc_signature(params, "POST", "testsecret")
    assert query["Signature"] == expected
    assert query["Action"] == "SubmitVideoGenerationJob"
    assert query["Format"] == "json"
    assert query["Version"] == "2014-05-26"
    assert query["AccessKeyId"] == "testid"
    assert query["SignatureMethod"] == "HMAC-SHA1"
    assert query["SignatureVersion"] == "1.0"


def test_rpc_query_encodes_utf8_and_special_chars():
    query = build_rpc_params(
        action="SubmitVideoGenerationJob",
        version=YIKE_API_VERSION,
        access_key_id="ak",
        access_key_secret="sk",
        params={"Input": '{"Prompt": "你好 world", "Medias": [{"URL": "https://x/a b.jpg"}]}', "N": 2},
        timestamp="2026-01-01T00:00:00Z",
        signature_nonce="nonce-1",
    )
    # 签名参数包含公共参数 + 动作参数 (Input 含 UTF-8 / 空格 / 冒号)
    signed = {
        "AccessKeyId": "ak",
        "Action": "SubmitVideoGenerationJob",
        "Format": "json",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": "nonce-1",
        "SignatureVersion": "1.0",
        "Timestamp": "2026-01-01T00:00:00Z",
        "Version": YIKE_API_VERSION,
        "Input": '{"Prompt": "你好 world", "Medias": [{"URL": "https://x/a b.jpg"}]}',
        "N": 2,
    }
    assert query["Signature"] == _reference_rpc_signature(signed, "POST", "sk")
    # 公共参数 (含 Signature) 进入 query, 动作参数进入 form body
    assert "Input" not in query


def test_resolve_yike_endpoint():
    assert resolve_yike_endpoint(None, None) == DEFAULT_ENDPOINT
    assert resolve_yike_endpoint("ap-southeast-1", None) == "yike.ap-southeast-1.aliyuncs.com"
    assert resolve_yike_endpoint("cn-hangzhou", None) == DEFAULT_ENDPOINT  # 未注册区域回退默认
    assert resolve_yike_endpoint("cn-shanghai", "https://my.endpoint.com") == "my.endpoint.com"
    assert resolve_yike_endpoint(None, "yike.custom.aliyuncs.com") == "yike.custom.aliyuncs.com"


# ---------------------------------------------------------------------------
# 参数构造
# ---------------------------------------------------------------------------

def test_normalize_duration():
    # yike API 要求纯秒数字符串; "6s" 会被上游以 InvalidParameter.Duration 拒绝
    assert _normalize_duration(None) == "5"
    assert _normalize_duration("5s") == "5"
    assert _normalize_duration("6s") == "6"
    assert _normalize_duration("10") == "10"
    assert _normalize_duration(6) == "6"
    assert _normalize_duration("4") == "4"
    assert _normalize_duration("6.0") == "6"


def test_build_input_json_and_job_type_inference():
    media = [{"Type": "image", "Url": "https://x/1.jpg"}]
    input_json = build_input_json(prompt="一只猫", media=media)
    parsed = json.loads(input_json)
    assert parsed == {"Prompt": "一只猫", "Medias": [{"Type": "image", "Url": "https://x/1.jpg"}]}

    assert infer_job_type([]) == "text_to_video"
    assert infer_job_type([{"Type": "image", "Url": "a"}]) == "image_to_video"
    assert infer_job_type([
        {"Type": "image", "Url": "a"},
        {"Type": "image", "Url": "b"},
    ]) == "first_last_frame"
    assert infer_job_type([
        {"Type": "image", "Url": "a"},
        {"Type": "video", "Url": "b"},
    ]) == "reference_to_video"


def test_build_media_list_from_messages_and_metadata():
    messages = [
        Message(role=MessageRole.USER, content=[
            ContentBlock.from_text("把这只猫变成机器人"),
            ContentBlock.from_image_url("https://x/cat.jpg"),
            ContentBlock.from_video_url("https://x/clip.mp4"),
        ]),
    ]
    metadata = {
        "last_frame_url": "https://x/end.jpg",
        "reference_images": ["https://x/ref1.jpg"],
        "file_id_media_map": {
            "file-1": {"type": "image", "url": "https://x/map1.jpg"},
            "file-2": {"type": "video", "url": "https://x/map2.mp4"},
        },
    }
    media = _build_media_list(messages, metadata)
    urls = [m["Url"] for m in media]
    assert urls == [
        "https://x/cat.jpg",
        "https://x/clip.mp4",
        "https://x/map1.jpg",
        "https://x/map2.mp4",
        "https://x/ref1.jpg",
        "https://x/end.jpg",
    ]
    assert media[0]["Type"] == "image"
    assert media[1]["Type"] == "video"


def test_extract_text_prompt_strips_file_templates():
    messages = [
        Message(role=MessageRole.USER, content="第一段"),
        Message(role=MessageRole.SYSTEM, content="系统提示"),
        Message(role=MessageRole.USER, content="参考 {{file-abc123def456}} 生成"),
    ]
    assert _extract_text_prompt(messages) == "第一段参考 生成"


def test_parse_output_medias():
    output = '{"Medias": [{"MediaId": "m1", "OutputUrl": "https://v/1.mp4"}, {"MediaId": "m2", "OuputUrl": "https://v/2.mp4"}]}'
    medias = parse_output_medias(output)
    assert medias == [
        {"MediaId": "m1", "OutputUrl": "https://v/1.mp4"},
        {"MediaId": "m2", "OutputUrl": "https://v/2.mp4"},
    ]
    assert parse_output_medias("") == []
    assert parse_output_medias("not-json") == []
    assert parse_output_medias('{"Other": 1}') == []


# ---------------------------------------------------------------------------
# SubmitVideoGenerationJob / GetVideoGenerationJob
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_video_generation_job():
    client = _FakeClient([_FakeResponse(200, _submit_ok_payload())])
    result = await submit_video_generation_job(
        client,
        access_key_id="ak-test",
        access_key_secret="sk-test",
        job_type="image_to_video",
        model="wonder-pro",
        input_json='{"Prompt": "猫", "Medias": [{"Type": "image", "URL": "https://x/1.jpg"}]}',
        resolution="1080p",
        aspect_ratio="9:16",
        duration=6,
        n=2,
        scene="general",
    )
    assert result == {"RequestId": "req-abcde", "JobId": "job-12345"}

    req = client.requests[0]
    assert "Action=SubmitVideoGenerationJob" in req["url"]
    assert "Signature=" in req["url"]
    assert "Version=2026-03-19" in req["url"]
    assert req["headers"]["x-acs-action"] == "SubmitVideoGenerationJob"
    assert req["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    body = dict(pair.split("=", 1) for pair in req["content"].split("&"))
    from urllib.parse import unquote
    body = {k: unquote(v) for k, v in body.items()}
    assert body["JobType"] == "image_to_video"
    assert body["Model"] == "wonder-pro"
    assert body["Resolution"] == "1080P"  # 归一化大写
    assert body["AspectRatio"] == "9:16"
    assert body["Duration"] == "6"  # 纯秒数字符串, 不带 "s" 后缀
    assert body["N"] == "2"
    assert body["Scene"] == "general"
    assert json.loads(body["Input"])["Prompt"] == "猫"


@pytest.mark.asyncio
async def test_submit_video_generation_job_error():
    client = _FakeClient([_FakeResponse(400, {
        "Code": "InvalidParameter",
        "Message": "model not supported",
        "RequestId": "req-err",
    })])
    with pytest.raises(RuntimeError, match="InvalidParameter"):
        await submit_video_generation_job(
            client,
            access_key_id="ak", access_key_secret="sk",
            job_type="text_to_video", model="bad-model", input_json='{"Prompt": "x"}',
        )


@pytest.mark.asyncio
async def test_submit_missing_job_id_raises():
    client = _FakeClient([_FakeResponse(200, {"RequestId": "req-1"})])
    with pytest.raises(RuntimeError, match="JobId"):
        await submit_video_generation_job(
            client,
            access_key_id="ak", access_key_secret="sk",
            job_type="text_to_video", model="wonder-pro", input_json='{"Prompt": "x"}',
        )


@pytest.mark.asyncio
async def test_submit_video_generation_job_version_override():
    client = _FakeClient([_FakeResponse(200, _submit_ok_payload())])
    await submit_video_generation_job(
        client,
        access_key_id="ak", access_key_secret="sk",
        job_type="text_to_video", model="wonder-pro",
        input_json='{"Prompt": "x"}',
        version="2026-07-07",
    )
    assert "Version=2026-07-07" in client.requests[0]["url"]
    assert "Version=2026-03-19" not in client.requests[0]["url"]


@pytest.mark.asyncio
async def test_get_video_generation_job():
    client = _FakeClient([_FakeResponse(200, _job_payload("Executing"))])
    result = await get_video_generation_job(
        client,
        access_key_id="ak", access_key_secret="sk",
        job_id="job-12345",
    )
    req = client.requests[0]
    assert "Action=GetVideoGenerationJob" in req["url"]
    assert "JobId=job-12345" in req["content"]
    assert result["VideoGenerationJob"]["Status"] == "Executing"


@pytest.mark.asyncio
async def test_get_video_generation_job_version_override():
    client = _FakeClient([_FakeResponse(200, _job_payload("Finished"))])
    await get_video_generation_job(
        client,
        access_key_id="ak", access_key_secret="sk",
        job_id="job-12345",
        version="2026-07-07",
    )
    assert "Version=2026-07-07" in client.requests[0]["url"]


def test_responses_adapter_usage_carries_credits():
    """Responses API 表面: usage 需带上 yike 积分字段 (credits / credit_status)。"""
    from app.abstraction.chat import ChatResponse, ChatChoice, UsageInfo
    from app.adapters.responses_adapter import OpenAIResponsesAdapter

    usage = UsageInfo(
        prompt_tokens=0, completion_tokens=5, total_tokens=5,
        extra={"credits": 12.5, "credit_status": "Generated", "_task_id": "job-1"},
    )
    resp = ChatResponse(
        id="resp_1", created=0, model="wonder-pro",
        choices=[ChatChoice(
            index=0,
            message=Message(role=MessageRole.ASSISTANT, content="[]"),
            finish_reason=FinishReason.STOP,
        )],
        usage=usage,
    )
    formatted = OpenAIResponsesAdapter().format_response(resp)
    assert formatted["usage"]["credits"] == 12.5
    assert formatted["usage"]["credit_status"] == "Generated"
    assert "_task_id" not in formatted["usage"]


@pytest.mark.asyncio
async def test_get_yike_job_credit():
    client = _FakeClient([_FakeResponse(200, _credit_payload(cost=6.25))])
    result = await get_yike_job_credit(
        client,
        access_key_id="ak", access_key_secret="sk",
        job_id="job-12345",
    )
    req = client.requests[0]
    assert "Action=GetYikeJobCredit" in req["url"]
    assert "Version=2026-03-19" in req["url"]
    assert "JobId=job-12345" in req["content"]
    assert result["JobCreditCost"] == 6.25
    assert result["CreditStatus"] == "Generated"


@pytest.mark.asyncio
async def test_get_yike_job_credit_version_override():
    client = _FakeClient([_FakeResponse(200, _credit_payload())])
    await get_yike_job_credit(
        client,
        access_key_id="ak", access_key_secret="sk",
        job_id="job-12345",
        version="2026-07-07",
    )
    assert "Version=2026-07-07" in client.requests[0]["url"]


@pytest.mark.asyncio
async def test_get_yike_job_credit_error():
    client = _FakeClient([_FakeResponse(400, {
        "Code": "InvalidParameter",
        "Message": "job not found",
        "RequestId": "req-err",
    })])
    with pytest.raises(RuntimeError, match="GetYikeJobCredit.*InvalidParameter"):
        await get_yike_job_credit(
            client,
            access_key_id="ak", access_key_secret="sk",
            job_id="job-404",
        )


@pytest.mark.asyncio
async def test_fetch_job_credit_best_effort(monkeypatch):
    """积分查询失败不应影响任务结果 (usage 中无 credits 字段)。"""

    async def failing_shared_client():
        raise RuntimeError("credit api down")

    monkeypatch.setattr("app.http_client.get_shared_client", failing_shared_client)
    credit = await _fetch_job_credit(
        access_key_id="ak", access_key_secret="sk", job_id="job-12345",
    )
    assert credit is None


@pytest.mark.asyncio
async def test_execute_video_generation_credit_unavailable(monkeypatch):
    """GetYikeJobCredit 返回错误时, 任务仍成功且 usage 不含 credits。"""
    client = _FakeClient([
        _FakeResponse(200, _submit_ok_payload()),
        _FakeResponse(200, _job_payload(
            "Finished",
            output_medias='{"Medias": [{"MediaId": "m1", "OutputUrl": "https://v/1.mp4"}]}',
        )),
        _FakeResponse(400, {"Code": "Forbidden", "Message": "no credit permission"}),
    ])

    async def fake_shared_client():
        return client

    monkeypatch.setattr("app.http_client.get_shared_client", fake_shared_client)

    request = _chat_request()
    response = await execute_video_generation(
        access_key_id="ak", access_key_secret="sk",
        model="wonder-pro",
        messages=request.messages,
        metadata=request.metadata,
    )
    assert response.choices[0].finish_reason == FinishReason.STOP
    assert "credits" not in response.usage.extra


@pytest.mark.asyncio
async def test_delete_medias_legacy_version():
    """默认版本 2026-03-19 → DeleteYikeAssetMediaInfos + LogicDelete=false (物理删除)。"""
    client = _FakeClient([_FakeResponse(200, {"RequestId": "req-del"})])
    result = await delete_medias(
        client,
        access_key_id="ak", access_key_secret="sk",
        media_ids=["media-1", "media-2"],
        delete_physical_files=True,
    )
    assert result["RequestId"] == "req-del"

    req = client.requests[0]
    assert "Action=DeleteYikeAssetMediaInfos" in req["url"]
    assert "Version=2026-03-19" in req["url"]
    assert req["headers"]["x-acs-action"] == "DeleteYikeAssetMediaInfos"

    from urllib.parse import unquote
    body = dict(pair.split("=", 1) for pair in req["content"].split("&"))
    body = {k: unquote(v) for k, v in body.items()}
    assert body["MediaIds"] == "media-1,media-2"
    assert body["LogicDelete"] == "false"


@pytest.mark.asyncio
async def test_delete_medias_new_version():
    """2026-07-07+ → DeleteMedias + DeletePhysicalFiles。"""
    client = _FakeClient([_FakeResponse(200, {"RequestId": "req-del"})])
    await delete_medias(
        client,
        access_key_id="ak", access_key_secret="sk",
        media_ids="media-1,media-2",
        delete_physical_files=True,
        version="2026-07-07",
    )
    req = client.requests[0]
    assert "Action=DeleteMedias" in req["url"]
    assert "Version=2026-07-07" in req["url"]

    from urllib.parse import unquote
    body = dict(pair.split("=", 1) for pair in req["content"].split("&"))
    body = {k: unquote(v) for k, v in body.items()}
    assert body["MediaIds"] == "media-1,media-2"
    assert body["DeletePhysicalFiles"] == "true"


@pytest.mark.asyncio
async def test_delete_medias_logic_delete_when_keeping_files():
    """delete_physical_files=False → 旧版 LogicDelete=true (保留文件)。"""
    client = _FakeClient([_FakeResponse(200, {"RequestId": "req-del"})])
    await delete_medias(
        client,
        access_key_id="ak", access_key_secret="sk",
        media_ids=["media-1"],
        delete_physical_files=False,
    )
    from urllib.parse import unquote
    body = dict(pair.split("=", 1) for pair in client.requests[0]["content"].split("&"))
    body = {k: unquote(v) for k, v in body.items()}
    assert body["LogicDelete"] == "true"


@pytest.mark.asyncio
async def test_delete_medias_validation_and_error():
    client = _FakeClient([_FakeResponse(400, {
        "Code": "InvalidParameter", "Message": "media not found", "RequestId": "req-err",
    })])
    with pytest.raises(ValueError, match="MediaIds"):
        await delete_medias(client, access_key_id="ak", access_key_secret="sk", media_ids=[])
    with pytest.raises(RuntimeError, match="DeleteYikeAssetMediaInfos.*InvalidParameter"):
        await delete_medias(client, access_key_id="ak", access_key_secret="sk", media_ids=["media-x"])


@pytest.mark.asyncio
async def test_import_media():
    client = _FakeClient([_FakeResponse(200, {"RequestId": "req-import", "MediaId": "media-12345"})])
    result = await import_media(
        client,
        access_key_id="ak", access_key_secret="sk",
        input_url="https://x/ref.jpg",
        media_type="image",
        register_config={"NeedThirdPartyAsset": True},
    )
    assert result == {"RequestId": "req-import", "MediaId": "media-12345"}

    req = client.requests[0]
    assert "Action=ImportMedia" in req["url"]
    assert "Version=2026-03-19" in req["url"]
    assert req["headers"]["x-acs-action"] == "ImportMedia"

    from urllib.parse import unquote
    body = dict(pair.split("=", 1) for pair in req["content"].split("&"))
    body = {k: unquote(v) for k, v in body.items()}
    assert body["ImportSource"] == "url"
    assert body["InputURL"] == "https://x/ref.jpg"
    assert body["MediaType"] == "image"
    assert json.loads(body["RegisterConfig"]) == {"NeedThirdPartyAsset": True}


@pytest.mark.asyncio
async def test_import_media_need_third_party_asset_shorthand():
    client = _FakeClient([_FakeResponse(200, {"RequestId": "r", "MediaId": "media-1"})])
    await import_media(
        client,
        access_key_id="ak", access_key_secret="sk",
        input_url="https://x/1.png",
        media_type="image",
        need_third_party_asset=True,
    )
    from urllib.parse import unquote
    body = dict(pair.split("=", 1) for pair in client.requests[0]["content"].split("&"))
    body = {k: unquote(v) for k, v in body.items()}
    assert json.loads(body["RegisterConfig"]) == {"NeedThirdPartyAsset": True}


@pytest.mark.asyncio
async def test_import_media_normalizes_media_type_and_missing_url():
    client = _FakeClient([_FakeResponse(200, {"RequestId": "r", "MediaId": "media-1"})])
    await import_media(
        client, access_key_id="ak", access_key_secret="sk",
        input_url="https://x/a.mp4", media_type="VIDEO",
    )
    from urllib.parse import unquote
    body = dict(pair.split("=", 1) for pair in client.requests[0]["content"].split("&"))
    assert unquote(body["MediaType"]) == "video"

    with pytest.raises(ValueError, match="MediaType"):
        await import_media(
            client, access_key_id="ak", access_key_secret="sk",
            input_url="https://x/1.png", media_type="png",
        )
    with pytest.raises(ValueError, match="InputURL"):
        await import_media(
            client, access_key_id="ak", access_key_secret="sk",
            input_url="", media_type="image",
        )


@pytest.mark.asyncio
async def test_import_media_error():
    client = _FakeClient([_FakeResponse(400, {
        "Code": "InvalidParameter",
        "Message": "url not accessible",
        "RequestId": "req-err",
    })])
    with pytest.raises(RuntimeError, match="ImportMedia.*InvalidParameter"):
        await import_media(
            client, access_key_id="ak", access_key_secret="sk",
            input_url="https://x/1.jpg", media_type="image",
        )


def test_build_media_list_media_id_sources():
    """Medias 支持 MediaId (消息块 / metadata / yike:// 前缀 / 引用列表)。"""
    block_with_media_id = ContentBlock(type=ContentType.IMAGE_URL, url="")
    block_with_media_id.media_id = "media-block-1"

    messages = [
        Message(role=MessageRole.USER, content=[
            ContentBlock.from_text("用这张图"),
            ContentBlock.from_image_url("https://x/1.jpg"),
            block_with_media_id,
        ]),
    ]
    metadata = {
        "file_id_media_map": {
            "file-aaa": {"type": "image", "url": "yike://media-map-1"},
            "file-bbb": {"type": "video", "media_id": "media-map-2"},
            "file-ccc": {"type": "image", "url": "https://x/2.jpg"},
        },
        "reference_images": [
            {"media_id": "media-ref-1"},
            {"url": "yike://media-ref-2"},
            "https://x/3.jpg",
        ],
        "first_frame_url": {"media_id": "media-ff-1"},
        "last_frame_url": "yike://media-lf-1",
    }
    media = _build_media_list(messages, metadata)
    assert media == [
        {"Type": "image", "Url": "https://x/1.jpg"},
        {"Type": "image", "MediaId": "media-block-1"},
        {"Type": "image", "MediaId": "media-map-1"},
        {"Type": "video", "MediaId": "media-map-2"},
        {"Type": "image", "Url": "https://x/2.jpg"},
        {"Type": "image", "MediaId": "media-ref-1"},
        {"Type": "image", "MediaId": "media-ref-2"},
        {"Type": "image", "Url": "https://x/3.jpg"},
        {"Type": "image", "MediaId": "media-ff-1"},
        {"Type": "image", "MediaId": "media-lf-1"},
    ]


@pytest.mark.asyncio
async def test_resolve_file_ids_aliyun_uses_yike_prefix():
    """file_id 解析: Aliyun 上传的素材映射为 yike://{MediaId}。"""
    from app.models import UploadedFile
    from app.middleware.gateway_service import GatewayService

    class _FakeScalars:
        def __init__(self, records):
            self._records = records
        def all(self):
            return self._records

    class _FakeResult:
        def __init__(self, records):
            self._records = records
        def scalars(self):
            return _FakeScalars(self._records)

    class _FakeSession:
        def __init__(self, records):
            self._records = records
        async def execute(self, query):
            return _FakeResult(self._records)

    records = [
        UploadedFile(file_id="file-aliyun", object_key="media-ali-1", type="aliyun"),
        UploadedFile(file_id="file-volc", object_key="asset-volc-1", type="volcengine"),
    ]
    request = ChatRequest(
        messages=[Message(role=MessageRole.USER, content="图 {{file-aliyun}}")],
        model="wonder-pro",
        metadata={"file_id_media_map": {
            "file-aliyun": {"type": "image", "url": "file-aliyun"},
            "file-volc": {"type": "image", "url": "file-volc"},
        }},
    )
    await GatewayService._resolve_file_ids(request, _FakeSession(records))
    fid_map = request.metadata["file_id_media_map"]
    assert fid_map["file-aliyun"]["url"] == "yike://media-ali-1"
    assert fid_map["file-volc"]["url"] == "asset://asset-volc-1"


@pytest.mark.asyncio
async def test_videos_collect_media_media_id_and_url():
    from app.routes.videos import _collect_media

    media, var_map = await _collect_media({
        "images": ["https://x/1.jpg", {"media_id": "media-1", "var_id": "cat"}],
        "videos": [{"url": "https://v/1.mp4", "var_id": "clip"}],
        "first_frame_url": {"media_id": "media-ff"},
        "last_frame_url": "https://x/last.jpg",
    })
    assert media == [
        {"Type": "image", "Url": "https://x/1.jpg"},
        {"Type": "image", "MediaId": "media-1"},
        {"Type": "video", "Url": "https://v/1.mp4"},
        {"Type": "image", "MediaId": "media-ff"},
        {"Type": "image", "Url": "https://x/last.jpg"},
    ]
    assert var_map == {"cat": ("image", 2), "clip": ("video", 1)}


@pytest.mark.asyncio
async def test_videos_collect_media_resolves_file_id(monkeypatch):
    from app.models import UploadedFile
    from app.routes.videos import _collect_media

    class _FakeScalars:
        def __init__(self, records):
            self._records = records
        def all(self):
            return self._records

    class _FakeResult:
        def __init__(self, records):
            self._records = records
        def scalars(self):
            return _FakeScalars(self._records)

    class _FakeSession:
        async def execute(self, query):
            return _FakeResult([
                UploadedFile(file_id="file-aliyun", object_key="media-ali-1",
                             type="aliyun", storage_key="https://orig/1.jpg"),
                UploadedFile(file_id="file-volc", object_key="asset-volc-1",
                             type="volcengine", storage_key=""),
            ])

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_db():
        yield _FakeSession()

    import app.routes.videos as videos_route
    monkeypatch.setattr(videos_route, "get_db_session", fake_db)

    media, var_map = await _collect_media({
        "images": [{"file_id": "file-aliyun", "var_id": "cat"}],
        "videos": [{"file_id": "file-volc"}],
    })
    assert media == [
        {"Type": "image", "MediaId": "media-ali-1"},
        {"Type": "video", "Url": "asset://asset-volc-1"},
    ]
    assert var_map == {"cat": ("image", 1)}

    with pytest.raises(ValueError, match="File not found"):
        await _collect_media({"images": ["file-missing"]})


@pytest.mark.asyncio
async def test_get_aliyun_credentials():
    """files 路由的 Aliyun 凭证解析: extra_config 优先, 兼容 AK:SK api_key。"""
    from app.models import Provider
    from app.routes.files import _get_aliyun_credentials

    class _FakeScalars:
        def __init__(self, records):
            self._records = records
        def all(self):
            return self._records
        def first(self):
            return self._records[0] if self._records else None

    class _FakeResult:
        def __init__(self, records):
            self._records = records
        def scalars(self):
            return _FakeScalars(self._records)

    class _FakeSession:
        def __init__(self, records):
            self._records = records
        async def execute(self, query):
            return _FakeResult(self._records)

    provider = Provider(
        type="aliyun", name="aliyun-1", group_id=1, is_active=True,
        api_key="", extra_config={
            "access_key_id": "AK-EXTRA", "access_key_secret": "SK-EXTRA",
            "region": "ap-southeast-1", "api_version": "2026-07-07",
        },
    )
    creds = await _get_aliyun_credentials(_FakeSession([provider]), 1)
    assert creds["vendor"] == "aliyun"
    assert creds["access_key_id"] == "AK-EXTRA"
    assert creds["access_key_secret"] == "SK-EXTRA"
    assert creds["region"] == "ap-southeast-1"
    assert creds["api_version"] == "2026-07-07"
    assert creds["provider_id"] is None

    provider2 = Provider(
        type="aliyun", name="aliyun-2", group_id=1, is_active=True,
        api_key="AK-KEY:SK-KEY", extra_config={},
    )
    creds2 = await _get_aliyun_credentials(_FakeSession([provider2]), 1)
    assert creds2["access_key_id"] == "AK-KEY"
    assert creds2["access_key_secret"] == "SK-KEY"

    provider3 = Provider(
        type="aliyun", name="aliyun-3", group_id=1, is_active=True,
        api_key="", extra_config={},
    )
    with pytest.raises(RuntimeError, match="missing credentials"):
        await _get_aliyun_credentials(_FakeSession([provider3]), 1)

    with pytest.raises(RuntimeError, match="No active Aliyun provider"):
        await _get_aliyun_credentials(_FakeSession([]), 1)


def test_substitute_prompt_vars():
    """{{var_id}} → 阿里云变量名 (图/视频/音频分别计数, 中英文)。"""
    var_map = {
        "cat": ("image", 1),
        "room": ("image", 2),
        "clip": ("video", 1),
        "song": ("audio", 1),
    }
    # 中文 prompt → 中文变量名
    assert _substitute_prompt_vars(
        "{{cat}} 在图里, {{room}} 是房间, {{clip}} 是参考视频", var_map
    ) == "图 1 在图里, 图 2 是房间, 视频 1 是参考视频"
    # 英文 prompt → 英文变量名
    assert _substitute_prompt_vars(
        "The cat in {{cat}} runs, audio {{song}}", var_map
    ) == "The cat in Image 1 runs, audio Audio 1"
    # 未命中的占位符保持原样
    assert _substitute_prompt_vars("{{missing}} 和 {{cat}}", var_map) == "{{missing}} 和 图 1"
    # 空输入
    assert _substitute_prompt_vars("", var_map) == ""
    assert _substitute_prompt_vars("plain text", {}) == "plain text"


def test_build_media_list_var_map():
    """var_id 收集: 图片/视频分别计数, 媒体项不携带 var_id 字段。"""
    messages = [
        Message(role=MessageRole.USER, content=[
            ContentBlock.from_text("参考"),
            ContentBlock.from_image_url("https://x/1.jpg"),
        ]),
    ]
    metadata = {
        "file_id_media_map": {
            "file-a": {"type": "image", "url": "https://x/a.jpg", "var_id": "cat"},
            "file-b": {"type": "video", "media_id": "media-b", "var_id": "clip"},
            "file-c": {"type": "image", "url": "https://x/c.jpg"},
        },
        "reference_audios": [{"url": "https://x/s.mp3", "var_id": "song"}],
    }
    media, var_map = _build_media_list(messages, metadata, return_vars=True)
    # 消息块里的 https://x/1.jpg 先占 image 1; cat 是第 2 张图
    assert var_map == {"cat": ("image", 2), "clip": ("video", 1), "song": ("audio", 1)}
    assert media[0] == {"Type": "image", "Url": "https://x/1.jpg"}
    # yike 的 Medias 不带 var_id 字段
    for item in media:
        assert "var_id" not in item
        assert "_var_id" not in item
    # 非 return_vars 模式保持旧返回类型
    assert _build_media_list(messages, metadata) == media


@pytest.mark.asyncio
async def test_execute_video_generation_prompt_var_substitution(monkeypatch):
    """execute 提交时 Prompt 中的 {{var_id}} 被替换为阿里云变量名。"""
    client = _FakeClient([
        _FakeResponse(200, _submit_ok_payload()),
        _FakeResponse(200, _job_payload(
            "Finished",
            output_medias='{"Medias": [{"MediaId": "m1", "OutputUrl": "https://v/1.mp4"}]}',
        )),
        _FakeResponse(200, _credit_payload()),
    ])

    async def fake_shared_client():
        return client

    monkeypatch.setattr("app.http_client.get_shared_client", fake_shared_client)

    request = _chat_request(
        prompt="让 {{cat}} 里的猫奔跑",
        metadata={"reference_images": [{"url": "https://x/cat.jpg", "var_id": "cat"}]},
    )
    await execute_video_generation(
        access_key_id="ak", access_key_secret="sk",
        model="wonder-pro",
        messages=request.messages,
        metadata=request.metadata,
    )
    from urllib.parse import unquote
    body = dict(pair.split("=", 1) for pair in client.requests[0]["content"].split("&"))
    body = {k: unquote(v) for k, v in body.items()}
    parsed = json.loads(body["Input"])
    assert parsed["Prompt"] == "让 图 1 里的猫奔跑"
    assert parsed["Medias"] == [{"Type": "image", "Url": "https://x/cat.jpg"}]


def test_normalize_input_raw_input_var_id_stripped():
    """raw input: Medias 项的 var_id 被剥离, Prompt 的 {{var_id}} 被替换。"""
    from app.routes.videos import _normalize_input

    out = _normalize_input(
        raw_input={
            "Prompt": "{{cat}} 奔跑",
            "Medias": [
                {"Type": "image", "Url": "https://x/a.jpg", "var_id": "cat"},
                {"Type": "video", "Url": "https://x/b.mp4", "VarId": "clip"},
            ],
        },
    )
    parsed = json.loads(out)
    assert parsed["Prompt"] == "图 1 奔跑"
    assert parsed["Medias"] == [
        {"Type": "image", "Url": "https://x/a.jpg"},
        {"Type": "video", "Url": "https://x/b.mp4"},
    ]


# ---------------------------------------------------------------------------
# 非流式执行 (submit + poll)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_video_generation_success(monkeypatch):
    client = _FakeClient([
        _FakeResponse(200, _submit_ok_payload()),
        _FakeResponse(200, _job_payload(
            "Finished",
            output_medias='{"Medias": [{"MediaId": "m1", "OutputUrl": "https://v/1.mp4"}]}',
        )),
        _FakeResponse(200, _credit_payload(cost=12.5)),
    ])

    async def fake_shared_client():
        return client

    monkeypatch.setattr("app.http_client.get_shared_client", fake_shared_client)

    hook_calls: List[str] = []
    request = _chat_request(
        prompt="一只猫在奔跑",
        metadata={
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "seconds": 5,
            "n": 1,
            "_on_task_created": hook_calls.append,
        },
    )
    response = await execute_video_generation(
        access_key_id="ak",
        access_key_secret="sk",
        model="wonder-pro",
        messages=request.messages,
        metadata=request.metadata,
    )
    assert hook_calls == ["job-12345"]
    assert response.provider == "aliyun"
    assert response.id.startswith("vid_")
    assert response.choices[0].finish_reason == FinishReason.STOP

    items = json.loads(response.choices[0].message.get_text_content())
    assert items[0]["type"] == "video_generation_call"
    assert items[0]["status"] == "completed"
    assert items[0]["result"] == "https://v/1.mp4"

    assert response.usage.extra["output_video_number"] == 1
    assert response.usage.extra["output_video_resolution"] == "720P"
    assert response.usage.extra["output_video_aspect"] == "16:9"
    assert response.usage.extra["output_video_seconds"] == 5.0
    assert response.usage.extra["_task_id"] == "job-12345"
    assert response.usage.extra["credits"] == 12.5
    assert response.usage.extra["credit_status"] == "Generated"

    # 提交 + 轮询 + 积分查询
    assert len(client.requests) == 3
    assert "Action=GetYikeJobCredit" in client.requests[2]["url"]
    assert "JobId=job-12345" in client.requests[2]["content"]


@pytest.mark.asyncio
async def test_execute_video_generation_failed(monkeypatch):
    client = _FakeClient([
        _FakeResponse(200, _submit_ok_payload()),
        _FakeResponse(200, _job_payload("Failed", error_message="模型欠费")),
    ])

    async def fake_shared_client():
        return client

    monkeypatch.setattr("app.http_client.get_shared_client", fake_shared_client)

    request = _chat_request()
    with pytest.raises(RuntimeError, match="模型欠费"):
        await execute_video_generation(
            access_key_id="ak", access_key_secret="sk",
            model="wonder-pro",
            messages=request.messages,
            metadata=request.metadata,
        )


@pytest.mark.asyncio
async def test_execute_video_generation_image_to_video(monkeypatch):
    """图生视频: 媒体来自消息 content block, JobType 自动推断为 image_to_video。"""
    messages = [
        Message(role=MessageRole.USER, content=[
            ContentBlock.from_text("放大这张图"),
            ContentBlock.from_image_url("https://x/ref.jpg"),
        ]),
    ]
    client = _FakeClient([
        _FakeResponse(200, _submit_ok_payload()),
        _FakeResponse(200, _job_payload(
            "Finished",
            output_medias='{"Medias": [{"MediaId": "m1", "OutputUrl": "https://v/out.mp4"}]}',
        )),
        _FakeResponse(200, _credit_payload()),
    ])

    async def fake_shared_client():
        return client

    monkeypatch.setattr("app.http_client.get_shared_client", fake_shared_client)

    request = _chat_request(messages=messages, metadata={})
    await execute_video_generation(
        access_key_id="ak", access_key_secret="sk",
        model="wonder-pro",
        messages=request.messages,
        metadata=request.metadata,
    )
    body = dict(pair.split("=", 1) for pair in client.requests[0]["content"].split("&"))
    from urllib.parse import unquote
    body = {k: unquote(v) for k, v in body.items()}
    assert body["JobType"] == "image_to_video"
    parsed = json.loads(body["Input"])
    assert parsed["Medias"] == [{"Type": "image", "Url": "https://x/ref.jpg"}]


# ---------------------------------------------------------------------------
# 流式执行
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_video_generation(monkeypatch):
    client = _FakeClient([
        _FakeResponse(200, _submit_ok_payload()),
        _FakeResponse(200, _job_payload(
            "Executing",
        )),
        _FakeResponse(200, _job_payload(
            "Finished",
            output_medias='{"Medias": [{"MediaId": "m1", "OutputUrl": "https://v/out.mp4"}]}',
        )),
        _FakeResponse(200, _credit_payload(cost=8.0)),
    ])

    async def fake_shared_client():
        return client

    monkeypatch.setattr("app.http_client.get_shared_client", fake_shared_client)

    request = _chat_request(metadata={"resolution": "720p"})
    chunks = []
    async for chunk in stream_video_generation(None, request):
        chunks.append(chunk)

    deltas = [c.delta_content for c in chunks if c.delta_content]
    assert any("任务已提交" in d for d in deltas)
    assert any("状态: Executing" in d for d in deltas)
    assert any("https://v/out.mp4" in d for d in deltas)

    done = [c for c in chunks if c.event_type == StreamEventType.DONE]
    assert len(done) == 1
    assert done[0].finish_reason == FinishReason.STOP
    assert done[0].usage.extra["output_video_seconds"] == 5.0
    assert done[0].usage.extra["credits"] == 8.0
    assert done[0].usage.extra["credit_status"] == "Generated"

    # 带 tool_calls 的视频块
    tool_chunks = [c for c in chunks if c.tool_calls]
    assert tool_chunks
    assert tool_chunks[0].tool_calls[0]["type"] == "video_generation_call"
    assert tool_chunks[0].tool_calls[0]["result"] == "https://v/out.mp4"


@pytest.mark.asyncio
async def test_stream_video_generation_error(monkeypatch):
    client = _FakeClient([_FakeResponse(500, {"Code": "InternalError", "Message": "boom"})])

    async def fake_shared_client():
        return client

    monkeypatch.setattr("app.http_client.get_shared_client", fake_shared_client)

    request = _chat_request()
    chunks = []
    async for chunk in stream_video_generation(None, request):
        chunks.append(chunk)
    done = [c for c in chunks if c.event_type == StreamEventType.DONE]
    assert done and done[0].finish_reason == FinishReason.ERROR


# ---------------------------------------------------------------------------
# Provider 配置与分发
# ---------------------------------------------------------------------------

def test_aliyun_provider_config_from_extra_config():
    provider = AliyunProvider(ProviderConfig(
        name="aliyun-test",
        api_key="",
        extra_config={
            "access_key_id": "AK123",
            "access_key_secret": "SK456",
            "region": "ap-southeast-1",
            "api_version": "2026-07-07",
        },
    ))
    assert provider.access_key_id == "AK123"
    assert provider.access_key_secret == "SK456"
    assert provider.region == "ap-southeast-1"
    assert provider.endpoint is None
    assert provider.api_version == "2026-07-07"


def test_aliyun_provider_config_from_api_key():
    provider = AliyunProvider(ProviderConfig(
        name="aliyun-test",
        api_key="AK123:SK456",
    ))
    assert provider.access_key_id == "AK123"
    assert provider.access_key_secret == "SK456"
    assert provider.region == "cn-shanghai"


def test_aliyun_provider_config_missing_credentials():
    with pytest.raises(ValueError, match="access_key_id"):
        AliyunProvider(ProviderConfig(name="aliyun-test", api_key=""))


def test_aliyun_provider_registered():
    assert get_provider_class("aliyun") is AliyunProvider


def test_model_detection():
    for model in ALIYUN_VIDEO_MODELS:
        assert is_aliyun_video_model(model)
    assert is_aliyun_video_model("WONDER-PRO")
    assert is_aliyun_video_model("aliyun/wan2.7")
    assert not is_aliyun_video_model("gpt-4o")
    assert not is_aliyun_video_model("happyhorse-1.0-t2v")  # 百炼的型号不属于 yike 供应商


@pytest.mark.asyncio
async def test_aliyun_provider_chat_rejects_non_video_model():
    provider = AliyunProvider(ProviderConfig(
        name="aliyun-test",
        api_key="AK123:SK456",
    ))
    with pytest.raises(RuntimeError, match="only supports video generation"):
        await provider.chat(_chat_request(model="gpt-4o", prompt="hi"))


@pytest.mark.asyncio
async def test_aliyun_provider_chat_dispatch(monkeypatch):
    from app.abstraction.chat import ChatResponse, ChatChoice, UsageInfo
    from app.providers.aliyun import base as aliyun_base

    captured: Dict[str, Any] = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return ChatResponse(
            id="vid_test", created=0, model=kwargs["model"],
            choices=[ChatChoice(index=0, message=Message(role=MessageRole.ASSISTANT, content="[]"), finish_reason=FinishReason.STOP)],
            usage=UsageInfo(), provider="aliyun",
        )

    monkeypatch.setattr(aliyun_base, "execute_video_generation", fake_execute)

    provider = AliyunProvider(ProviderConfig(
        name="aliyun-test",
        api_key="AK123:SK456",
        extra_config={"region": "ap-southeast-1"},
    ))
    request = _chat_request(model="wonder-pro", prompt="一只猫")
    await provider.chat(request)
    assert captured["access_key_id"] == "AK123"
    assert captured["access_key_secret"] == "SK456"
    assert captured["model"] == "wonder-pro"
    assert captured["region"] == "ap-southeast-1"


@pytest.mark.asyncio
async def test_aliyun_provider_stream_chat_injects_credentials(monkeypatch):
    from app.providers.aliyun import base as aliyun_base
    from app.abstraction.chat import ChatResponse, ChatChoice, UsageInfo

    captured: Dict[str, Any] = {}

    async def fake_stream(chat_fn, request):
        captured["metadata"] = dict(request.metadata)
        yield None

    monkeypatch.setattr(aliyun_base, "stream_video_generation", fake_stream)

    provider = AliyunProvider(ProviderConfig(
        name="aliyun-test",
        api_key="AK123:SK456",
    ))
    request = _chat_request(model="wan2.7", prompt="猫")
    chunks = []
    async for chunk in provider.stream_chat(request):
        chunks.append(chunk)
    assert captured["metadata"]["_access_key_id"] == "AK123"
    assert captured["metadata"]["_access_key_secret"] == "SK456"
    assert captured["metadata"]["_region"] == "cn-shanghai"
    assert captured["metadata"]["_api_version"] is None


@pytest.mark.asyncio
async def test_aliyun_provider_get_job_credit(monkeypatch):
    from app.providers.aliyun import base as aliyun_base

    captured: Dict[str, Any] = {}

    async def fake_credit(client, **kwargs):
        captured.update(kwargs)
        return {"RequestId": "req-1", "JobId": "job-1", "JobCreditCost": 3.5, "CreditStatus": "Generated"}

    monkeypatch.setattr(aliyun_base, "get_yike_job_credit", fake_credit)

    provider = AliyunProvider(ProviderConfig(
        name="aliyun-test",
        api_key="AK123:SK456",
        extra_config={"api_version": "2026-07-07"},
    ))
    result = await provider.get_job_credit("job-1")
    assert result["JobCreditCost"] == 3.5
    assert captured["job_id"] == "job-1"
    assert captured["version"] == "2026-07-07"
    assert captured["access_key_id"] == "AK123"


# ---------------------------------------------------------------------------
# GatewayService 中间件包装
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gateway_service_submit_video_generation():
    from app.middleware.gateway_service import GatewayService
    from app.request_context import ResolvedModelData

    class _FakeVideoProvider:
        async def submit_video_generation(self, params):
            return {"RequestId": "req-1", "JobId": "job-1"}

    service = GatewayService()
    resolved = ResolvedModelData(
        provider_id=1, provider_name="aliyun-test", provider_type="aliyun",
        model_real_name="wonder-pro", provider_instance=_FakeVideoProvider(),
    )
    result = await service.submit_video_generation(
        resolved, {"job_type": "text_to_video"},
    )
    assert result == {"RequestId": "req-1", "JobId": "job-1"}


@pytest.mark.asyncio
async def test_gateway_service_submit_video_generation_unsupported_provider():
    from app.middleware.gateway_service import GatewayService, GatewayServiceError
    from app.request_context import ResolvedModelData

    class _NoVideoProvider:
        pass

    service = GatewayService()
    resolved = ResolvedModelData(
        provider_id=1, provider_name="openai", provider_type="openai",
        model_real_name="gpt-4o", provider_instance=_NoVideoProvider(),
    )
    with pytest.raises(GatewayServiceError, match="does not support video generation"):
        await service.submit_video_generation(resolved, {})


@pytest.mark.asyncio
async def test_gateway_service_get_video_generation_wraps_provider_error():
    from app.middleware.gateway_service import GatewayService, ProviderError
    from app.request_context import ResolvedModelData

    class _FailingProvider:
        async def get_video_generation(self, job_id, request_id=None):
            raise RuntimeError("upstream boom")

    service = GatewayService()
    resolved = ResolvedModelData(
        provider_id=1, provider_name="aliyun-test", provider_type="aliyun",
        model_real_name="wonder-pro", provider_instance=_FailingProvider(),
    )
    with pytest.raises(ProviderError, match="upstream boom"):
        await service.get_video_generation(resolved, "job-1")


@pytest.mark.asyncio
async def test_gateway_service_get_video_job_credit():
    from app.middleware.gateway_service import GatewayService
    from app.request_context import ResolvedModelData

    class _FakeCreditProvider:
        async def get_job_credit(self, job_id):
            return {"RequestId": "req-1", "JobId": job_id, "JobCreditCost": 2.0, "CreditStatus": "Generated"}

    service = GatewayService()
    resolved = ResolvedModelData(
        provider_id=1, provider_name="aliyun-test", provider_type="aliyun",
        model_real_name="wonder-pro", provider_instance=_FakeCreditProvider(),
    )
    result = await service.get_video_job_credit(resolved, "job-1")
    assert result["JobCreditCost"] == 2.0


@pytest.mark.asyncio
async def test_gateway_service_get_video_job_credit_unsupported_provider():
    from app.middleware.gateway_service import GatewayService, GatewayServiceError
    from app.request_context import ResolvedModelData

    class _NoCreditProvider:
        pass

    service = GatewayService()
    resolved = ResolvedModelData(
        provider_id=1, provider_name="openai", provider_type="openai",
        model_real_name="gpt-4o", provider_instance=_NoCreditProvider(),
    )
    with pytest.raises(GatewayServiceError, match="does not support job credit query"):
        await service.get_video_job_credit(resolved, "job-1")


@pytest.mark.asyncio
async def test_provider_submit_missing_params_raises_value_error():
    provider = AliyunProvider(ProviderConfig(
        name="aliyun-test",
        api_key="AK123:SK456",
    ))
    with pytest.raises(ValueError, match="job_type"):
        await provider.submit_video_generation({})


@pytest.mark.asyncio
async def test_execute_video_generation_derives_size(monkeypatch):
    """size 字段 (如 1280x720) 应推导出 resolution=720P / aspect_ratio=16:9。"""
    client = _FakeClient([
        _FakeResponse(200, _submit_ok_payload()),
        _FakeResponse(200, _job_payload(
            "Finished",
            output_medias='{"Medias": [{"MediaId": "m1", "OutputUrl": "https://v/out.mp4"}]}',
        )),
    ])

    async def fake_shared_client():
        return client

    monkeypatch.setattr("app.http_client.get_shared_client", fake_shared_client)

    request = _chat_request(metadata={"size": "1280x720"})
    await execute_video_generation(
        access_key_id="ak", access_key_secret="sk",
        model="wonder-pro",
        messages=request.messages,
        metadata=request.metadata,
    )
    body = dict(pair.split("=", 1) for pair in client.requests[0]["content"].split("&"))
    from urllib.parse import unquote
    body = {k: unquote(v) for k, v in body.items()}
    assert body["Resolution"] == "720P"
    assert body["AspectRatio"] == "16:9"
