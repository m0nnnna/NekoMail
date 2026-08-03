"""In-process rate limiter for login abuse prevention.

NekoMail runs as a single ``uvicorn --workers 1`` process (required anyway for
the in-process WebSocket event bus — see services/mail/sync_manager.py), so a
plain in-memory dict is sufficient here; no Redis needed for a single-user
self-hosted app.
"""
import time

MAX_ATTEMPTS = 10          # failures before lockout
WINDOW_SECONDS = 900       # 15-minute rolling window

# ip -> (count, window_started_at)
_failures: dict[str, tuple[int, float]] = {}


def _get(ip: str) -> int:
    entry = _failures.get(ip)
    if entry is None:
        return 0
    count, started_at = entry
    if time.monotonic() - started_at > WINDOW_SECONDS:
        del _failures[ip]
        return 0
    return count


async def is_locked_out(ip: str) -> bool:
    return _get(ip) >= MAX_ATTEMPTS


async def record_failure(ip: str) -> int:
    count = _get(ip)
    if count == 0:
        _failures[ip] = (1, time.monotonic())
        return 1
    _, started_at = _failures[ip]
    count += 1
    _failures[ip] = (count, started_at)
    return count


async def clear_failures(ip: str) -> None:
    _failures.pop(ip, None)
