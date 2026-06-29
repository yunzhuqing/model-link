"""
Rate Limiter for Model RPM/TPM throttling.

Mechanism:
  RPM (Requests Per Minute): each request consumes 1 slot. When the window
    counter reaches 0 the request is rejected with HTTP 429.

  TPM (Tokens Per Minute): tokens are pre-estimated before the request and
    reconciled after the provider returns the actual usage. Pre-estimation
    uses the text length of the last user message (×1.5), plus system + tool
    messages for the first user turn.

Cache keys (sliding minute window, auto-expiring):
  ratelimit:rpm:{model_id}:{group_id}:{minute}  → remaining RPM (int)
  ratelimit:tpm:{model_id}:{group_id}:{minute}  → remaining TPM (float)

Usage:
    from app.rate_limiter import get_async_rate_limiter

    limiter = get_async_rate_limiter()

    # Before request
    result = limiter.check_and_reserve(
        model_id=1, group_id=2,
        rpm_limit=500, tpm_limit=15000000,
        estimated_input_tokens=1200,
    )
    if not result.allowed:
        abort(429, result.detail)

    # After request
    limiter.reconcile(
        model_id=1, group_id=2,
        tpm_limit=15000000,
        pre_estimated_tokens=1200,
        actual_input_tokens=1050,
    )
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("rate_limiter")

# ── Helpers ──────────────────────────────────────────────────────────────────

def _minute_key() -> str:
    return time.strftime("%Y%m%d%H%M", time.gmtime())

def _seconds_until_next_minute() -> int:
    now = time.time()
    return 60 - int(now % 60)

# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class RateLimitResult:
    allowed: bool
    detail: Optional[str] = None
    remaining_rpm: Optional[int] = None
    remaining_tpm: Optional[float] = None
    workspace_remaining_rpm: Optional[int] = None
    workspace_remaining_tpm: Optional[float] = None
    # Which rate-limit level rejected the request (None when allowed).
    # Values: "model", "workspace", "apikey".
    limit_level: Optional[str] = None

# ── Token Estimation Utility ──────────────────────────────────────────────────


def estimate_input_tokens(
    messages: List[Dict[str, Any]],
    system_prompt: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    multiplier: float = 1.5,
) -> int:
    """Estimate input tokens based on text content length.

    Find the last user message and count its string length x multiplier.
    If this is the first user turn, also include system_prompt and tools.
    Returns the estimated token count (rounded to int).
    """
    estimated = 0

    user_messages = [m for m in reversed(messages) if m.get("role") == "user"]
    if user_messages:
        last_user = user_messages[0]
        content = last_user.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    estimated += len(block.get("text", ""))
        elif isinstance(content, str):
            estimated += len(content)

    if len(user_messages) <= 1:
        if system_prompt:
            estimated += len(system_prompt)
        if tools:
            estimated += len(json.dumps(tools, ensure_ascii=False))

    return max(1, int(estimated * multiplier))


class AsyncRateLimiter:
    """Per-model, per-group RPM / TPM rate limiter using the async cache backend."""

    WINDOW_TTL = 90
    WS_WINDOW_TTL = 660

    RPM_PREFIX = "ratelimit:rpm:"
    TPM_PREFIX = "ratelimit:tpm:"
    APIKEY_PREFIX = "ratelimit:apikey:"
    WS_RPM_PREFIX = "ratelimit:ws:rpm:"
    WS_TPM_PREFIX = "ratelimit:ws:tpm:"
    WS_APIKEY_PREFIX = "ratelimit:ws:apikey:"
    WSP_RPM_PREFIX = "ratelimit:wsp:rpm:"
    WSP_TPM_PREFIX = "ratelimit:wsp:tpm:"
    WSP_APIKEY_PREFIX = "ratelimit:wsp:apikey:"
    AK_RPM_PREFIX = "ratelimit:ak:rpm:"
    AK_TPM_PREFIX = "ratelimit:ak:tpm:"

    def __init__(self, backend):
        from app.cache import AsyncCacheBackend as _ACB
        self._backend: _ACB = backend

    def _rpm_key(self, model_id: int, group_id: int) -> str:
        return f"{self.RPM_PREFIX}{model_id}:{group_id}:{_minute_key()}"

    def _tpm_key(self, model_id: int, group_id: int) -> str:
        return f"{self.TPM_PREFIX}{model_id}:{group_id}:{_minute_key()}"

    def _apikey_key(self, model_id: int, group_id: int) -> str:
        return f"{self.APIKEY_PREFIX}{model_id}:{group_id}:{_minute_key()}"

    def _ws_rpm_key(self, workspace_id: int, model_name: str, provider_type: str = "", provider_id: Optional[int] = None) -> str:
        suffix = f":{provider_type}" if provider_type else ""
        if provider_id is not None:
            suffix += f":{provider_id}"
        return f"{self.WS_RPM_PREFIX}{workspace_id}:{model_name}{suffix}:{_minute_key()}"

    def _ws_tpm_key(self, workspace_id: int, model_name: str, provider_type: str = "", provider_id: Optional[int] = None) -> str:
        suffix = f":{provider_type}" if provider_type else ""
        if provider_id is not None:
            suffix += f":{provider_id}"
        return f"{self.WS_TPM_PREFIX}{workspace_id}:{model_name}{suffix}:{_minute_key()}"

    def _ws_apikey_key(self, workspace_id: int, model_name: str, provider_type: str = "", provider_id: Optional[int] = None) -> str:
        suffix = f":{provider_type}" if provider_type else ""
        if provider_id is not None:
            suffix += f":{provider_id}"
        return f"{self.WS_APIKEY_PREFIX}{workspace_id}:{model_name}{suffix}:{_minute_key()}"

    def _ak_rpm_key(self, api_key_id: int) -> str:
        return f"{self.AK_RPM_PREFIX}{api_key_id}:{_minute_key()}"

    def _ak_tpm_key(self, api_key_id: int) -> str:
        return f"{self.AK_TPM_PREFIX}{api_key_id}:{_minute_key()}"

    async def _get_apikey_map(self, model_id: int, group_id: int) -> Dict[str, Dict[str, int]]:
        key = self._apikey_key(model_id, group_id)
        raw = await self._backend.get(key)
        if raw:
            try:
                return json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    async def _save_apikey_map(self, model_id: int, group_id: int, data: Dict[str, Dict[str, int]]) -> None:
        key = self._apikey_key(model_id, group_id)
        await self._backend.set(key, json.dumps(data) if isinstance(data, dict) else data, ttl=self.WINDOW_TTL)

    async def _update_apikey_usage(self, model_id: int, group_id: int, apikey_preview: str,
                                   rpm_delta: int = 0, tpm_delta: int = 0) -> None:
        if not apikey_preview:
            return
        data = await self._get_apikey_map(model_id, group_id)
        entry = data.get(apikey_preview, {"rpm_used": 0, "tpm_used": 0})
        entry["rpm_used"] = max(0, entry["rpm_used"] + rpm_delta)
        entry["tpm_used"] = max(0, entry["tpm_used"] + tpm_delta)
        data[apikey_preview] = entry
        await self._save_apikey_map(model_id, group_id, data)

    async def _get_ws_apikey_map(self, workspace_id: int, model_name: str,
                                 provider_type: str = "", provider_id: Optional[int] = None) -> Dict[str, Dict[str, int]]:
        key = self._ws_apikey_key(workspace_id, model_name, provider_type, provider_id)
        raw = await self._backend.get(key)
        if raw:
            try:
                return json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    async def _save_ws_apikey_map(self, workspace_id: int, model_name: str,
                                  data: Dict[str, Dict[str, int]],
                                  provider_type: str = "", provider_id: Optional[int] = None) -> None:
        key = self._ws_apikey_key(workspace_id, model_name, provider_type, provider_id)
        await self._backend.set(key, json.dumps(data) if isinstance(data, dict) else data, ttl=self.WS_WINDOW_TTL)

    async def _update_ws_apikey_usage(self, workspace_id: int, model_name: str, apikey_preview: str,
                                      rpm_delta: int = 0, tpm_delta: int = 0,
                                      provider_type: str = "", provider_id: Optional[int] = None) -> None:
        if not apikey_preview or workspace_id is None:
            return
        data = await self._get_ws_apikey_map(workspace_id, model_name, provider_type, provider_id)
        entry = data.get(apikey_preview, {"rpm_used": 0, "tpm_used": 0})
        entry["rpm_used"] = max(0, entry["rpm_used"] + rpm_delta)
        entry["tpm_used"] = max(0, entry["tpm_used"] + tpm_delta)
        data[apikey_preview] = entry
        await self._save_ws_apikey_map(workspace_id, model_name, data, provider_type, provider_id)

    def _get_ttl_for_key(self, key: str) -> int:
        return self.WS_WINDOW_TTL if key.startswith("ratelimit:ws:") else self.WINDOW_TTL

    async def _init_rpm_key(self, key: str, limit: int) -> int:
        existing = await self._backend.get_float(key)
        if existing is None:
            await self._backend.set_float(key, float(limit), ttl=self._get_ttl_for_key(key))
            return limit
        return int(existing)

    async def _init_tpm_key(self, key: str, limit: int) -> float:
        existing = await self._backend.get_float(key)
        if existing is None:
            await self._backend.set_float(key, float(limit), ttl=self._get_ttl_for_key(key))
            return float(limit)
        return float(existing)

    async def _decr_rpm(self, key: str, limit: int) -> Optional[int]:
        await self._init_rpm_key(key, limit)
        new_val = await self._backend.incr_float_scalar(key, -1.0)
        return int(new_val) if new_val is not None else None

    async def _incr_rpm(self, key: str, limit: int) -> Optional[int]:
        new_val = await self._backend.incr_float_scalar(key, 1.0)
        return int(new_val) if new_val is not None else None

    async def _decr_tpm(self, key: str, limit: int, tokens: int) -> Optional[float]:
        await self._init_tpm_key(key, limit)
        return await self._backend.incr_float_scalar(key, float(-tokens))

    async def _incr_tpm(self, key: str, limit: int, tokens: int) -> Optional[float]:
        await self._init_tpm_key(key, limit)
        return await self._backend.incr_float_scalar(key, float(tokens))

    # ── Public API ────────────────────────────────────────────────────────

    async def check_and_reserve(
        self, model_id: int, group_id: int, rpm_limit: Optional[int],
        tpm_limit: Optional[int], estimated_input_tokens: int = 0,
        apikey_preview: str = "", workspace_id: Optional[int] = None,
        model_name: str = "", workspace_rpm: Optional[int] = None,
        workspace_tpm: Optional[int] = None, ws_provider_type: str = "",
        ws_provider_id: Optional[int] = None, apikey_rpm: Optional[int] = None,
        apikey_tpm: Optional[int] = None, api_key_id: Optional[int] = None,
    ) -> RateLimitResult:
        has_rpm = rpm_limit is not None and rpm_limit > 0
        has_tpm = tpm_limit is not None and tpm_limit > 0
        has_ws_rpm = workspace_id is not None and workspace_rpm is not None and workspace_rpm > 0
        has_ws_tpm = workspace_id is not None and workspace_tpm is not None and workspace_tpm > 0
        has_ak_rpm = api_key_id is not None and apikey_rpm is not None and apikey_rpm > 0
        has_ak_tpm = api_key_id is not None and apikey_tpm is not None and apikey_tpm > 0

        if not has_rpm and not has_tpm and not has_ws_rpm and not has_ws_tpm and not has_ak_rpm and not has_ak_tpm:
            return RateLimitResult(allowed=True)

        retry_msg = f"Retry after {_seconds_until_next_minute()}s."
        remaining_rpm = None
        remaining_tpm = None

        rpm_key = self._rpm_key(model_id, group_id) if has_rpm else None
        if has_rpm:
            remaining_rpm = await self._decr_rpm(rpm_key, rpm_limit)
            if remaining_rpm is not None and remaining_rpm < 0:
                return RateLimitResult(allowed=False, detail=f"RPM limit exceeded (limit: {rpm_limit}/min). {retry_msg}", remaining_rpm=0, limit_level="model")
            await self._update_apikey_usage(model_id, group_id, apikey_preview, rpm_delta=1)

        tpm_key = self._tpm_key(model_id, group_id) if has_tpm else None
        if has_tpm:
            remaining_tpm = await self._decr_tpm(tpm_key, tpm_limit, estimated_input_tokens)
            if remaining_tpm is not None and remaining_tpm < 0:
                if has_rpm:
                    await self._incr_rpm(rpm_key, rpm_limit)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, rpm_delta=-1)
                return RateLimitResult(allowed=False, detail=f"TPM limit exceeded (limit: {tpm_limit}/min). {retry_msg}", remaining_tpm=0.0, limit_level="model")
            await self._update_apikey_usage(model_id, group_id, apikey_preview, tpm_delta=estimated_input_tokens)

        ws_rpm_key = self._ws_rpm_key(workspace_id, model_name, ws_provider_type, ws_provider_id) if has_ws_rpm else None
        if has_ws_rpm:
            ws_remaining_rpm = await self._decr_rpm(ws_rpm_key, workspace_rpm)
            if ws_remaining_rpm is not None and ws_remaining_rpm < 0:
                if has_rpm:
                    await self._incr_rpm(rpm_key, rpm_limit)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, rpm_delta=-1)
                if has_tpm:
                    await self._incr_tpm(tpm_key, tpm_limit, estimated_input_tokens)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, tpm_delta=-estimated_input_tokens)
                return RateLimitResult(allowed=False, detail=f"Workspace RPM limit exceeded (limit: {workspace_rpm}/min). {retry_msg}", workspace_remaining_rpm=0, limit_level="workspace")
            await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, rpm_delta=1,
                                               provider_type=ws_provider_type, provider_id=ws_provider_id)

        ws_tpm_key = self._ws_tpm_key(workspace_id, model_name, ws_provider_type, ws_provider_id) if has_ws_tpm else None
        if has_ws_tpm:
            ws_remaining_tpm = await self._decr_tpm(ws_tpm_key, workspace_tpm, estimated_input_tokens)
            if ws_remaining_tpm is not None and ws_remaining_tpm < 0:
                if has_ws_rpm:
                    await self._incr_rpm(ws_rpm_key, workspace_rpm)
                    await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, rpm_delta=-1,
                                                       provider_type=ws_provider_type, provider_id=ws_provider_id)
                if has_rpm:
                    await self._incr_rpm(rpm_key, rpm_limit)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, rpm_delta=-1)
                if has_tpm:
                    await self._incr_tpm(tpm_key, tpm_limit, estimated_input_tokens)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, tpm_delta=-estimated_input_tokens)
                return RateLimitResult(allowed=False, detail=f"Workspace TPM limit exceeded (limit: {workspace_tpm}/min). {retry_msg}", workspace_remaining_tpm=0.0, limit_level="workspace")
            await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, tpm_delta=estimated_input_tokens,
                                               provider_type=ws_provider_type, provider_id=ws_provider_id)

        ak_rpm_key = self._ak_rpm_key(api_key_id) if has_ak_rpm else None
        if has_ak_rpm:
            ak_remaining_rpm = await self._decr_rpm(ak_rpm_key, apikey_rpm)
            if ak_remaining_rpm is not None and ak_remaining_rpm < 0:
                if has_ws_tpm:
                    await self._incr_tpm(ws_tpm_key, workspace_tpm, estimated_input_tokens)
                    await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, tpm_delta=-estimated_input_tokens,
                                                       provider_type=ws_provider_type, provider_id=ws_provider_id)
                if has_ws_rpm:
                    await self._incr_rpm(ws_rpm_key, workspace_rpm)
                    await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, rpm_delta=-1,
                                                       provider_type=ws_provider_type, provider_id=ws_provider_id)
                if has_rpm:
                    await self._incr_rpm(rpm_key, rpm_limit)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, rpm_delta=-1)
                if has_tpm:
                    await self._incr_tpm(tpm_key, tpm_limit, estimated_input_tokens)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, tpm_delta=-estimated_input_tokens)
                return RateLimitResult(allowed=False, detail=f"API key RPM limit exceeded (limit: {apikey_rpm}/min). {retry_msg}", remaining_rpm=0, limit_level="apikey")

        ak_tpm_key = self._ak_tpm_key(api_key_id) if has_ak_tpm else None
        if has_ak_tpm:
            ak_remaining_tpm = await self._decr_tpm(ak_tpm_key, apikey_tpm, estimated_input_tokens)
            if ak_remaining_tpm is not None and ak_remaining_tpm < 0:
                if has_ak_rpm:
                    await self._incr_rpm(ak_rpm_key, apikey_rpm)
                if has_ws_tpm:
                    await self._incr_tpm(ws_tpm_key, workspace_tpm, estimated_input_tokens)
                    await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, tpm_delta=-estimated_input_tokens,
                                                       provider_type=ws_provider_type, provider_id=ws_provider_id)
                if has_ws_rpm:
                    await self._incr_rpm(ws_rpm_key, workspace_rpm)
                    await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, rpm_delta=-1,
                                                       provider_type=ws_provider_type, provider_id=ws_provider_id)
                if has_rpm:
                    await self._incr_rpm(rpm_key, rpm_limit)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, rpm_delta=-1)
                if has_tpm:
                    await self._incr_tpm(tpm_key, tpm_limit, estimated_input_tokens)
                    await self._update_apikey_usage(model_id, group_id, apikey_preview, tpm_delta=-estimated_input_tokens)
                return RateLimitResult(allowed=False, detail=f"API key TPM limit exceeded (limit: {apikey_tpm}/min). {retry_msg}", remaining_tpm=0.0, limit_level="apikey")

        return RateLimitResult(allowed=True, remaining_rpm=remaining_rpm, remaining_tpm=remaining_tpm)

    async def reconcile(
        self, model_id: int, group_id: int, tpm_limit: Optional[int],
        pre_estimated_tokens: int, actual_input_tokens: int,
        apikey_preview: str = "", workspace_id: Optional[int] = None,
        model_name: str = "", workspace_tpm: Optional[int] = None,
        ws_provider_type: str = "", ws_provider_id: Optional[int] = None,
        apikey_tpm: Optional[int] = None, api_key_id: Optional[int] = None,
    ) -> None:
        delta = pre_estimated_tokens - actual_input_tokens
        if delta == 0:
            return
        if tpm_limit is not None and tpm_limit > 0:
            tpm_key = self._tpm_key(model_id, group_id)
            if delta > 0:
                await self._incr_tpm(tpm_key, tpm_limit, delta)
                await self._update_apikey_usage(model_id, group_id, apikey_preview, tpm_delta=-delta)
            else:
                await self._decr_tpm(tpm_key, tpm_limit, abs(delta))
                await self._update_apikey_usage(model_id, group_id, apikey_preview, tpm_delta=abs(delta))
        if workspace_id is not None and workspace_tpm is not None and workspace_tpm > 0 and model_name:
            ws_tpm_key = self._ws_tpm_key(workspace_id, model_name, ws_provider_type, ws_provider_id)
            if delta > 0:
                await self._incr_tpm(ws_tpm_key, workspace_tpm, delta)
                await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, tpm_delta=-delta,
                                                   provider_type=ws_provider_type, provider_id=ws_provider_id)
            else:
                await self._decr_tpm(ws_tpm_key, workspace_tpm, abs(delta))
                await self._update_ws_apikey_usage(workspace_id, model_name, apikey_preview, tpm_delta=abs(delta),
                                                   provider_type=ws_provider_type, provider_id=ws_provider_id)
        if api_key_id is not None and apikey_tpm is not None and apikey_tpm > 0:
            ak_tpm_key = self._ak_tpm_key(api_key_id)
            if delta > 0:
                await self._incr_tpm(ak_tpm_key, apikey_tpm, delta)
            else:
                await self._decr_tpm(ak_tpm_key, apikey_tpm, abs(delta))

    async def get_status(self, model_id: int, group_id: int) -> Dict[str, Any]:
        rpm_key = self._rpm_key(model_id, group_id)
        tpm_key = self._tpm_key(model_id, group_id)
        rpm_remaining = await self._backend.get_float(rpm_key)
        tpm_remaining = await self._backend.get_float(tpm_key)
        apikey_data = await self._get_apikey_map(model_id, group_id)
        apikeys = [{"preview": k, "rpm_used": v.get("rpm_used", 0), "tpm_used": v.get("tpm_used", 0)}
                   for k, v in apikey_data.items()]
        return {"rpm": {"remaining": int(rpm_remaining) if rpm_remaining is not None else None},
                "tpm": {"remaining": float(tpm_remaining) if tpm_remaining is not None else None},
                "apikeys": apikeys}

    async def get_all_status_for_group(self, model_ids: List[int], group_id: int) -> List[Dict[str, Any]]:
        results = []
        for model_id in model_ids:
            status = await self.get_status(model_id, group_id)
            status["model_id"] = model_id
            results.append(status)
        return results

    async def get_ws_status(self, workspace_id: int, model_name: str,
                            ws_rpm_limit: Optional[int] = None, ws_tpm_limit: Optional[int] = None,
                            provider_type: str = "", provider_id: Optional[int] = None) -> Dict[str, Any]:
        ws_rpm_key = self._ws_rpm_key(workspace_id, model_name, provider_type, provider_id)
        ws_tpm_key = self._ws_tpm_key(workspace_id, model_name, provider_type, provider_id)
        rpm_remaining = await self._backend.get_float(ws_rpm_key)
        tpm_remaining = await self._backend.get_float(ws_tpm_key)
        rpm_used = None
        if ws_rpm_limit is not None and rpm_remaining is not None:
            rpm_used = max(0, ws_rpm_limit - int(rpm_remaining))
        tpm_used = None
        if ws_tpm_limit is not None and tpm_remaining is not None:
            tpm_used = max(0, ws_tpm_limit - int(tpm_remaining))
        apikey_data = await self._get_ws_apikey_map(workspace_id, model_name, provider_type, provider_id)
        apikeys = [{"preview": k, "rpm_used": v.get("rpm_used", 0), "tpm_used": v.get("tpm_used", 0)}
                   for k, v in apikey_data.items()]
        return {"model_name": model_name,
                "rpm": {"limit": ws_rpm_limit, "remaining": int(rpm_remaining) if rpm_remaining is not None else ws_rpm_limit, "used": rpm_used or 0},
                "tpm": {"limit": ws_tpm_limit, "remaining": int(tpm_remaining) if tpm_remaining is not None else ws_tpm_limit, "used": tpm_used or 0},
                "apikeys": apikeys}

    async def get_ws_history(self, workspace_id: int, model_name: str,
                             ws_rpm_limit: Optional[int] = None, ws_tpm_limit: Optional[int] = None,
                             minutes: int = 10, provider_type: str = "",
                             provider_id: Optional[int] = None) -> Dict[str, Any]:
        now = time.time()
        rpm_1 = rpm_5 = rpm_10 = 0
        tpm_1 = tpm_5 = tpm_10 = 0
        suffix = f":{provider_type}" if provider_type else ""
        if provider_id is not None:
            suffix += f":{provider_id}"
        for i in range(minutes):
            t_offset = now - i * 60
            mk = time.strftime("%Y%m%d%H%M", time.gmtime(t_offset))
            rpm_key = f"{self.WS_RPM_PREFIX}{workspace_id}:{model_name}{suffix}:{mk}"
            rpm_rem = await self._backend.get_float(rpm_key)
            rpm_used_min = 0
            if ws_rpm_limit is not None and rpm_rem is not None:
                rpm_used_min = max(0, ws_rpm_limit - int(rpm_rem))
            tpm_key = f"{self.WS_TPM_PREFIX}{workspace_id}:{model_name}{suffix}:{mk}"
            tpm_rem = await self._backend.get_float(tpm_key)
            tpm_used_min = 0
            if ws_tpm_limit is not None and tpm_rem is not None:
                tpm_used_min = max(0, ws_tpm_limit - int(tpm_rem))
            if i < 1:
                rpm_1 += rpm_used_min; tpm_1 += tpm_used_min
            if i < 5:
                rpm_5 += rpm_used_min; tpm_5 += tpm_used_min
            rpm_10 += rpm_used_min; tpm_10 += tpm_used_min
        return {"rpm_1m": rpm_1, "rpm_5m": rpm_5, "rpm_10m": rpm_10,
                "tpm_1m": tpm_1, "tpm_5m": tpm_5, "tpm_10m": tpm_10}


# ── Async Singleton ───────────────────────────────────────────────────────────

_async_rate_limiter: Optional[AsyncRateLimiter] = None


def get_async_rate_limiter() -> AsyncRateLimiter:
    """Return the global AsyncRateLimiter singleton."""
    global _async_rate_limiter
    if _async_rate_limiter is None:
        from app.cache import get_async_cache as _get_ac
        _async_rate_limiter = AsyncRateLimiter(_get_ac()._backend)
    return _async_rate_limiter