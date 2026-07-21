"""
Simple async QPS rate limiter.

Limits the rate of asynchronous operations to at most *max_per_second*
acquisitions per second. Used to stay safely below upstream QPS limits
(e.g. Volcengine ARK DeleteAsset, which has a default QPS limit of 10).
"""
from __future__ import annotations

import asyncio
import time


class QPSRateLimiter:
    """Simple async rate limiter — allows at most *max_per_second* acquisitions per second."""

    def __init__(self, max_per_second: int):
        self._interval = 1.0 / max_per_second
        self._next = time.monotonic()

    async def acquire(self):
        now = time.monotonic()
        wait = self._next - now
        if wait > 0:
            await asyncio.sleep(wait)
            self._next += self._interval
        else:
            self._next = time.monotonic() + self._interval
