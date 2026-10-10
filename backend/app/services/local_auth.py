"""Local auto-login for the native window (desktop mode only).

Design (see ultimit/NOTES.md):
  * At server start a random secret is written to
    ``$XDG_RUNTIME_DIR/nekomail/token`` (0600, in a 0700 dir). Only the owning
    user (and root) can read it, so other local users cannot sign in.
  * The window process reads the secret and POSTs it (Authorization: Bearer)
    to ``/api/auth/local/ticket`` to get a single-use, 30 s ticket.
  * The window then navigates to ``/api/auth/local/session?ticket=...``,
    which sets the normal session cookie and redirects to ``/``. The
    long-lived secret never appears in a URL; the ticket in the URL is dead
    after one use.
  * Both endpoints refuse anything that is not a direct loopback request
    (non-loopback peer, proxy headers, non-localhost Host header), so the LAN
    listener and the Android client keep using the normal login.
"""
import hmac
import logging
import secrets
import time

from config import settings
import desktop_env

logger = logging.getLogger(__name__)

TICKET_TTL_SECONDS = 30
MAX_TICKETS = 16
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

_token: str | None = None
_tickets: dict[str, float] = {}


def init() -> None:
    global _token
    if not settings.desktop_mode:
        return
    _token = secrets.token_urlsafe(32)
    desktop_env.write_private_file(desktop_env.token_path(), _token + "\n")
    logger.info("local auto-login token written to %s", desktop_env.token_path())


def shutdown() -> None:
    global _token
    _token = None
    _tickets.clear()
    if settings.desktop_mode:
        try:
            desktop_env.token_path().unlink()
        except (FileNotFoundError, PermissionError):
            pass


def enabled() -> bool:
    return settings.desktop_mode and _token is not None


def request_is_local(request) -> bool:
    """Direct loopback request only: no proxy headers, loopback peer, and a
    localhost Host header (blocks DNS-rebinding style access)."""
    if request.headers.get("x-forwarded-for") or request.headers.get("forwarded") or request.headers.get("x-real-ip"):
        return False
    peer = request.client.host if request.client else ""
    if peer not in ("127.0.0.1", "::1"):
        return False
    host = request.headers.get("host", "")
    hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    return hostname.strip("[]") in LOOPBACK_HOSTS


def check_token(candidate: str) -> bool:
    return _token is not None and hmac.compare_digest(candidate.encode(), _token.encode())


def issue_ticket() -> str:
    now = time.monotonic()
    for t in [t for t, exp in _tickets.items() if exp < now]:
        del _tickets[t]
    if len(_tickets) >= MAX_TICKETS:
        _tickets.pop(min(_tickets, key=_tickets.get))
    ticket = secrets.token_urlsafe(24)
    _tickets[ticket] = now + TICKET_TTL_SECONDS
    return ticket


def redeem_ticket(ticket: str) -> bool:
    expires = _tickets.pop(ticket, None)
    return expires is not None and expires >= time.monotonic()
