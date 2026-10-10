"""Desktop integration hooks for Ultimit (desktop mode only, no-ops otherwise).

  * Unread badge: the total INBOX unread count is written to
    ``$XDG_RUNTIME_DIR/nekomail/unread`` (plain integer, atomic rewrite, only
    when it changes) so the shell can show a badge without authenticating.
  * New-mail notifications over org.freedesktop.Notifications, coalesced
    (one notification per burst), only for genuinely new INBOX mail from the
    sync paths -- never for a folder's initial sync, backfill, or mail a
    rule already moved/marked read.
"""
import asyncio
import logging
import os
import shutil
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

import desktop_env
from config import settings
from database import AsyncSessionLocal
from models.account import Account
from models.folder import Folder
from models.message import Message

logger = logging.getLogger(__name__)

UNREAD_POLL_SECONDS = 10
# A burst of messages (one poll cycle, several IDLE pushes) becomes one
# notification: flush once nothing new has arrived for DEBOUNCE, or at MAX_WAIT.
DEBOUNCE_SECONDS = 3.0
MAX_WAIT_SECONDS = 10.0
ACTION_WAIT_SECONDS = 120

_last_unread: int | None = None
_pending: list[tuple[str, str]] = []  # (sender, subject)
_flush_task: asyncio.Task | None = None
_first_pending_at = 0.0
_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------- unread ----

async def compute_unread() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message.flags)
            .join(Folder, Folder.id == Message.folder_id)
            .join(Account, Account.id == Message.account_id)
            .where(Folder.special_use == "inbox", Account.is_active.is_(True))
        )
        return sum(1 for (flags,) in result.all() if "\\Seen" not in (flags or []))


async def refresh_unread() -> int | None:
    """Recompute and (if changed) rewrite the unread file."""
    global _last_unread
    if not settings.desktop_mode:
        return None
    try:
        count = await compute_unread()
        # Also rewrite if the file vanished (tmpfs cleanup, someone deleted it).
        if count != _last_unread or not desktop_env.unread_path().exists():
            desktop_env.write_private_file(desktop_env.unread_path(), f"{count}\n")
            _last_unread = count
        return count
    except Exception:
        logger.exception("unread count refresh failed")
        return None


async def unread_loop() -> None:
    while True:
        await refresh_unread()
        await asyncio.sleep(UNREAD_POLL_SECONDS)


def remove_unread_file() -> None:
    global _last_unread
    _last_unread = None
    if settings.desktop_mode:
        try:
            desktop_env.unread_path().unlink()
        except (FileNotFoundError, PermissionError):
            pass


# --------------------------------------------------------- notifications ----

def _sender_label(from_addrs) -> str:
    first = (from_addrs or [{}])[0] or {}
    return first.get("name") or first.get("email") or "Unknown sender"


async def notify_new_messages(message_ids: list[int]) -> None:
    """Called with the ids a forward sync pass reported as new (never initial
    sync / backfill). Keeps only mail that is still an unread INBOX message
    after rules ran, then queues it for a coalesced notification."""
    if not settings.desktop_mode or not settings.desktop_notifications or not message_ids:
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message.from_addrs, Message.subject, Message.flags)
            .join(Folder, Folder.id == Message.folder_id)
            .where(Message.id.in_(message_ids), Folder.special_use == "inbox")
            .order_by(Message.id)
        )
        rows = [(_sender_label(f), s or "(no subject)") for f, s, flags in result.all() if "\\Seen" not in (flags or [])]
    if not rows:
        return
    _queue(rows)


def _queue(rows: list[tuple[str, str]]) -> None:
    global _flush_task, _first_pending_at
    loop = asyncio.get_running_loop()
    if not _pending:
        _first_pending_at = loop.time()
    _pending.extend(rows)
    if _flush_task is not None and not _flush_task.done():
        _flush_task.cancel()  # restart the debounce window
    wait = min(DEBOUNCE_SECONDS, max(0.0, _first_pending_at + MAX_WAIT_SECONDS - loop.time()))
    _flush_task = asyncio.create_task(_flush_after(wait))


async def _flush_after(delay: float) -> None:
    await asyncio.sleep(delay)
    rows = list(_pending)
    _pending.clear()
    if rows:
        summary, body = format_notification(rows)
        await send_notification(summary, body)


def format_notification(rows: list[tuple[str, str]]) -> tuple[str, str]:
    if len(rows) == 1:
        sender, subject = rows[0]
        return sender, subject
    senders: list[str] = []
    for sender, _ in rows:
        if sender not in senders:
            senders.append(sender)
    shown = ", ".join(senders[:3]) + (f" +{len(senders) - 3}" if len(senders) > 3 else "")
    return f"{len(rows)} new messages", f"From {shown}"


def window_command() -> list[str]:
    if settings.window_command:
        return settings.window_command.split()
    found = shutil.which("nekomail")
    if found:
        return [found]
    return [sys.executable, str(Path(__file__).resolve().parents[2] / "desktop_app.py")]


async def send_notification(summary: str, body: str) -> None:
    """Show a notification; if the server supports actions and the user
    clicks it, open the NekoMail window. notify-send (libnotify) handles the
    action round trip; plain gdbus is the no-action fallback."""
    notify_send = shutil.which("notify-send")
    if notify_send:
        args = [
            notify_send, "--app-name=NekoMail", "--icon=nekomail", "--category=email.arrived",
            "--expire-time=8000", "--hint=string:desktop-entry:nekomail",
            "--action=default=Open NekoMail", "--", summary, body,
        ]
    elif shutil.which("gdbus"):
        args = [
            "gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
            "--object-path", "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.Notify",
            "NekoMail", "0", "nekomail", summary, body, "['default','Open NekoMail']", "{}", "8000",
        ]
    else:
        logger.warning("no notify-send/gdbus; skipping notification")
        return
    task = asyncio.create_task(_run_notifier(args))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run_notifier(args: list[str]) -> None:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=ACTION_WAIT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()  # our own child only
            await proc.wait()
            return
        err_text = err.decode(errors="replace").strip()
        if proc.returncode != 0:
            # notify-send exits 1 (but still shows the notification) when the
            # server doesn't advertise actions; only other failures are news.
            level = logging.INFO if "not supported" in err_text else logging.WARNING
            logger.log(level, "notification command exited %s: %s", proc.returncode, err_text)
        elif out.decode().strip() == "default":
            await asyncio.create_subprocess_exec(
                *window_command(), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
            )
    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            proc.kill()
        raise
    except Exception:
        logger.exception("notification failed")


async def on_sync_finished(new_message_ids: list[int]) -> None:
    """Single hook for the scheduler: refresh the badge and notify."""
    await refresh_unread()
    await notify_new_messages(new_message_ids)
