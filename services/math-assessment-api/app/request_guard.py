"""Small, dependency-free request guard for the public read-only API.

The catalog is intentionally public for teacher reference.  This guard is a
polite abuse deterrent, not an identity system: Vercel functions do not share
memory, so durable edge-level limits should be added if traffic grows.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._entries: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            entries = self._entries[key]
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= limit:
                return False
            entries.append(now)
            return True


limiter = SlidingWindowLimiter()


def client_key(headers: dict[str, str], path: str) -> str:
    """Use the first Vercel-forwarded address, without storing it permanently."""
    forwarded = headers.get("x-forwarded-for") or headers.get("x-real-ip") or "unknown"
    address = forwarded.split(",", 1)[0].strip() or "unknown"
    return f"{address}:{path}"
