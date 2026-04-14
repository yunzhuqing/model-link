"""
Exchange Rate Service
Fetches the USD→CNY exchange rate from frankfurter.app and caches it in
memory.  The rate is refreshed once per day via a background daemon thread
that is started at application startup.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

logger = logging.getLogger("exchange_rate")

# ── Configuration ─────────────────────────────────────────────────────────────
USD = "USD"
CNY = "CNY"

_DEFAULT_RATE = 7.0          # Fallback when the API is unavailable
_REFRESH_INTERVAL = 86400    # Refresh every 24 hours (seconds)

# ── In-memory state ──────────────────────────────────────────────────────────
_lock = threading.Lock()
_current_rate: float = _DEFAULT_RATE
_started = False              # Guard so we only start one refresh thread


# ── Public API ────────────────────────────────────────────────────────────────

def get_exchange_rate() -> float:
    """Return the current USD → CNY exchange rate (thread-safe read)."""
    with _lock:
        return _current_rate


def start_daily_refresh() -> None:
    """
    Start a background daemon thread that refreshes the exchange rate every 24 h.

    Safe to call multiple times — only one thread is ever started.
    Performs an immediate fetch on startup so the rate is current from the
    first request.
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True

    thread = threading.Thread(target=_refresh_loop, daemon=True, name="exchange-rate-refresh")
    thread.start()
    logger.info("[exchange_rate] Daily refresh thread started.")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_once() -> None:
    """Fetch the latest rate from frankfurter.app and update the global."""
    global _current_rate
    url = f"https://api.frankfurter.app/latest?from={USD}&to={CNY}"
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(url)
            if response.status_code == 200:
                data = response.json()
                if "rates" in data and CNY in data["rates"]:
                    rate = float(data["rates"][CNY])
                    with _lock:
                        _current_rate = rate
                    logger.info(f"[exchange_rate] Updated {USD}→{CNY} rate: {rate}")
                else:
                    logger.warning(f"[exchange_rate] {CNY} rate not found in response: {data}")
            else:
                logger.error(
                    f"[exchange_rate] Failed to fetch exchange rate. "
                    f"Status: {response.status_code}"
                )
    except Exception as exc:
        logger.error(f"[exchange_rate] Error fetching exchange rate: {exc}")


def _seconds_until_next_midnight() -> float:
    """Return the number of seconds from now until the next 00:00:00 local time."""
    import datetime
    now = datetime.datetime.now()
    # Next midnight = today's date + 1 day, at 00:00:00
    tomorrow_midnight = datetime.datetime(now.year, now.month, now.day) + datetime.timedelta(days=1)
    return (tomorrow_midnight - now).total_seconds()


def _refresh_loop() -> None:
    """
    Fetch the exchange rate immediately on startup, then repeat at every local midnight (00:00).

    Sleep logic:
      1. Fetch once right now (startup).
      2. Calculate how many seconds remain until the next 00:00 local time.
      3. Sleep until midnight, then fetch again.
      4. After that, sleep exactly 24 h between fetches (keeping alignment with midnight).
    """
    # Initial fetch on startup
    _fetch_once()

    # Wait until next midnight, then loop daily
    while True:
        wait = _seconds_until_next_midnight()
        logger.info(f"[exchange_rate] Next refresh in {wait:.0f}s (at local midnight).")
        time.sleep(wait)
        _fetch_once()
