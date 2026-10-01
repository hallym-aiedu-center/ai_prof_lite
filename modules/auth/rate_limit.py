from __future__ import annotations

import hashlib
import heapq
import math
import time
from collections import defaultdict, deque
from threading import Lock

from modules.auth.constraints import EMAIL_MAX_LENGTH


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
        # One expiry marker per accepted event lets us reclaim inactive keys
        # without scanning the whole dictionary on every login attempt.
        self._expiries: list[tuple[float, str]] = []
        self._lock = Lock()

    def _prune_expired(self, current: float) -> None:
        cutoff = current - self.window_seconds
        while self._expiries and self._expiries[0][0] <= current:
            _, key = heapq.heappop(self._expiries)
            events = self._events.get(key)
            if not events:
                continue
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                self._events.pop(key, None)

    def consume(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            self._prune_expired(current)
            events = self._events[key]

            if len(events) >= self.limit:
                retry_after = max(
                    1, math.ceil(self.window_seconds - (current - events[0]))
                )
                return False, retry_after

            events.append(current)
            heapq.heappush(self._expiries, (current + self.window_seconds, key))
            return True, 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def clear(self) -> None:
        """Drop all in-process limiter state.

        Production code normally never needs this; it exists so a fresh test
        case starts with a deterministic limiter state.
        """
        with self._lock:
            self._events.clear()
            self._expiries.clear()


# Keep both a per-source and per-account budget.  These values are deliberately
# conservative enough for normal users while bounding expensive password work.
_LOGIN_IP = SlidingWindowRateLimiter(limit=20, window_seconds=60)
_LOGIN_ACCOUNT = SlidingWindowRateLimiter(limit=10, window_seconds=300)
# Registration performs Argon2 hashing and persists new accounts, so bound burst
# creation separately from login. Keep this source-IP-only for the Lite build.
_REGISTER_IP = SlidingWindowRateLimiter(limit=5, window_seconds=600)


def reset_all_rate_limits() -> None:
    """Reset process-local authentication limiter state.

    Intended for deterministic test setup. Multi-process production rate
    limiting still belongs at a reverse proxy or shared store.
    """
    for limiter in (_LOGIN_IP, _LOGIN_ACCOUNT, _REGISTER_IP):
        limiter.clear()


def _client_key(request) -> str:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host or "unknown")


def _account_key(email: str) -> str:
    raw = str(email or "")
    if len(raw) > EMAIL_MAX_LENGTH:
        return "<oversize>"
    normalized = raw.strip().lower()
    if not normalized:
        return "<empty>"
    digest = hashlib.blake2s(normalized.encode("utf-8"), digest_size=16).hexdigest()
    return f"email:{digest}"


def check_login_rate_limit(request, email: str) -> tuple[bool, int]:
    ip_key = _client_key(request)
    account_key = _account_key(email)

    # Do not create/update per-account state for traffic already rejected by the
    # source-IP budget.  Otherwise an attacker can retain unbounded email keys by
    # rotating arbitrary addresses behind a single blocked IP.
    ip_allowed, ip_retry = _LOGIN_IP.consume(ip_key)
    if not ip_allowed:
        return False, ip_retry

    account_allowed, account_retry = _LOGIN_ACCOUNT.consume(account_key)
    if not account_allowed:
        return False, account_retry
    return True, 0


def reset_login_account(email: str) -> None:
    _LOGIN_ACCOUNT.reset(_account_key(email))


def check_register_rate_limit(request) -> tuple[bool, int]:
    """Bound account-creation bursts without changing lecture/job limits."""
    return _REGISTER_IP.consume(_client_key(request))
