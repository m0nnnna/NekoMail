"""IMAP-side mail mutations (Phase 5): flag changes and folder moves --
archive/trash/generic-move all reduce to the same underlying move primitive.
Mirrors sync.py (the "sync mail over IMAP" module) as the "mutate mail over
IMAP" one.

Built bulk-first: every action here takes a list of message ids and groups
them by (account_id, folder_id) so a multi-select action opens one IMAP
connection per affected folder rather than one per message.
"""

import asyncio
import logging
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from models.folder import Folder
from models.message import Message
from services.mail.account_conn import imap_params
from services.mail.probe import connect_imap, imap_login
from services.mail.sync import eml_abs_path, lock_for_folder, quote_mailbox, sync_folder
from services.ws_manager import manager as ws_manager

logger = logging.getLogger(__name__)


async def _load_messages(db: AsyncSession, user_id: uuid.UUID, message_ids: list[int]) -> list[Message]:
    result = await db.execute(
        select(Message)
        .join(Account, Account.id == Message.account_id)
        .where(Account.user_id == user_id, Message.id.in_(message_ids))
    )
    return list(result.scalars())


def _group_by_folder(messages: list[Message]) -> dict[tuple[uuid.UUID, uuid.UUID], list[Message]]:
    groups: dict[tuple[uuid.UUID, uuid.UUID], list[Message]] = defaultdict(list)
    for m in messages:
        groups[(m.account_id, m.folder_id)].append(m)
    return groups


def _uid_set(messages: list[Message]) -> str:
    return ",".join(str(m.uid) for m in messages)


def _result(succeeded_ids: list[int], failed: list[dict]) -> dict:
    return {"succeeded_ids": succeeded_ids, "failed": failed}


def _missing_errors(requested_ids: list[int], found: list[Message]) -> list[dict]:
    found_ids = {m.id for m in found}
    return [{"message_id": mid, "error": "Message not found"} for mid in requested_ids if mid not in found_ids]


async def _set_flags_group(db: AsyncSession, group: list[Message], add: list[str], remove: list[str]) -> None:
    account = await db.get(Account, group[0].account_id)
    folder = await db.get(Folder, group[0].folder_id)
    uid_set = _uid_set(group)

    params = await imap_params(db, account)
    client = await connect_imap(params)
    try:
        login_resp = await imap_login(client, params)
        if login_resp.result != "OK":
            raise RuntimeError(f"Login failed: {login_resp.lines}")
        select_resp = await client.select(quote_mailbox(folder.name))
        if select_resp.result != "OK":
            raise RuntimeError(f"SELECT {folder.name!r} failed: {select_resp.lines}")

        if add:
            resp = await client.uid("store", uid_set, "+FLAGS", f"({' '.join(add)})")
            if resp.result != "OK":
                raise RuntimeError(f"STORE +FLAGS failed: {resp.lines}")
        if remove:
            resp = await client.uid("store", uid_set, "-FLAGS", f"({' '.join(remove)})")
            if resp.result != "OK":
                raise RuntimeError(f"STORE -FLAGS failed: {resp.lines}")
    finally:
        try:
            await asyncio.wait_for(client.logout(), timeout=5)
        except Exception:
            pass

    add_set, remove_set = set(add), set(remove)
    for m in group:
        current = (set(m.flags or []) | add_set) - remove_set
        m.flags = list(current)
    await db.commit()


async def set_flags(db: AsyncSession, user_id: uuid.UUID, message_ids: list[int], add: list[str], remove: list[str]) -> dict:
    messages = await _load_messages(db, user_id, message_ids)
    failed = _missing_errors(message_ids, messages)
    succeeded: list[int] = []

    for (account_id, folder_id), group in _group_by_folder(messages).items():
        async with lock_for_folder(account_id, folder_id):
            try:
                await _set_flags_group(db, group, add, remove)
                succeeded.extend(m.id for m in group)
            except Exception as exc:
                logger.exception("set_flags failed for account %s folder %s", account_id, folder_id)
                failed.extend({"message_id": m.id, "error": str(exc)} for m in group)

    if succeeded:
        await ws_manager.broadcast({"type": "flags_changed", "message_ids": succeeded, "add": add, "remove": remove})

    return _result(succeeded, failed)


