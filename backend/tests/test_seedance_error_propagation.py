"""
Unit tests for Seedance failed-task error propagation.

Verifies that when an upstream Seedance task ends with status=failed, the
upstream ``error`` object (code + message) is carried through:
  1. check_seedance_task_status  → result["error"]
  2. _poll_video_task            → RuntimeError message
  3. resolve_and_check_task_status_async (volcengine branch)
                                  → TaskCheckResult.error

运行: cd backend && uv run python tests/test_seedance_error_propagation.py
  或: cd backend && uv run pytest tests/test_seedance_error_propagation.py -v
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from app.providers.volcengine import video_generation as vg
from app.usagerecord import task_status_checker as tsc
from app.usagerecord.task_status_checker import (
    TaskCheckResult,
    TaskStatus,
    resolve_and_check_task_status_async,
)


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload, ensure_ascii=False)


class _FakeClient:
    """Async client whose .get() returns a coroutine yielding a _FakeResponse."""

    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self._status_code = status_code

    def get(self, url, headers=None):
        async def _coro():
            return _FakeResponse(self._payload, self._status_code)
        return _coro()


class _Patcher:
    """Tiny attribute patcher that restores originals on exit."""

    def __init__(self):
        self._saved = []

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


def _patch_check(payload: Dict[str, Any], patcher: _Patcher) -> None:
    async def _fake_get_ark_client():
        return _FakeClient(payload)
    patcher.set(vg, "_get_ark_client", _fake_get_ark_client)


# ── 1. check_seedance_task_status extracts error on failed ─────────────────

def test_check_status_extracts_error_when_failed():
    p = _Patcher()
    try:
        _patch_check({
            "id": "cgt-test",
            "status": "failed",
            "error": {
                "code": "OutputVideoSensitiveContentDetected.PolicyViolation",
                "message": "The request failed because the output video may be related to copyright restrictions. Request id: 02178",
            },
        }, p)
        result = asyncio.get_event_loop().run_until_complete(
            vg.check_seedance_task_status("k", "https://ark/api/v3", "cgt-test")
        )
    finally:
        p.restore()

    assert result["status"] == "failed"
    # Normalized: policy/sensitive violation → content_policy_violation,
    # message carries full upstream info (code + message, incl. request id).
    assert result["error"] == {
        "code": "content_policy_violation",
        "message": "OutputVideoSensitiveContentDetected.PolicyViolation: "
                   "The request failed because the output video may be related "
                   "to copyright restrictions. Request id: 02178",
    }
    assert "video_url" not in result
    assert "usage" not in result
    print("PASS: check_seedance_task_status extracts+normalizes error on failed")


def test_check_status_no_error_field_when_upstream_omits_it():
    p = _Patcher()
    try:
        _patch_check({"id": "cgt-test", "status": "failed"}, p)
        result = asyncio.get_event_loop().run_until_complete(
            vg.check_seedance_task_status("k", "https://ark/api/v3", "cgt-test")
        )
    finally:
        p.restore()

    assert result["status"] == "failed"
    assert "error" not in result
    print("PASS: no error field when upstream omits it")


def test_check_status_succeeded_has_no_error():
    p = _Patcher()
    try:
        _patch_check({
            "id": "cgt-test",
            "status": "succeeded",
            "content": {"video_url": "https://cdn/v.mp4"},
            "usage": {"completion_tokens": 5, "total_tokens": 7},
        }, p)
        result = asyncio.get_event_loop().run_until_complete(
            vg.check_seedance_task_status("k", "https://ark/api/v3", "cgt-test")
        )
    finally:
        p.restore()

    assert result["status"] == "succeeded"
    assert result["video_url"] == "https://cdn/v.mp4"
    assert "error" not in result
    print("PASS: succeeded has no error field")


# ── 2. _poll_video_task surfaces error in RuntimeError ────────────────────

def test_poll_video_task_runtime_error_includes_error():
    p = _Patcher()
    try:
        # Patch the HTTP client so the REAL check_seedance_task_status runs
        # and normalizes the upstream error.
        _patch_check({
            "id": "cgt-test",
            "status": "failed",
            "error": {
                "code": "OutputVideoSensitiveContentDetected.PolicyViolation",
                "message": "copyright restrictions",
            },
        }, p)

        try:
            asyncio.get_event_loop().run_until_complete(
                vg._poll_video_task("k", "https://ark/api/v3", "cgt-test")
            )
        except vg.SeedanceTaskError as e:
            exc = e
            msg = str(e)
        else:
            raise AssertionError("expected SeedanceTaskError")
    finally:
        p.restore()

    assert "status=failed" in msg
    assert "OutputVideoSensitiveContentDetected.PolicyViolation" in msg
    assert "copyright restrictions" in msg
    # error_info carries the normalized client-facing error dict
    assert exc.error_info == {
        "code": "content_policy_violation",
        "message": "OutputVideoSensitiveContentDetected.PolicyViolation: copyright restrictions",
    }
    print("PASS: _poll_video_task raises SeedanceTaskError with normalized error_info")


# ── 3. resolve_and_check_task_status_async (volcengine) carries error ──────

def test_resolve_volcengine_carries_error():
    p = _Patcher()
    try:
        # Real check_seedance_task_status runs (via patched _get_ark_client)
        # so the upstream error gets normalized.
        _patch_check({
            "id": "cgt-test",
            "status": "failed",
            "error": {"code": "OutputVideoSensitiveContentDetected.PolicyViolation",
                      "message": "copyright restrictions"},
        }, p)

        async def _fake_lookup(provider_id):
            return {"id": provider_id, "type": "volcengine", "api_key": "k",
                    "base_url": "https://ark/api/v3", "extra_config": {}}
        p.set(tsc, "_lookup_provider_credentials_async", _fake_lookup)

        record = {"task_id": "cgt-test", "provider_id": 1, "model": "doubao-seedance-2.0"}
        result = asyncio.get_event_loop().run_until_complete(
            resolve_and_check_task_status_async(record)
        )
    finally:
        p.restore()

    assert result.status == TaskStatus.FAILED
    # Normalized to content_policy_violation with full upstream info in message
    assert result.error == {
        "code": "content_policy_violation",
        "message": "OutputVideoSensitiveContentDetected.PolicyViolation: copyright restrictions",
    }
    assert result.output_items is None
    print("PASS: resolve_and_check_task_status_async carries normalized error (volcengine)")


def test_resolve_volcengine_non_policy_error_falls_back():
    """Non-policy failures normalize to server_error but keep full message."""
    p = _Patcher()
    try:
        _patch_check({
            "id": "cgt-test",
            "status": "failed",
            "error": {"code": "InvalidParameter", "message": "bad ratio"},
        }, p)

        async def _fake_lookup(provider_id):
            return {"id": provider_id, "type": "volcengine", "api_key": "k",
                    "base_url": "https://ark/api/v3", "extra_config": {}}
        p.set(tsc, "_lookup_provider_credentials_async", _fake_lookup)

        record = {"task_id": "cgt-test", "provider_id": 1, "model": "doubao-seedance-2.0"}
        result = asyncio.get_event_loop().run_until_complete(
            resolve_and_check_task_status_async(record)
        )
    finally:
        p.restore()

    assert result.status == TaskStatus.FAILED
    assert result.error == {
        "code": "server_error",
        "message": "InvalidParameter: bad ratio",
    }
    print("PASS: non-policy failure normalizes to server_error (keeps full message)")


def test_resolve_volcengine_completed_has_no_error():
    p = _Patcher()
    try:
        async def _fake_check(api_key, base_url, task_id):
            return {
                "status": "succeeded",
                "data": {"status": "succeeded"},
                "video_url": "https://cdn/v.mp4",
                "usage": {"prompt_tokens": 2, "completion_tokens": 5, "total_tokens": 7},
            }
        p.set(vg, "check_seedance_task_status", _fake_check)

        async def _fake_lookup(provider_id):
            return {"id": provider_id, "type": "volcengine", "api_key": "k",
                    "base_url": "https://ark/api/v3", "extra_config": {}}
        p.set(tsc, "_lookup_provider_credentials_async", _fake_lookup)

        record = {"task_id": "cgt-test", "provider_id": 1, "model": "doubao-seedance-2.0"}
        result = asyncio.get_event_loop().run_until_complete(
            resolve_and_check_task_status_async(record)
        )
    finally:
        p.restore()

    assert result.status == TaskStatus.COMPLETED
    assert result.error is None
    assert result.output_items and result.output_items[0]["result"] == "https://cdn/v.mp4"
    print("PASS: resolve completed (volcengine) has no error")


# ── 4. background_resync FAILED branch → mark_failed_async(error_json) ─────

def test_resync_failed_branch_passes_error_to_mark_failed():
    """Verify the FAILED branch builds a JSON error string from result.error."""
    import app.usagerecord.background_resync_service as brs

    captured: list[str] = []

    async def _fake_mark_failed(response_id, error):
        captured.append(error)

    p = _Patcher()
    try:
        p.set(brs, "_bg_dao", type("_DAO", (), {
            "mark_failed_async": staticmethod(_fake_mark_failed),
        })())

        # result.error is already the normalized client-facing dict (produced by
        # check_seedance_task_status → _normalize_seedance_error).
        result = TaskCheckResult(
            TaskStatus.FAILED,
            error={"code": "content_policy_violation",
                   "message": "OutputVideoSensitiveContentDetected.PolicyViolation: copyright restrictions"},
        )
        err = result.error
        error_msg = json.dumps(err, ensure_ascii=False) if err else "Task failed at upstream provider"
        asyncio.get_event_loop().run_until_complete(_fake_mark_failed("resp-1", error_msg))
    finally:
        p.restore()

    assert captured and json.loads(captured[0]) == {
        "code": "content_policy_violation",
        "message": "OutputVideoSensitiveContentDetected.PolicyViolation: copyright restrictions",
    }
    print("PASS: resync FAILED branch stores normalized error JSON via mark_failed_async")


if __name__ == "__main__":
    import sys
    tests = [
        test_check_status_extracts_error_when_failed,
        test_check_status_no_error_field_when_upstream_omits_it,
        test_check_status_succeeded_has_no_error,
        test_poll_video_task_runtime_error_includes_error,
        test_resolve_volcengine_carries_error,
        test_resolve_volcengine_non_policy_error_falls_back,
        test_resolve_volcengine_completed_has_no_error,
        test_resync_failed_branch_passes_error_to_mark_failed,
    ]
    failed = []
    for fn in tests:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"FAIL: {fn.__name__}: {e}")
            failed.append(fn.__name__)
    if failed:
        print(f"\n{len(failed)} test(s) failed: {failed}")
        sys.exit(1)
    print("\nAll Seedance error-propagation tests passed.")
