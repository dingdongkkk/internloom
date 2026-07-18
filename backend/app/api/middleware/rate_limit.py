"""Rate limiting middleware (Bonus A).

Sliding-window limiter, built by hand on an in-memory store (no external lib,
per the bonus rules): at most settings.RATE_LIMIT_MAX requests per IP per
settings.RATE_LIMIT_WINDOW_SEC. On breach: HTTP 429 in the standard envelope
with a Retry-After header saying when the oldest request exits the window.

Implementation notes:
  - ip -> deque[monotonic timestamps]; each request prunes stamps older than the
    window, then either rejects (len >= MAX) or appends.
  - A threading.Lock guards the dict — FastAPI sync endpoints run in a thread
    pool, so concurrent mutation is real.
  - Idle IPs are pruned opportunistically so memory stays bounded.
  - Client IP from request.client.host (X-Forwarded-For is not trustworthy; only trust
    it behind a known proxy, which local demo is not).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.envelope import err


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = None, window_sec: int = None):
        super().__init__(app)
        self.max_requests = max_requests or settings.RATE_LIMIT_MAX
        self.window_sec = window_sec or settings.RATE_LIMIT_WINDOW_SEC
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def _sweep(self, now: float) -> None:
        """Drop IPs with no requests inside the window (bounded memory)."""
        if now - self._last_sweep < self.window_sec:
            return
        cutoff = now - self.window_sec
        for ip in [ip for ip, dq in self._hits.items() if not dq or dq[-1] < cutoff]:
            del self._hits[ip]
        self._last_sweep = now

    async def dispatch(self, request, call_next):
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_sec

        with self._lock:
            self._sweep(now)
            dq = self._hits.setdefault(ip, deque())
            while dq and dq[0] < cutoff:      # slide the window
                dq.popleft()
            if len(dq) >= self.max_requests:
                retry_after = max(1, int(dq[0] + self.window_sec - now) + 1)
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content=err(
                        "RATE_LIMITED",
                        f"Too many requests: limit is {self.max_requests} per "
                        f"{self.window_sec // 60} minutes",
                        {"retry_after_seconds": retry_after},
                    ),
                )
            dq.append(now)

        return await call_next(request)
