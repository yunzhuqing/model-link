"""
Unit tests for Vidu and MiniMax-H3 background-response resync.

Verifies that ``resolve_and_check_task_status_async`` correctly handles:

1. **Vidu image generation** (provider_type="vidu") — image_generation_call
   output items extracted from ``check_vidu_task_status``.

2. **MiniMax-H3 video generation** (provider_type="tencentvod") —
   video_generation_call output items extracted from
   ``check_tencentvod_task_status`` + ``_extract_tencentvod_output``,
   including error details (ErrCode/ErrCodeExt) on failure.

3. **Vidu video models** (viduq3* via tencentvod) — same tencentvod path.

运行: cd backend && uv run pytest tests/test_vidu_minimax_h3_resync.py -v
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.usagerecord import task_status_checker as tsc
from app.usagerecord.task_status_checker import (
    TaskCheckResult,
    TaskStatus,
    resolve_and_check_task_status_async,
)


def _run_async(coro):
    """Run a coroutine with a fresh event loop (Python 3.12 compatible)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── fakes ────────────────────────────────────────────────────────────────────

class _Patcher:
    """Tiny attribute patcher that restores originals on exit."""

    def __init__(self):
        self._saved: List[tuple] = []

    def set(self, target: Any, name: str, value: Any) -> None:
        self._saved.append((target, name, getattr(target, name, None), hasattr(target, name)))
        setattr(target, name, value)

    def restore(self) -> None:
        for target, name, old, had in reversed(self._saved):
            if had:
                setattr(target, name, old)
            else:
                try:
                    delattr(target, name)
                except AttributeError:
                    pass
        self._saved.clear()


def _patch_lookup(
    provider_type: str,
    patcher: _Patcher,
    api_key: str = "vda_test_key",
    base_url: str = "",
    extra_config: Optional[Dict[str, Any]] = None,
) -> None:
    async def _fake_lookup(provider_id):
        return {
            "id": provider_id,
            "type": provider_type,
            "api_key": api_key,
            "base_url": base_url,
            "extra_config": extra_config or {},
        }
    patcher.set(tsc, "_lookup_provider_credentials_async", _fake_lookup)


# ── Vidu (provider_type="vidu") image generation ─────────────────────────────

def _patch_vidu_check(resp: Optional[Dict[str, Any]], patcher: _Patcher) -> None:
    async def _fake_check(api_key, base_url, task_id):
        return resp
    from app.providers.vidu import image_generation as vidu_img
    patcher.set(vidu_img, "check_vidu_task_status", _fake_check)


