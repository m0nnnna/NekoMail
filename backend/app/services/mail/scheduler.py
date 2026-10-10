"""Background sync orchestration (Phase 4b): a periodic full poll as a safety
net, plus a dedicated IMAP IDLE connection per active account watching just
its INBOX for near-instant push. Both paths route new-mail results through
the same WebSocket broadcast.

Must run under `uvicorn --workers 1` -- watcher state (`_idle_tasks`) and the
WebSocket connection set (services/ws_manager.py) are in-process only.
"""

import asyncio
import logging
import uuid

import aioimaplib
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models.account import Account
from models.folder import Folder
from services import desktop
from services.mail import rules as rules_module
from services.mail import sync as sync_module
from services.mail.account_conn import imap_params
from services.mail.probe import connect_imap, imap_login
from services.mail.sync import quote_mailbox
from services.ws_manager import manager as ws_manager

logger = logging.getLogger(__name__)

# Refresh the IDLE command well under the ~29 minute window RFC 2177
# recommends servers enforce (confirmed against mail.nekos.farm in the
# Phase 2 spike). wait_server_push's own timeout is padded past this so the
# built-in idle_start() timer (which posts STOP_WAIT_SERVER_PUSH) always
# fires first -- a bare asyncio.TimeoutError here is only a defensive fallback.
IDLE_REFRESH_SECONDS = 25 * 60
_RECONNECT_BACKOFF = (5, 15, 30, 60, 120)

_idle_tasks: dict[uuid.UUID, asyncio.Task] = {}
_background_tasks: list[asyncio.Task] = []


async def _broadcast_new_mail(account_id: uuid.UUID, result: sync_module.FolderSyncResult) -> None:
    if result.new_count <= 0:
        return
    await ws_manager.broadcast({
        "type": "new_mail",
        "account_id": str(account_id),
        "folder_name": result.folder_name,
        "new_count": result.new_count,
    })


