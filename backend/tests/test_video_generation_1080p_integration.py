"""
Integration tests for 1080p / 6s video generation across three models:

  - doubao-seedance-2.0   (Volcengine Seedance 2.0)
  - kling-v3-omni         (TencentVOD Kling 3.0-Omni)
  - MiniMax-H3            (TencentVOD Hailuo H3, multi-modal references)

Each test follows the background polling flow a real client uses:

  1. POST /v1/responses with {"background": true,
        "tools": [{"type": "video_generation",
                   "resolution": "1080p", "seconds": "6",
                   "aspect_ratio": "16:9"}]}
  2. Receive an in_progress response with an id
  3. Loop-poll GET /v1/responses/{id} until status is "completed"
     (or "failed")
  4. Assert the final output contains a video_generation_call item with a
     downloadable video URL

The MiniMax-H3 test mirrors the ARK r2v (reference-to-video) example: a long
first-person prompt that references one image for POV (图片1), one image as the
final frame (图片2), one reference video (视频1), and one background audio
(音频1) via @-prefixed Hailuo file-id variables.

These tests require a running server at ``MODEL_LINK_BASE_URL`` (default
``http://localhost:8000``) and a valid API key in ``MODEL_LINK_API_KEY``.
They are skipped automatically when the server is unreachable or the key is
missing, so they don't break ordinary unit-test runs.

Run (live server required):
  cd backend && \\
  MODEL_LINK_API_KEY=sk-xxx \\
    uv run pytest tests/test_video_generation_1080p_integration.py -v -s

Override the per-model identifiers or the duration if your account uses
different model ids:
  MODEL_LINK_SEEDANCE_MODEL=doubao-seedance-2.0 \\
  MODEL_LINK_KLING_MODEL=kling-v3-omni \\
  MODEL_LINK_MINIMAX_H3_MODEL=MiniMax-H3 \\
  MODEL_LINK_VIDEO_SECONDS=6 \\
  MODEL_LINK_API_KEY=sk-xxx \\
    uv run pytest tests/test_video_generation_1080p_integration.py -v -s
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

import httpx
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Configuration via env vars
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("MODEL_LINK_BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("MODEL_LINK_API_KEY", "")

# Per-model identifiers (override if your account maps to different ids).
SEEDANCE_MODEL = os.environ.get("MODEL_LINK_SEEDANCE_MODEL", "doubao-seedance-2.0")
KLING_MODEL = os.environ.get("MODEL_LINK_KLING_MODEL", "kling-v3-omni")
MINIMAX_H3_MODEL = os.environ.get("MODEL_LINK_MINIMAX_H3_MODEL", "MiniMax-H3")

# Shared generation parameters — 1080p, 6s, 16:9.
RESOLUTION = os.environ.get("MODEL_LINK_VIDEO_RESOLUTION", "1080p")
DURATION_S = os.environ.get("MODEL_LINK_VIDEO_SECONDS", "6")
ASPECT_RATIO = os.environ.get("MODEL_LINK_VIDEO_ASPECT_RATIO", "16:9")

POLL_INTERVAL_S = 5.0
POLL_MAX_WAIT_S = 900  # 15 minutes — 1080p multi-modal can be slow

_SKIP_REASON = (
    "Set MODEL_LINK_API_KEY (and optionally MODEL_LINK_BASE_URL) to run the "
    "1080p video generation live integration tests."
)


def _auth_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }


async def _server_reachable(client: httpx.AsyncClient) -> bool:
    if not API_KEY:
        return False
    try:
        r = await client.head("/v1/responses", headers=_auth_headers(), timeout=5.0)
        return r.status_code in (200, 400, 401)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_text_video_payload(
    *,
    model: str,
    prompt: str,
    resolution: str = RESOLUTION,
    seconds: str = DURATION_S,
    aspect_ratio: str = ASPECT_RATIO,
    background: bool = True,
) -> Dict[str, Any]:
    """Build a text-to-video /v1/responses payload with the shared 1080p/6s tool."""
    return {
        "model": model,
        "background": background,
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
        "tools": [
            {
                "type": "video_generation",
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "seconds": seconds,
            }
        ],
    }


def _build_minimax_h3_multimodal_payload(
    *,
    model: str = MINIMAX_H3_MODEL,
    resolution: str = RESOLUTION,
    seconds: str = DURATION_S,
    aspect_ratio: str = ASPECT_RATIO,
    background: bool = True,
) -> Dict[str, Any]:
    """Build the MiniMax-H3 multi-modal (reference-to-video) payload.

    Mirrors the ARK r2v example: a first-person fruit-tea ad that references
    one POV image (图片1), one final-frame image (图片2), one reference video
    (视频1) and one background audio (音频1).

    Each media block carries an explicit ``file_id`` so the Responses adapter
    builds the file_id → media map deterministically; the prompt addresses them
    with Hailuo-native ``@图片1`` / ``@音频1`` / ``@图片2`` variables.
    """
    prompt = (
        "全程使用@图片1的第一视角构图，全程参考@视频1的运镜节奏，全程使用@音频1作为背景音乐。"
        "第一人称视角果茶宣传广告，seedance牌「苹苹安安」苹果果茶限定款；"
        "首帧为@图片1，你的手摘下一颗带晨露的阿克苏红苹果，轻脆的苹果碰撞声；"
        "2-4 秒：快速切镜，你的手将苹果块投入雪克杯，加入冰块与茶底，用力摇晃，"
        "冰块碰撞声与摇晃声卡点轻快鼓点，背景音：「鲜切现摇」；"
        "4-6 秒：第一人称成品特写，分层果茶倒入透明杯，你的手轻挤奶盖在顶部铺展，"
        "在杯身贴上粉红包标，镜头拉近看奶盖与果茶的分层纹理；"
        "6-8 秒：第一人称手持举杯，你将@图片2中的果茶举到镜头前"
        "（模拟递到观众面前的视角），杯身标签清晰可见，背景音「来一口鲜爽」，"
        "尾帧定格为@图片2。背景声音统一为女生音色。"
    )
    return {
        "model": model,
        "background": background,
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic1.jpg",
                        "file_id": "图片1",
                        "role": "reference_image",
                    },
                    {
                        "type": "input_image",
                        "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic2.jpg",
                        "file_id": "图片2",
                        "role": "reference_image",
                    },
                    {
                        "type": "input_video",
                        "video_url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_tea_video1.mp4",
                        "file_id": "视频1",
                        "role": "reference_video",
                    },
                    {
                        "type": "input_audio",
                        "audio_url": "https://ark-project.tos-cn-beijing.volces.com/doc_audio/r2v_tea_audio1.mp3",
                        "file_id": "音频1",
                        "role": "reference_audio",
                    },
                ],
            }
        ],
        "tools": [
            {
                "type": "video_generation",
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "seconds": seconds,
            }
        ],
    }


def _extract_video_items(output: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [it for it in output if it.get("type") == "video_generation_call"]


async def _poll_until_terminal(
    client: httpx.AsyncClient,
    response_id: str,
    *,
    poll_interval: float = POLL_INTERVAL_S,
    max_wait: float = POLL_MAX_WAIT_S,
    tag: str = "video",
) -> Dict[str, Any]:
    """Loop GET /v1/responses/{id} until status is terminal (completed/failed)."""
    deadline = time.monotonic() + max_wait
    last_status: Optional[str] = None
    poll_count = 0
    start = time.monotonic()

    while time.monotonic() < deadline:
        poll_count += 1
        r = await client.get(
            f"/v1/responses/{response_id}",
            headers=_auth_headers(),
        )
        assert r.status_code == 200, f"[{tag}] poll failed: {r.status_code} {r.text}"
        body = r.json()
        status = body.get("status", "")

        if status != last_status:
            elapsed = round(time.monotonic() - start, 1)
            print(f"\n[{tag}-poll] poll #{poll_count} t={elapsed}s status={status}")
            last_status = status

        if status in ("completed", "failed"):
            elapsed = round(time.monotonic() - start, 1)
            print(
                f"\n[{tag}-poll] terminal status={status} after {elapsed}s "
                f"({poll_count} polls)"
            )
            return body

        await asyncio.sleep(poll_interval)

    pytest.fail(
        f"[{tag}] Timed out after {max_wait}s waiting for response {response_id} "
        f"(last status: {last_status})"
    )


async def _submit_and_assert_in_progress(
    client: httpx.AsyncClient,
    payload: Dict[str, Any],
    *,
    tag: str,
) -> str:
    """POST /v1/responses, assert 200 + in_progress, return the response id."""
    r = await client.post("/v1/responses", json=payload, headers=_auth_headers())
    assert r.status_code == 200, f"[{tag}] Submit failed: {r.status_code} {r.text}"
    initial = r.json()

    assert initial.get("object") == "response", f"[{tag}] unexpected object: {initial}"
    assert initial.get("status") == "in_progress", (
        f"[{tag}] expected in_progress, got {initial.get('status')}: {initial}"
    )
    assert initial.get("background") is True, f"[{tag}] background not true: {initial}"
    response_id = initial.get("id", "")
    assert response_id, f"[{tag}] no response id in {initial}"
    print(f"\n[{tag}] Submitted; response_id={response_id}")
    return response_id


def _assert_completed_video(final: Dict[str, Any], *, tag: str) -> None:
    """Assert the terminal response carries a completed video_generation_call."""
    assert final.get("status") == "completed", (
        f"[{tag}] Expected completed, got {final.get('status')}: "
        f"{final.get('error') or final}"
    )
    output = final.get("output", [])
    assert isinstance(output, list) and output, f"[{tag}] no output items: {final}"
    videos = _extract_video_items(output)
    assert videos, f"[{tag}] no video_generation_call in output: {output}"
    for v in videos:
        assert v.get("status") == "completed", f"[{tag}] item not completed: {v}"
        result_url = v.get("result", "")
        assert result_url, f"[{tag}] empty video result: {v}"
        assert result_url.startswith(("http://", "https://")), (
            f"[{tag}] unexpected result URL: {result_url}"
        )
        print(f"[{tag}] video ready: {result_url[:140]}")

    usage = final.get("usage") or {}
    assert usage.get("total_tokens", 0) > 0 or usage.get("output_tokens", 0) > 0, (
        f"[{tag}] suspicious usage: {usage}"
    )
    print(f"[{tag}] usage: {usage}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    """Yield an httpx.AsyncClient pointed at BASE_URL; skips if server unreachable."""
    async with httpx.AsyncClient(
        base_url=BASE_URL, timeout=httpx.Timeout(30.0, read=None)
    ) as c:
        if not await _server_reachable(c):
            pytest.skip(f"Server at {BASE_URL} not reachable or MODEL_LINK_API_KEY not set.")
        yield c


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not API_KEY, reason=_SKIP_REASON)
@pytest.mark.asyncio
class TestVideoGeneration1080p:
    """End-to-end 1080p / 6s video generation for Seedance 2.0, Kling v3-Omni, MiniMax-H3."""

    async def test_seedance_2_0_1080p_6s(self, client):
        """doubao-seedance-2.0 text-to-video at 1080p / 6s, polled to completion."""
        tag = "seedance-2.0"
        payload = _build_text_video_payload(
            model=SEEDANCE_MODEL,
            prompt="一只橘猫在阳光草地上追蝴蝶，镜头跟随，光线柔和",
        )
        response_id = await _submit_and_assert_in_progress(client, payload, tag=tag)
        final = await _poll_until_terminal(client, response_id, tag=tag)
        _assert_completed_video(final, tag=tag)

    async def test_kling_v3_omni_1080p_6s(self, client):
        """kling-v3-omni text-to-video at 1080p / 6s, polled to completion."""
        tag = "kling-v3-omni"
        payload = _build_text_video_payload(
            model=KLING_MODEL,
            prompt="海边夕阳下的城市天际线，镜头缓缓推进，海面波光粼粼",
        )
        response_id = await _submit_and_assert_in_progress(client, payload, tag=tag)
        final = await _poll_until_terminal(client, response_id, tag=tag)
        _assert_completed_video(final, tag=tag)

    async def test_minimax_h3_1080p_6s_multimodal(self, client):
        """MiniMax-H3 reference-to-video at 1080p / 6s with image/video/audio refs."""
        tag = "minimax-h3"
        payload = _build_minimax_h3_multimodal_payload(model=MINIMAX_H3_MODEL)
        response_id = await _submit_and_assert_in_progress(client, payload, tag=tag)
        final = await _poll_until_terminal(client, response_id, tag=tag)
        _assert_completed_video(final, tag=tag)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    async def _main():
        if not API_KEY:
            print("ERROR: set MODEL_LINK_API_KEY first.", file=sys.stderr)
            sys.exit(2)
        async with httpx.AsyncClient(
            base_url=BASE_URL, timeout=httpx.Timeout(30.0, read=None)
        ) as c:
            if not await _server_reachable(c):
                print(f"ERROR: server at {BASE_URL} not reachable.", file=sys.stderr)
                sys.exit(3)
            tester = TestVideoGeneration1080p()
            print("=== test_seedance_2_0_1080p_6s ===")
            await tester.test_seedance_2_0_1080p_6s(c)
            print("\n=== test_kling_v3_omni_1080p_6s ===")
            await tester.test_kling_v3_omni_1080p_6s(c)
            print("\n=== test_minimax_h3_1080p_6s_multimodal ===")
            await tester.test_minimax_h3_1080p_6s_multimodal(c)
            print("\nAll 1080p video generation integration tests passed.")

    asyncio.run(_main())
