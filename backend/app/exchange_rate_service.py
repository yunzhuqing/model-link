"""
Exchange Rate Service
Fetches the USD→CNY exchange rate from frankfurter.app and caches it in
memory.  The rate is refreshed once per day via an asyncio background task
that is started at application startup.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger("exchange_rate")

# ── Configuration ─────────────────────────────────────────────────────────────
USD = "USD"
CNY = "CNY"

_DEFAULT_RATE = 7.0          # Fallback when the API is unavailable
_REFRESH_INTERVAL = 86400    # Refresh every 24 hours (seconds)

# ── In-memory state ──────────────────────────────────────────────────────────
_lock = asyncio.Lock()
_current_rate: float = _DEFAULT_RATE
_refresh_task: asyncio.Task | None = None

# ── Public API ───────────────────────────────────────────────────────────────


def get_exchange_rate() -> float:
    """Return the current USD → CNY exchange rate (thread-safe read).

    A plain float read is atomic in CPython, so no lock is needed for reads.
    """
    return _current_rate


def start_daily_refresh() -> None:
    """Schedule the async daily refresh task on the running event loop."""
    global _refresh_task
    if _refresh_task is not None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Not inside an event loop yet — will be started in create_app via
        # a startup task.
        return
    _refresh_task = loop.create_task(_refresh_loop())
    logger.info("[exchange_rate] Daily refresh task scheduled.")


async def stop_daily_refresh() -> None:
    """Cancel the daily refresh task. Called on shutdown."""
    global _refresh_task
    if _refresh_task is not None:
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass
        _refresh_task = None


# ── Internal helpers ─────────────────────────────────────────────────────────


async def _fetch_once() -> None:
    """Fetch the latest rate from frankfurter.app and update the global."""
    global _current_rate
    url = f"https://api.frankfurter.app/latest?from={USD}&to={CNY}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                if "rates" in data and CNY in data["rates"]:
                    rate = float(data["rates"][CNY])
                    async with _lock:
                        _current_rate = rate
                    logger.info(f"[exchange_rate] Updated {USD}→{CNY} rate: {rate}")
                else:
                    logger.warning(f"[exchange_rate] {CNY} rate not found in response: {data}")
            else:
                logger.error(f"[exchange_rate] Failed to fetch exchange rate. Status: {response.status_code}")
    except Exception as exc:
        logger.error(f"[exchange_rate] Error fetching exchange rate: {exc}")


def _seconds_until_next_midnight() -> float:
    """Return the number of seconds from now until the next 00:00:00 local time."""
    import datetime
    now = datetime.datetime.now()
    tomorrow_midnight = datetime.datetime(now.year, now.month, now.day) + datetime.timedelta(days=1)
    return (tomorrow_midnight - now).total_seconds()


async def _refresh_loop() -> None:
    """Fetch daily, aligned to local midnight. Only the leader node fetches."""
    from app.election_service import is_leader

    if is_leader():
        await _fetch_once()
    else:
        logger.info("[exchange_rate] Not leader — skipping initial fetch.")

    while True:
        wait = _seconds_until_next_midnight()
        logger.info(f"[exchange_rate] Next refresh in {wait:.0f}s (at local midnight).")
        await asyncio.sleep(wait)
        if is_leader():
            await _fetch_once()
        else:
            logger.debug("[exchange_rate] Not leader — skipping scheduled fetch.")