async def poll_loop() -> None:
    """Full sync of every active account's every folder, on a timer. Runs
    forever until cancelled -- catches anything a folder's IDLE watcher
    wouldn't (non-INBOX folders, a watcher that hasn't (re)connected yet)."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Account.id).where(Account.is_active.is_(True)))
                account_ids = [row[0] for row in result.all()]

            for account_id in account_ids:
                async with AsyncSessionLocal() as db:
                    try:
                        account = await db.get(Account, account_id)
                        if account is None or not account.is_active:
                            continue
                        # sync_folder (called per-folder inside sync_account)
                        # commits its own work -- nothing left to commit here.
                        results = await sync_module.sync_account(db, account)
                        # Rules run per folder, only against each folder's
                        # own new_message_ids -- lock_for_folder was already
                        # released by the time sync_account returned, so this
                        # can safely open its own IMAP connections for
                        # move/archive/trash actions without deadlocking.
                        for r in results:
                            if r.new_message_ids:
                                await rules_module.apply_rules_to_new_messages(db, account, r.new_message_ids)
                    except Exception:
                        logger.exception("poll_loop: sync failed for account %s", account_id)
                        continue
                for r in results:
                    await _broadcast_new_mail(account_id, r)
                await desktop.on_sync_finished([i for r in results for i in r.new_message_ids])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("poll_loop: unexpected top-level error")

        await asyncio.sleep(settings.poll_interval_seconds)


async def _on_idle_push(account_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        try:
            account = await db.get(Account, account_id)
            if account is None or not account.is_active:
                return
            result = await db.execute(
                select(Folder).where(Folder.account_id == account.id, Folder.special_use == "inbox")
            )
            inbox = result.scalar_one_or_none()
            if inbox is None:
                return
            # sync_folder commits its own work internally.
            sync_result = await sync_module.sync_folder(db, account, inbox)
            if sync_result.new_message_ids:
                await rules_module.apply_rules_to_new_messages(db, account, sync_result.new_message_ids)
        except Exception:
            logger.exception("IDLE-triggered sync failed for account %s", account_id)
            return

    await _broadcast_new_mail(account_id, sync_result)
    await desktop.on_sync_finished(sync_result.new_message_ids)


async def watch_account_idle(account_id: uuid.UUID) -> None:
    """Long-lived task: one dedicated IDLE connection on an account's INBOX.
    Never reused for fetches -- sync (triggered via `_on_idle_push`) always
    opens its own connection, since IDLE and other commands can't share a
    socket (Phase 2 finding)."""
    backoff_idx = 0
    while True:
        async with AsyncSessionLocal() as db:
            account = await db.get(Account, account_id)
            if account is None or not account.is_active:
                return
            result = await db.execute(
                select(Folder).where(Folder.account_id == account.id, Folder.special_use == "inbox")
            )
            inbox = result.scalar_one_or_none()
            # Resolved (and refreshed if needed) while `account` is still
            # attached to a live session -- imap_params persists a refreshed
            # oauth token back onto this row internally.
            params = await imap_params(db, account) if inbox is not None else None

        if inbox is None:
            await asyncio.sleep(60)
            continue

        client = None
        try:
            client = await connect_imap(params)
            login_resp = await imap_login(client, params)
            if login_resp.result != "OK":
                raise RuntimeError(f"IDLE login failed: {login_resp.lines}")
            select_resp = await client.select(quote_mailbox(inbox.name))
            if select_resp.result != "OK":
                raise RuntimeError(f"IDLE select failed: {select_resp.lines}")

            logger.info("IDLE watcher connected for account %s (%s)", account_id, account.email_address)
            backoff_idx = 0

            while True:
                idle_task = await client.idle_start(timeout=IDLE_REFRESH_SECONDS)
                try:
                    while True:
                        try:
                            msg = await client.wait_server_push(timeout=IDLE_REFRESH_SECONDS + 60)
                        except asyncio.TimeoutError:
                            msg = aioimaplib.STOP_WAIT_SERVER_PUSH

                        if msg == aioimaplib.STOP_WAIT_SERVER_PUSH:
                            break

                        lines = msg if isinstance(msg, list) else [msg]
                        if any(b"EXISTS" in bytes(line) for line in lines):
                            await _on_idle_push(account_id)
                finally:
                    client.idle_done()
                    try:
                        await asyncio.wait_for(asyncio.shield(idle_task), timeout=5)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("IDLE watcher for account %s dropped, reconnecting", account_id)
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.logout(), timeout=5)
                except Exception:
                    pass

        delay = _RECONNECT_BACKOFF[min(backoff_idx, len(_RECONNECT_BACKOFF) - 1)]
        backoff_idx += 1
        await asyncio.sleep(delay)


async def _stop_watcher(account_id: uuid.UUID) -> None:
    task = _idle_tasks.pop(account_id, None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("IDLE watcher for account %s raised during shutdown", account_id)


async def reconcile_idle_watchers() -> None:
    """Keeps one watch_account_idle task running per active Account,
    starting/stopping watchers as accounts are added, deactivated, or
    deleted. Polled rather than event-driven to keep account CRUD (routers/
    accounts.py) decoupled from the sync engine's internals."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Account.id).where(Account.is_active.is_(True)))
                active_ids = {row[0] for row in result.all()}

            for account_id in active_ids - _idle_tasks.keys():
                _idle_tasks[account_id] = asyncio.create_task(watch_account_idle(account_id))

            for account_id in list(_idle_tasks.keys() - active_ids):
                await _stop_watcher(account_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reconcile_idle_watchers: unexpected error")

        await asyncio.sleep(settings.idle_reconcile_interval_seconds)


async def start() -> None:
    _background_tasks.append(asyncio.create_task(poll_loop()))
    _background_tasks.append(asyncio.create_task(reconcile_idle_watchers()))
    if settings.desktop_mode:
        _background_tasks.append(asyncio.create_task(desktop.unread_loop()))


async def stop() -> None:
    for account_id in list(_idle_tasks.keys()):
        await _stop_watcher(account_id)

    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
