"""
Integration tests for Doubao Seedance video generation via /v1/responses.

Tests cover the background polling flow a real client uses:

  1. POST /v1/responses with {"background": true, "tools": [{"type": "video_generation", ...}]}
  2. Receive an in_progress response with an id
  3. Loop-poll GET /v1/responses/{id} until status is "completed" (or "failed")
  4. Assert the final output contains a video_generation_call with a video URL

These tests require a running server at ``MODEL_LINK_BASE_URL`` (default
``http://localhost:8000``) and a valid API key in ``MODEL_LINK_API_KEY``.
They are skipped automatically when the server is unreachable or the key is
missing, so they don't break ordinary unit-test runs.

Run (live server required):
  cd backend && \
  MODEL_LINK_API_KEY=sk-xxx uv run pytest tests/test_seedance_video_generation.py -v -s

Run against a non-default host:
  MODEL_LINK_BASE_URL=http://host:8000 MODEL_LINK_API_KEY=sk-xxx \
    uv run pytest tests/test_seedance_video_generation.py -v -s
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
DEFAULT_MODEL = "doubao-seedance-2.0-fast"
# Model used for 1080p (non-fast tier supports 1080p; fast only supports 480p/720p)
MODEL_1080P = os.environ.get("MODEL_LINK_SEEDANCE_MODEL_1080P", "doubao-seedance-2.0")

POLL_INTERVAL_S = 5.0
POLL_MAX_WAIT_S = 600  # 10 minutes

_SKIP_REASON = (
    "Set MODEL_LINK_API_KEY (and optionally MODEL_LINK_BASE_URL) to run the "
    "Seedance live integration tests."
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

def _build_seedance_payload(
    prompt: str = "海边夕阳",
    *,
    model: str = DEFAULT_MODEL,
    resolution: str = "720p",
    ratio: Optional[str] = None,
    duration: Optional[int] = None,
    background: bool = True,
    generate_audio: Optional[bool] = None,
) -> Dict[str, Any]:
    tool: Dict[str, Any] = {"type": "video_generation", "resolution": resolution}
    if ratio:
        tool["ratio"] = ratio
    if duration is not None:
        tool["duration"] = duration
    if generate_audio is not None:
        tool["generate_audio"] = generate_audio
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
        "tools": [tool],
    }


def _extract_video_items(output: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [it for it in output if it.get("type") == "video_generation_call"]


async def _poll_until_terminal(
    client: httpx.AsyncClient,
    response_id: str,
    *,
    poll_interval: float = POLL_INTERVAL_S,
    max_wait: float = POLL_MAX_WAIT_S,
) -> Dict[str, Any]:
    """Loop GET /v1/responses/{id} until status is terminal."""
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
        assert r.status_code == 200, f"poll failed: {r.status_code} {r.text}"
        body = r.json()
        status = body.get("status", "")

        if status != last_status:
            elapsed = round(time.monotonic() - start, 1)
            print(f"\n[seedance-poll] poll #{poll_count} t={elapsed}s status={status}")
            last_status = status

        if status in ("completed", "failed"):
            elapsed = round(time.monotonic() - start, 1)
            print(f"\n[seedance-poll] terminal status={status} after {elapsed}s ({poll_count} polls)")
            return body

        await asyncio.sleep(poll_interval)

    pytest.fail(
        f"Timed out after {max_wait}s waiting for response {response_id} "
        f"(last status: {last_status})"
    )


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
class TestSeedanceVideoGeneration:
    """End-to-end tests for the Seedance video generation flow.

    Each test submits a real generation request and polls until the final
    result is available.
    """

    model: str = os.environ.get("MODEL_LINK_SEEDANCE_MODEL", DEFAULT_MODEL)

    async def test_background_video_generation_polls_to_completion(self, client):
        """Submit a background video request and poll until completed.

        Mirrors the curl example in the ticket:
          POST /v1/responses (background:true) -> in_progress
          GET  /v1/responses/{id} (loop)       -> completed with video URL
        """
        payload = _build_seedance_payload(
            prompt="海边夕阳",
            model=self.model,
            resolution="720p",
            background=True,
        )

        # Submit
        r = await client.post("/v1/responses", json=payload, headers=_auth_headers())
        assert r.status_code == 200, f"Submit failed: {r.status_code} {r.text}"
        initial = r.json()

        assert initial.get("object") == "response"
        assert initial.get("status") == "in_progress", (
            f"expected in_progress, got {initial.get('status')}: {initial}"
        )
        assert initial.get("background") is True
        response_id = initial.get("id", "")
        assert response_id, f"no response id in {initial}"
        print(f"\n[seedance-bg] Submitted; response_id={response_id}")

        # Poll to terminal
        final = await _poll_until_terminal(client, response_id)

        # Assert on completed result
        assert final.get("status") == "completed", (
            f"Expected completed, got {final.get('status')}: "
            f"{final.get('error') or final}"
        )
        output = final.get("output", [])
        assert isinstance(output, list) and output, f"no output items: {final}"
        videos = _extract_video_items(output)
        assert videos, f"no video_generation_call in output: {output}"
        for v in videos:
            assert v.get("status") == "completed"
            result_url = v.get("result", "")
            assert result_url, f"empty video result: {v}"
            assert result_url.startswith(("http://", "https://")), (
                f"unexpected result URL: {result_url}"
            )
            print(f"[seedance-bg] video ready: {result_url[:140]}")

        usage = final.get("usage") or {}
        assert usage.get("total_tokens", 0) > 0 or usage.get("output_tokens", 0) > 0, (
            f"suspicious usage: {usage}"
        )
        print(f"[seedance-bg] usage: {usage}")

    async def test_background_video_generation_480p_fast(self, client):
        """doubao-seedance-2.0-fast supports 480p and 720p (not 1080p). Verify 480p works."""
        payload = _build_seedance_payload(
            prompt="雨天窗外的城市",
            model=self.model,
            resolution="480p",
            background=True,
        )
        r = await client.post("/v1/responses", json=payload, headers=_auth_headers())
        assert r.status_code == 200, f"Submit failed: {r.status_code} {r.text}"
        initial = r.json()
        response_id = initial["id"]
        print(f"\n[seedance-480p-fast] Submitted; response_id={response_id}")

        final = await _poll_until_terminal(client, response_id)
        assert final.get("status") == "completed", (
            f"unexpected status: {final.get('status')} — {final.get('error')}"
        )
        videos = _extract_video_items(final.get("output", []))
        assert videos and all(v.get("result", "").startswith("http") for v in videos), (
            f"missing video URLs: {final}"
        )
        for v in videos:
            print(f"[seedance-480p-fast] video ready: {v['result'][:140]}")

    async def test_background_video_generation_1080p(self, client):
        """1080p video generation requires the non-fast Seedance tier (doubao-seedance-2.0).

        Override with MODEL_LINK_SEEDANCE_MODEL_1080P if your account uses a
        different 1080p-capable model.
        """
        payload = _build_seedance_payload(
            prompt="一只橘猫在草地上追蝴蝶",
            model=MODEL_1080P,
            resolution="1080p",
            ratio="16:9",
            background=True,
        )
        r = await client.post("/v1/responses", json=payload, headers=_auth_headers())
        assert r.status_code == 200, f"Submit failed: {r.status_code} {r.text}"
        initial = r.json()
        response_id = initial["id"]
        print(f"\n[seedance-1080p] Submitted model={MODEL_1080P}; response_id={response_id}")

        final = await _poll_until_terminal(client, response_id)
        assert final.get("status") == "completed", (
            f"unexpected status: {final.get('status')} — {final.get('error')}"
        )
        videos = _extract_video_items(final.get("output", []))
        assert videos and all(v.get("result", "").startswith("http") for v in videos), (
            f"missing video URLs: {final}"
        )
        for v in videos:
            print(f"[seedance-1080p] video ready: {v['result'][:140]}")

    async def test_invalid_resolution_returns_error(self, client):
        """A bogus resolution should fail fast (non-200) on submit."""
        payload = _build_seedance_payload(
            prompt="海边夕阳",
            model=self.model,
            resolution="99999p",
            background=True,
        )
        r = await client.post("/v1/responses", json=payload, headers=_auth_headers())
        assert r.status_code in (400, 422), (
            f"Expected 4xx for invalid resolution, got {r.status_code}: {r.text[:500]}"
        )
        print(f"\n[seedance-invalid] Correctly rejected with {r.status_code}")


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
        ) as client:
            if not await _server_reachable(client):
                print(f"ERROR: server at {BASE_URL} not reachable.", file=sys.stderr)
                sys.exit(3)
            tester = TestSeedanceVideoGeneration()
            print("=== test_background_video_generation_polls_to_completion ===")
            await tester.test_background_video_generation_polls_to_completion(client)
            print("\n=== test_background_video_generation_480p_fast ===")
            await tester.test_background_video_generation_480p_fast(client)
            print("\n=== test_background_video_generation_1080p ===")
            await tester.test_background_video_generation_1080p(client)
            print("\n=== test_invalid_resolution_returns_error ===")
            await tester.test_invalid_resolution_returns_error(client)
            print("\nAll Seedance integration tests passed.")

    asyncio.run(_main())
