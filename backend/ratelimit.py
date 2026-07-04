"""Minimal fixed-window, per-client rate limiter. Off unless RATE_LIMIT > 0.

In-memory and single-process by design — it's a courtesy guard for a directly
exposed instance, not a distributed limiter. Real multi-instance throttling
belongs at a reverse proxy (see the README threat model).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict


_MAX_KEYS = 10_000  # bound memory: sweep expired keys once the table grows past this


class RateLimiter:
    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str, now: float | None = None) -> bool:
        """True if `key` is under the limit for the current window; records the hit."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        with self._lock:
            if len(self._hits) > _MAX_KEYS:
                self._sweep(cutoff)  # drop clients with no live hits — bound memory
            recent = [t for t in self._hits[key] if t > cutoff]
            if len(recent) >= self.limit:
                self._hits[key] = recent  # keep pruned list; don't count this hit
                return False
            recent.append(now)
            self._hits[key] = recent
            return True

    def _sweep(self, cutoff: float) -> None:
        for k in list(self._hits):
            live = [t for t in self._hits[k] if t > cutoff]
            if live:
                self._hits[k] = live
            else:
                del self._hits[k]
