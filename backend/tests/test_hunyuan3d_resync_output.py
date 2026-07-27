"""
Unit tests for Hunyuan3D background-resync output item shape.

Verifies that ``resolve_and_check_task_status_async`` (hunyuan branch)
builds output_items whose ``content`` entries carry the file ``type``
(e.g. OBJ/STL/GLB) — matching the real-time response shape in
``threed_generation.py`` — in addition to ``url`` and ``preview_url``.

运行: cd backend && uv run python tests/test_hunyuan3d_resync_output.py
  或: cd backend && uv run pytest tests/test_hunyuan3d_resync_output.py -v
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.providers.tencent.hunyuan import threed_generation as hunyuan3d
from app.usagerecord import task_status_checker as tsc
from app.usagerecord.task_status_checker import (
    TaskStatus,
    resolve_and_check_task_status_async,
)


# ── fakes ────────────────────────────────────────────────────────────────────

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


def _patch_hunyuan_check(resp: Dict[str, Any], patcher: _Patcher) -> None:
    async def _fake_check(secret_id, secret_key, task_id, *, model=None, region="ap-guangzhou"):
        return resp
    # ``resolve_and_check_task_status_async`` does
    # ``from app.providers.tencent.hunyuan.threed_generation import check_any_hunyuan3d_job_status``
    # at call time, so patching the module attribute is picked up.
    patcher.set(hunyuan3d, "check_any_hunyuan3d_job_status", _fake_check)


def _patch_lookup(provider_type: str, patcher: _Patcher) -> None:
    async def _fake_lookup(provider_id):
        return {
            "id": provider_id,
            "type": provider_type,
            "api_key": "sid:skey",  # secret_id:secret_key split
            "base_url": "",
            "extra_config": {},
        }
    patcher.set(tsc, "_lookup_provider_credentials_async", _fake_lookup)


# ── tests ────────────────────────────────────────────────────────────────────

def test_hunyuan_completed_content_has_file_type():
    """Each content entry must include file ``type`` (OBJ/STL/...), url, preview_url."""
    p = _Patcher()
    try:
        _patch_lookup("hunyuan", p)
        _patch_hunyuan_check({
            "Status": "DONE",
            "ResultFile3Ds": [
                {"Type": "OBJ", "Url": "https://cdn/a.obj", "PreviewImageUrl": "https://cdn/a.png"},
                {"Type": "GLB", "Url": "https://cdn/b.glb", "PreviewImageUrl": "https://cdn/b.png"},
            ],
        }, p)

        record = {"task_id": "job-1", "provider_id": 1, "model": "hunyuan-3d-rapid"}
        result = asyncio.get_event_loop().run_until_complete(
            resolve_and_check_task_status_async(record)
        )
    finally:
        p.restore()

    assert result.status == TaskStatus.COMPLETED
    assert result.output_items is not None
    assert len(result.output_items) == 2

    for item in result.output_items:
        assert item["type"] == "3d_generation_call"
        assert item["status"] == "completed"
        assert len(item["content"]) == 1
        entry = item["content"][0]
        # The bug: content only had url + preview_url, missing file type.
        assert set(entry.keys()) == {"type", "url", "preview_url"}, (
            f"content entry keys should be type/url/preview_url, got {set(entry.keys())}"
        )
        assert entry["url"].startswith("https://cdn/")
        assert entry["preview_url"].startswith("https://cdn/")

    assert result.output_items[0]["content"][0]["type"] == "OBJ"
    assert result.output_items[1]["content"][0]["type"] == "GLB"
    print("PASS: hunyuan3d resync content entries carry file type")


def test_hunyuan_completed_defaults_type_to_obj_when_upstream_omits():
    """When upstream ``Type`` is missing, fall back to OBJ (matches real-time path)."""
    p = _Patcher()
    try:
        _patch_lookup("hunyuan", p)
        _patch_hunyuan_check({
            "Status": "DONE",
            "ResultFile3Ds": [
                {"Url": "https://cdn/c.obj", "PreviewImageUrl": "https://cdn/c.png"},
            ],
        }, p)

        record = {"task_id": "job-2", "provider_id": 1, "model": "hunyuan-3d-pro"}
        result = asyncio.get_event_loop().run_until_complete(
            resolve_and_check_task_status_async(record)
        )
    finally:
        p.restore()

    assert result.status == TaskStatus.COMPLETED
    entry = result.output_items[0]["content"][0]
    assert entry["type"] == "OBJ"
    assert entry["url"] == "https://cdn/c.obj"
    assert entry["preview_url"] == "https://cdn/c.png"
    print("PASS: hunyuan3d resync defaults file type to OBJ when upstream omits Type")


def test_hunyuan_running_has_no_output_items():
    p = _Patcher()
    try:
        _patch_lookup("hunyuan", p)
        _patch_hunyuan_check({"Status": "RUNNING"}, p)

        record = {"task_id": "job-3", "provider_id": 1, "model": "hunyuan-3d-rapid"}
        result = asyncio.get_event_loop().run_until_complete(
            resolve_and_check_task_status_async(record)
        )
    finally:
        p.restore()

    assert result.status == TaskStatus.RUNNING
    assert result.output_items is None
    print("PASS: hunyuan3d resync running task has no output_items")


if __name__ == "__main__":
    import sys
    tests = [
        test_hunyuan_completed_content_has_file_type,
        test_hunyuan_completed_defaults_type_to_obj_when_upstream_omits,
        test_hunyuan_running_has_no_output_items,
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
    print("\nAll Hunyuan3D resync output tests passed.")
