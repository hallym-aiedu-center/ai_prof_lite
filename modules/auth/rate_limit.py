from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowRateLimiter:
    """Small in-process limiter for expensive authentication endpoints.

    It is intentionally local to the application process: it protects the event
    loop from bursts of Argon2 work without adding a Redis/runtime dependency.
    Deployments with multiple web processes should additionally rate-limit at the
    reverse proxy or a shared store.
    """

    def __init__(self, *, limit: int, window_seconds: int):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def consume(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else float(now)
        cutoff = current - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= self.limit:
                retry_after = max(1, math.ceil(self.window_seconds - (current - events[0])))
                return False, retry_after

            events.append(current)
            return True, 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


# Keep both a per-source and per-account budget.  These values are deliberately
# conservative enough for normal users while bounding expensive password work.
_LOGIN_IP = SlidingWindowRateLimiter(limit=20, window_seconds=60)
_LOGIN_ACCOUNT = SlidingWindowRateLimiter(limit=10, window_seconds=300)


def _client_key(request) -> str:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host or "unknown")


def check_login_rate_limit(request, email: str) -> tuple[bool, int]:
    ip_key = _client_key(request)
    account_key = str(email or "").strip().lower() or "<empty>"

    ip_allowed, ip_retry = _LOGIN_IP.consume(ip_key)
    account_allowed, account_retry = _LOGIN_ACCOUNT.consume(account_key)
    if ip_allowed and account_allowed:
        return True, 0
    return False, max(ip_retry, account_retry)


def reset_login_account(email: str) -> None:
    account_key = str(email or "").strip().lower() or "<empty>"
    _LOGIN_ACCOUNT.reset(account_key)