def test_vidu_image_completed_extracts_image_urls():
    """Vidu image task success -> COMPLETED with image_generation_call items."""
    p = _Patcher()
    try:
        _patch_lookup("vidu", p, base_url="https://api.vidu.cn")
        _patch_vidu_check({
            "state": "success",
            "image_urls": [
                "https://cdn.example.com/img1.png",
                "https://cdn.example.com/img2.png",
            ],
            "error": None,
        }, p)

        record = {"task_id": "vidu-task-1", "provider_id": 1, "model": "viduq2"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.COMPLETED
    assert result.output_items is not None
    assert len(result.output_items) == 2
    for i, item in enumerate(result.output_items):
        assert item["type"] == "image_generation_call"
        assert item["status"] == "completed"
        assert item["result"] == f"https://cdn.example.com/img{i+1}.png"


def test_vidu_image_running_returns_running():
    """Vidu task still processing -> RUNNING, no output items."""
    p = _Patcher()
    try:
        _patch_lookup("vidu", p, base_url="https://api.vidu.cn")
        _patch_vidu_check({"state": "processing", "image_urls": [], "error": None}, p)

        record = {"task_id": "vidu-task-2", "provider_id": 1, "model": "gpt-image-2"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.RUNNING
    assert result.output_items is None


def test_vidu_image_failed_carries_error():
    """Vidu task failure -> FAILED with error dict."""
    p = _Patcher()
    try:
        _patch_lookup("vidu", p, base_url="https://api.vidu.cn")
        _patch_vidu_check({
            "state": "failed",
            "image_urls": [],
            "error": {"code": "E1001", "message": "task failed"},
        }, p)

        record = {"task_id": "vidu-task-3", "provider_id": 1, "model": "viduq1"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.FAILED
    assert result.error == {"code": "E1001", "message": "task failed"}
    assert result.output_items is None


def test_vidu_image_http_error_returns_unknown():
    """Vidu check returns None (HTTP error) -> UNKNOWN."""
    p = _Patcher()
    try:
        _patch_lookup("vidu", p, base_url="https://api.vidu.cn")
        _patch_vidu_check(None, p)

        record = {"task_id": "vidu-task-4", "provider_id": 1, "model": "viduq2"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.UNKNOWN


# ── MiniMax-H3 (provider_type="tencentvod") video generation ─────────────────

def _patch_tencentvod_check(resp: Dict[str, Any], patcher: _Patcher) -> None:
    async def _fake_check(secret_id, secret_key, task_id, sub_app_id=None):
        return resp
    from app.providers.tencent.vod import image_generation as vod_img
    patcher.set(vod_img, "check_tencentvod_task_status", _fake_check)


def test_minimax_h3_completed_extracts_video_url():
    """MiniMax-H3 video task success -> COMPLETED with video_generation_call."""
    p = _Patcher()
    try:
        _patch_lookup("tencentvod", p, api_key="sid:skey")
        _patch_tencentvod_check({
            "Status": "FINISH",
            "AigcVideoTask": {
                "Status": "FINISH",
                "ErrCode": 0,
                "Output": {
                    "FileUrl": "https://cdn.example.com/video.mp4",
                    "FileType": "mp4",
                },
            },
        }, p)

        record = {"task_id": "vod-task-1", "provider_id": 1, "model": "MiniMax-H3"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.COMPLETED
    assert result.output_items is not None
    assert len(result.output_items) == 1
    assert result.output_items[0]["type"] == "video_generation_call"
    assert result.output_items[0]["status"] == "completed"
    assert result.output_items[0]["result"] == "https://cdn.example.com/video.mp4"


def test_minimax_h3_running_returns_running():
    """MiniMax-H3 task still processing -> RUNNING."""
    p = _Patcher()
    try:
        _patch_lookup("tencentvod", p, api_key="sid:skey")
        _patch_tencentvod_check({
            "Status": "PROCESSING",
            "AigcVideoTask": {"Status": "PROCESSING"},
        }, p)

        record = {"task_id": "vod-task-2", "provider_id": 1, "model": "minimax-h3"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.RUNNING
    assert result.output_items is None


def test_minimax_h3_failed_carries_error():
    """MiniMax-H3 task failure -> FAILED with error details."""
    p = _Patcher()
    try:
        _patch_lookup("tencentvod", p, api_key="sid:skey")
        _patch_tencentvod_check({
            "Status": "FINISH",
            "AigcVideoTask": {
                "Status": "FINISH",
                "ErrCode": 5001,
                "ErrCodeExt": "ContentPolicyViolation",
                "Message": "Content policy violation detected",
            },
        }, p)

        record = {"task_id": "vod-task-3", "provider_id": 1, "model": "MiniMax-H3"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.FAILED
    assert result.output_items is None
    assert result.error is not None
    assert result.error["code"] == "ContentPolicyViolation"
    assert "ErrCode=5001" in result.error["message"]
    assert "ErrCodeExt=ContentPolicyViolation" in result.error["message"]
    assert "Content policy violation detected" in result.error["message"]


def test_minimax_h3_fail_status_returns_failed():
    """MiniMax-H3 task with FAIL status -> FAILED."""
    p = _Patcher()
    try:
        _patch_lookup("tencentvod", p, api_key="sid:skey")
        _patch_tencentvod_check({
            "Status": "FAIL",
            "AigcVideoTask": {"Status": "FAIL"},
        }, p)

        record = {"task_id": "vod-task-4", "provider_id": 1, "model": "minimax-h3"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.FAILED
    assert result.output_items is None


# ── Vidu video models (viduq3* via tencentvod) ────────────────────────────────

def test_viduq3_completed_extracts_video_url():
    """ViduQ3 video task (via TencentVOD) success -> COMPLETED with video_generation_call."""
    p = _Patcher()
    try:
        _patch_lookup("tencentvod", p, api_key="sid:skey")
        _patch_tencentvod_check({
            "Status": "FINISH",
            "AigcVideoTask": {
                "Status": "FINISH",
                "ErrCode": 0,
                "Output": {
                    "FileUrl": "https://cdn.example.com/viduq3_video.mp4",
                    "FileType": "mp4",
                },
            },
        }, p)

        record = {"task_id": "vod-task-5", "provider_id": 1, "model": "viduq3"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.COMPLETED
    assert result.output_items is not None
    assert result.output_items[0]["type"] == "video_generation_call"
    assert result.output_items[0]["result"] == "https://cdn.example.com/viduq3_video.mp4"


def test_viduq3_fileinfos_fallback():
    """ViduQ3 video output via FileInfos array (fallback pattern)."""
    p = _Patcher()
    try:
        _patch_lookup("tencentvod", p, api_key="sid:skey")
        _patch_tencentvod_check({
            "Status": "FINISH",
            "AigcVideoTask": {
                "Status": "FINISH",
                "ErrCode": 0,
                "Output": {
                    "FileInfos": [
                        {"FileUrl": "https://cdn.example.com/viduq3_fi.mp4", "FileType": "mp4"},
                    ],
                },
            },
        }, p)

        record = {"task_id": "vod-task-6", "provider_id": 1, "model": "viduq3-pro"}
        result = _run_async(resolve_and_check_task_status_async(record))
    finally:
        p.restore()

    assert result.status == TaskStatus.COMPLETED
    assert result.output_items is not None
    assert result.output_items[0]["result"] == "https://cdn.example.com/viduq3_fi.mp4"
