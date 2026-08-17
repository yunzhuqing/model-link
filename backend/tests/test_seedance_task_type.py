"""
Unit tests for the Seedance ``task_type`` tool parameter and its mapping to the
upstream ``omni_reference_task_type`` API body field.

Run:
  cd backend && uv run pytest tests/test_seedance_task_type.py -v
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from app.abstraction.messages import ContentBlock, Message, MessageRole
from app.providers.volcengine import video_generation as vg

MODEL_25 = "doubao-seedance-2-5-pro-260620"


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self.status_code = status_code
        self._payload = payload
        self.headers: Dict[str, str] = {}

    def json(self) -> Dict[str, Any]:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload, ensure_ascii=False)


class _FakeSharedClient:
    """Async context manager that records the POST body and returns a task id."""

    def __init__(self):
        self.posts: list = []  # [(url, content_str, headers), ...]

    async def __aenter__(self):
        outer = self

        class _Client:
            async def post(self, url, content=None, headers=None):
                outer.posts.append((url, content, headers))
                return _FakeResponse({"id": "cgt-fake"})

        return _Client()

    async def __aexit__(self, *exc):
        return False


class _Patcher:
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


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── _create_video_task body construction ─────────────────────────────────────

def test_create_video_task_includes_omni_reference_task_type():
    fake = _FakeSharedClient()
    p = _Patcher()
    try:
        p.set(vg, "shared_client", lambda: fake)
        _run(vg._create_video_task(
            api_key="k",
            base_url="https://ark/api/v3",
            model_id="doubao-seedance-2-0-260128",
            content=[{"type": "text", "text": "a cat"}],
            omni_reference_task_type="reference",
        ))
    finally:
        p.restore()

    body = json.loads(fake.posts[0][1])
    assert body["omni_reference_task_type"] == "reference"
    print("PASS: _create_video_task writes omni_reference_task_type to body")


def test_create_video_task_omits_omni_reference_task_type_when_none():
    fake = _FakeSharedClient()
    p = _Patcher()
    try:
        p.set(vg, "shared_client", lambda: fake)
        _run(vg._create_video_task(
            api_key="k",
            base_url="https://ark/api/v3",
            model_id="doubao-seedance-2-0-260128",
            content=[{"type": "text", "text": "a cat"}],
        ))
    finally:
        p.restore()

    body = json.loads(fake.posts[0][1])
    assert "omni_reference_task_type" not in body
    print("PASS: _create_video_task omits omni_reference_task_type when not set")


# ── execute_seedance_video_generation wiring + validation ───────────────────

def test_execute_seedance_passes_task_type_as_omni_reference():
    captured: Dict[str, Any] = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return "cgt-fake"

    async def fake_poll(*args, **kwargs):
        return ("https://cdn/v.mp4",
                {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                1)

    p = _Patcher()
    try:
        p.set(vg, "_create_video_task", fake_create)
        p.set(vg, "_poll_video_task", fake_poll)
        _run(vg.execute_seedance_video_generation(
            api_key="k",
            base_url="https://ark/api/v3",
            model=MODEL_25,
            messages=[Message(role=MessageRole.USER, content="a cat")],
            metadata={"task_type": "reference"},
        ))
    finally:
        p.restore()

    assert captured["omni_reference_task_type"] == "reference"
    print("PASS: execute_seedance_video_generation maps task_type → omni_reference_task_type (2.5+ model)")


def test_execute_seedance_invalid_task_type_raises():
    p = _Patcher()
    try:
        raised = False
        try:
            _run(vg.execute_seedance_video_generation(
                api_key="k",
                base_url="https://ark/api/v3",
                model="doubao-seedance-2.0",
                messages=[Message(role=MessageRole.USER, content="a cat")],
                metadata={"task_type": "bogus"},
            ))
        except RuntimeError as e:
            raised = True
            assert "task_type" in str(e)
    finally:
        p.restore()

    assert raised, "expected RuntimeError for invalid task_type"
    print("PASS: execute_seedance_video_generation rejects invalid task_type")



# ── version gating ───────────────────────────────────────────────────────────

def test_model_supports_task_type_version_gating():
    assert vg._seedance_version("doubao-seedance-2-5-pro-260620") == (2, 5)
    assert vg._seedance_version("doubao-seedance-2.0") == (2, 0)
    assert vg._seedance_version("doubao-seedance-1-5-pro-251215") == (1, 5)
    assert vg._seedance_version("seedance-pro") is None

    assert vg._model_supports_task_type("doubao-seedance-2-5-pro-260620") is True
    assert vg._model_supports_task_type("doubao-seedance-2-6-lite") is True
    assert vg._model_supports_task_type("doubao-seedance-2.0") is False
    assert vg._model_supports_task_type("doubao-seedance-1-5-pro-251215") is False
    assert vg._model_supports_task_type("seedance-pro") is False
    print("PASS: _model_supports_task_type gates on Seedance 2.5+")


def test_execute_seedance_drops_task_type_for_pre_2_5_model():
    captured: Dict[str, Any] = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return "cgt-fake"

    async def fake_poll(*args, **kwargs):
        return ("https://cdn/v.mp4",
                {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                1)

    p = _Patcher()
    try:
        p.set(vg, "_create_video_task", fake_create)
        p.set(vg, "_poll_video_task", fake_poll)
        _run(vg.execute_seedance_video_generation(
            api_key="k",
            base_url="https://ark/api/v3",
            model="doubao-seedance-2.0",
            messages=[Message(role=MessageRole.USER, content="a cat")],
            metadata={"task_type": "reference"},
        ))
    finally:
        p.restore()

    # Pre-2.5 model: task_type silently dropped → not sent to the API
    assert captured.get("omni_reference_task_type") is None
    print("PASS: execute_seedance_video_generation drops task_type for pre-2.5 models")



# ── edit / extend constraints ─────────────────────────────────────────────────

def _ref_video_map(url="https://cdn/ref.mp4"):
    return {"v1": {"type": "video", "url": url, "role": "reference_video"}}


def test_execute_seedance_edit_requires_reference_video():
    p = _Patcher()
    try:
        raised = False
        try:
            _run(vg.execute_seedance_video_generation(
                api_key="k",
                base_url="https://ark/api/v3",
                model=MODEL_25,
                messages=[Message(role=MessageRole.USER, content="edit this")],
                metadata={"task_type": "edit"},
            ))
        except RuntimeError as e:
            raised = True
            assert "reference_video" in str(e)
    finally:
        p.restore()
    assert raised, "edit without reference_video should raise"
    print("PASS: edit task_type requires a reference_video")


def test_execute_seedance_edit_sets_adaptive_ratio_and_duration():
    captured: Dict[str, Any] = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return "cgt-fake"

    async def fake_poll(*args, **kwargs):
        return ("https://cdn/v.mp4",
                {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                1)

    p = _Patcher()
    try:
        p.set(vg, "_create_video_task", fake_create)
        p.set(vg, "_poll_video_task", fake_poll)
        _run(vg.execute_seedance_video_generation(
            api_key="k",
            base_url="https://ark/api/v3",
            model=MODEL_25,
            messages=[Message(role=MessageRole.USER, content="edit this video")],
            metadata={"task_type": "edit", "file_id_media_map": _ref_video_map()},
        ))
    finally:
        p.restore()

    assert captured["omni_reference_task_type"] == "edit"
    assert captured["ratio"] == "adaptive"
    assert captured["duration"] == -1
    print("PASS: edit forces ratio=adaptive and duration=-1")


def test_execute_seedance_extend_requires_reference_video():
    p = _Patcher()
    try:
        raised = False
        try:
            _run(vg.execute_seedance_video_generation(
                api_key="k",
                base_url="https://ark/api/v3",
                model=MODEL_25,
                messages=[Message(role=MessageRole.USER, content="extend this")],
                metadata={"task_type": "extend"},
            ))
        except RuntimeError as e:
            raised = True
            assert "reference_video" in str(e)
    finally:
        p.restore()
    assert raised, "extend without reference_video should raise"
    print("PASS: extend task_type requires a reference_video")


def test_execute_seedance_extend_sets_adaptive_ratio_only():
    captured: Dict[str, Any] = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return "cgt-fake"

    async def fake_poll(*args, **kwargs):
        return ("https://cdn/v.mp4",
                {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                1)

    p = _Patcher()
    try:
        p.set(vg, "_create_video_task", fake_create)
        p.set(vg, "_poll_video_task", fake_poll)
        _run(vg.execute_seedance_video_generation(
            api_key="k",
            base_url="https://ark/api/v3",
            model=MODEL_25,
            messages=[Message(role=MessageRole.USER, content="extend this video")],
            metadata={"task_type": "extend", "file_id_media_map": _ref_video_map()},
        ))
    finally:
        p.restore()

    assert captured["omni_reference_task_type"] == "extend"
    assert captured["ratio"] == "adaptive"
    # extend does NOT force duration=-1 (unlike edit)
    assert captured.get("duration") is None
    print("PASS: extend forces ratio=adaptive but leaves duration unset")



def test_execute_seedance_edit_with_inline_input_video():
    """Mimics the help-center edit example: input_video with video_url, no file_id."""
    captured: Dict[str, Any] = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return "cgt-fake"

    async def fake_poll(*args, **kwargs):
        return ("https://cdn/v.mp4",
                {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                1)

    p = _Patcher()
    try:
        p.set(vg, "_create_video_task", fake_create)
        p.set(vg, "_poll_video_task", fake_poll)
        _run(vg.execute_seedance_video_generation(
            api_key="k",
            base_url="https://ark/api/v3",
            model=MODEL_25,
            messages=[Message(
                role=MessageRole.USER,
                content=[
                    ContentBlock.from_text("将视频中的面包黄油换成樱桃"),
                    ContentBlock.from_video_url(
                        "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_tea_video1.mp4"),
                ],
            )],
            metadata={"task_type": "edit"},
        ))
    finally:
        p.restore()

    assert captured["omni_reference_task_type"] == "edit"
    assert captured["ratio"] == "adaptive"
    assert captured["duration"] == -1
    assert any(c.get("role") == "reference_video" for c in captured["content"])
    print("PASS: edit works with inline input_video (no file_id)")


if __name__ == "__main__":
    import sys
    tests = [
        test_create_video_task_includes_omni_reference_task_type,
        test_create_video_task_omits_omni_reference_task_type_when_none,
        test_execute_seedance_passes_task_type_as_omni_reference,
        test_execute_seedance_invalid_task_type_raises,
        test_model_supports_task_type_version_gating,
        test_execute_seedance_drops_task_type_for_pre_2_5_model,
        test_execute_seedance_edit_requires_reference_video,
        test_execute_seedance_edit_sets_adaptive_ratio_and_duration,
        test_execute_seedance_extend_requires_reference_video,
        test_execute_seedance_extend_sets_adaptive_ratio_only,
        test_execute_seedance_edit_with_inline_input_video,
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
    print("\nAll Seedance task_type tests passed.")