async def _move_group(db: AsyncSession, account_id: uuid.UUID, source_folder_id: uuid.UUID, target: Folder, group: list[Message]) -> list[int]:
    """Move `group` (all in one source folder) to `target` via IMAP
    COPY + STORE \\Deleted + EXPUNGE, then delete the local rows and let the
    ordinary sync pipeline (sync_folder) pick the message back up in its new
    folder under its new UID -- avoids having to parse the server's COPYUID
    response ourselves, at the cost of one redundant re-fetch."""
    async with lock_for_folder(account_id, source_folder_id):
        account = await db.get(Account, account_id)
        source = await db.get(Folder, source_folder_id)
        uid_set = _uid_set(group)

        params = await imap_params(db, account)
        client = await connect_imap(params)
        try:
            login_resp = await imap_login(client, params)
            if login_resp.result != "OK":
                raise RuntimeError(f"Login failed: {login_resp.lines}")
            select_resp = await client.select(quote_mailbox(source.name))
            if select_resp.result != "OK":
                raise RuntimeError(f"SELECT {source.name!r} failed: {select_resp.lines}")

            copy_resp = await client.uid("copy", uid_set, quote_mailbox(target.name))
            if copy_resp.result != "OK":
                raise RuntimeError(f"COPY to {target.name!r} failed: {copy_resp.lines}")

            store_resp = await client.uid("store", uid_set, "+FLAGS", "(\\Deleted)")
            if store_resp.result != "OK":
                raise RuntimeError(f"STORE \\Deleted failed: {store_resp.lines}")

            expunge_resp = await client.expunge()
            if expunge_resp.result != "OK":
                raise RuntimeError(f"EXPUNGE failed: {expunge_resp.lines}")
        finally:
            try:
                await asyncio.wait_for(client.logout(), timeout=5)
            except Exception:
                pass

        moved_ids = [m.id for m in group]
        for m in group:
            try:
                eml_abs_path(m.eml_path).unlink(missing_ok=True)
            except Exception:
                logger.exception("Failed to unlink .eml for message %s", m.id)
            await db.delete(m)
        await db.commit()

    await sync_folder(db, account, target)
    return moved_ids


async def move_messages(db: AsyncSession, user_id: uuid.UUID, message_ids: list[int], target_folder_id: uuid.UUID) -> dict:
    target = await db.get(Folder, target_folder_id)
    target_account = await db.get(Account, target.account_id) if target is not None else None
    if target is None or target_account is None or target_account.user_id != user_id:
        return _result([], [{"message_id": mid, "error": "Target folder not found"} for mid in message_ids])

    messages = await _load_messages(db, user_id, message_ids)
    failed = _missing_errors(message_ids, messages)

    mismatched = [m for m in messages if m.account_id != target.account_id]
    failed.extend({"message_id": m.id, "error": "Message belongs to a different account than the target folder"} for m in mismatched)

    eligible = [m for m in messages if m.account_id == target.account_id]
    succeeded = [m.id for m in eligible if m.folder_id == target.id]
    to_move = [m for m in eligible if m.folder_id != target.id]

    for (account_id, folder_id), group in _group_by_folder(to_move).items():
        try:
            succeeded.extend(await _move_group(db, account_id, folder_id, target, group))
        except Exception as exc:
            logger.exception("move_messages failed for account %s folder %s", account_id, folder_id)
            failed.extend({"message_id": m.id, "error": str(exc)} for m in group)

    if succeeded:
        await ws_manager.broadcast({"type": "messages_moved", "message_ids": succeeded, "target_folder_id": str(target.id)})

    return _result(succeeded, failed)


async def resolve_special_folder(db: AsyncSession, account_id: uuid.UUID, kinds: tuple[str, ...]) -> Folder | None:
    result = await db.execute(
        select(Folder).where(Folder.account_id == account_id, Folder.special_use.in_(kinds), Folder.is_selectable.is_(True))
    )
    by_kind = {f.special_use: f for f in result.scalars()}
    for kind in kinds:
        if kind in by_kind:
            return by_kind[kind]
    return None


async def _move_to_special(db: AsyncSession, user_id: uuid.UUID, message_ids: list[int], kinds: tuple[str, ...], label: str) -> dict:
    messages = await _load_messages(db, user_id, message_ids)
    failed = _missing_errors(message_ids, messages)
    succeeded: list[int] = []

    by_account: dict[uuid.UUID, list[Message]] = defaultdict(list)
    for m in messages:
        by_account[m.account_id].append(m)

    for account_id, account_messages in by_account.items():
        target = await resolve_special_folder(db, account_id, kinds)
        if target is None:
            failed.extend({"message_id": m.id, "error": f"No {label} folder found for this account"} for m in account_messages)
            continue

        succeeded.extend(m.id for m in account_messages if m.folder_id == target.id)
        to_move = [m for m in account_messages if m.folder_id != target.id]

        for (a_id, folder_id), group in _group_by_folder(to_move).items():
            try:
                succeeded.extend(await _move_group(db, a_id, folder_id, target, group))
            except Exception as exc:
                logger.exception("%s failed for account %s folder %s", label, a_id, folder_id)
                failed.extend({"message_id": m.id, "error": str(exc)} for m in group)

    if succeeded:
        await ws_manager.broadcast({"type": "messages_moved", "message_ids": succeeded, "target_special_use": kinds[0]})

    return _result(succeeded, failed)


async def archive_messages(db: AsyncSession, user_id: uuid.UUID, message_ids: list[int]) -> dict:
    # Gmail tags "All Mail" \All rather than \Archive -- fall back to it so
    # Archive still works there even without a dedicated \Archive folder.
    return await _move_to_special(db, user_id, message_ids, ("archive", "all"), "Archive")


async def trash_messages(db: AsyncSession, user_id: uuid.UUID, message_ids: list[int]) -> dict:
    return await _move_to_special(db, user_id, message_ids, ("trash",), "Trash")
