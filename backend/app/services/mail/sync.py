"""Poll-based sync engine (Phase 4, first cut). Dual-connection IDLE comes
later -- this module is invoked on demand (manual trigger for now, a
scheduler later) and does a full connect/select/fetch/logout pass per folder.

Fetches one UID per IMAP round trip rather than batching multiple literals
into a single FETCH -- batch-literal responses are ambiguous to parse
reliably across servers, and at personal-mailbox scale the extra round trips
are cheap. Optimize later if it's ever actually the bottleneck.
"""

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.account import Account
from models.attachment import Attachment
from models.contact import Contact
from models.folder import Folder
from models.message import Message
from services.mail import parser
from services.mail.account_conn import imap_params
from services.mail.probe import connect_imap, imap_login

INITIAL_BATCH = 200
BACKFILL_BATCH = 200


@dataclass
class FolderStatus:
    uidvalidity: int
    uidnext: int


@dataclass
class FolderSyncResult:
    folder_name: str
    new_count: int
    backfilled_count: int
    reconciled: bool
    # Message ids from the forward-sync path only -- genuinely new mail
    # since the last check. Deliberately excludes a folder's initial-sync
    # batch and all backfilled mail (both are pre-existing mail the user
    # already had, not "new incoming mail"). Phase 8 rules key off this list
    # so they never fire retroactively -- see services/mail/rules.py.
    new_message_ids: list[int] = field(default_factory=list)


# The poll loop, an account's IDLE watcher, and a manual `POST .../sync` call
# can all target the same folder at once. Each opens its own DB session, so
# without this lock two concurrent passes can both pass the
# already-synced-uids check before either commits, then race each other into
# the `(folder_id, uid)` unique constraint on insert. Keyed by (account_id,
# folder_id) so different folders of the same account still sync in parallel.
_folder_locks: dict[tuple[uuid.UUID, uuid.UUID], asyncio.Lock] = {}


def lock_for_folder(account_id: uuid.UUID, folder_id: uuid.UUID) -> asyncio.Lock:
    key = (account_id, folder_id)
    lock = _folder_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _folder_locks[key] = lock
    return lock


def quote_mailbox(name: str) -> str:
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _parse_folder_status(lines) -> FolderStatus:
    blob = b" ".join(bytes(line) for line in lines)
    uidvalidity_m = re.search(rb"UIDVALIDITY (\d+)", blob)
    uidnext_m = re.search(rb"UIDNEXT (\d+)", blob)
    if not uidvalidity_m or not uidnext_m:
        raise RuntimeError(f"SELECT response missing UIDVALIDITY/UIDNEXT: {lines!r}")
    return FolderStatus(uidvalidity=int(uidvalidity_m.group(1)), uidnext=int(uidnext_m.group(1)))


def _parse_single_fetch(lines) -> tuple[bytes | None, list[str]]:
    """A single-UID FETCH response is a header line ending in a literal size
    marker (`{n}`), followed by the literal payload itself. Order of FLAGS
    vs the literal within the header line isn't guaranteed, so scan for the
    marker rather than assuming a fixed line layout."""
    literal_re = re.compile(rb"\{(\d+)\}\s*$")
    for i, line in enumerate(lines):
        if not isinstance(line, (bytes, bytearray)):
            continue
        raw_line = bytes(line)
        if literal_re.search(raw_line) and i + 1 < len(lines):
            payload = bytes(lines[i + 1])
            flags_m = re.search(rb"FLAGS \(([^)]*)\)", raw_line)
            flags = flags_m.group(1).decode(errors="replace").split() if flags_m else []
            return payload, flags
    return None, []


def _eml_dir(account_id: uuid.UUID, folder_id: uuid.UUID) -> Path:
    return Path(settings.mail_storage_path) / str(account_id) / str(folder_id)


def eml_abs_path(relative_path: str) -> Path:
    """Resolve a Message.eml_path (stored relative -- host and container
    storage roots differ) to an absolute path under the current process's
    mail_storage_path."""
    return Path(settings.mail_storage_path) / relative_path


def _write_eml(account_id: uuid.UUID, folder_id: uuid.UUID, message_id: int, raw: bytes) -> str:
    dir_path = _eml_dir(account_id, folder_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{message_id}.eml").write_bytes(raw)
    # Stored relative to mail_storage_path -- the host and container paths
    # differ (docker-compose points MAIL_STORAGE_PATH at /app/data/mail),
    # so an absolute path baked into the DB would break outside the container.
    return str(Path(str(account_id)) / str(folder_id) / f"{message_id}.eml")


async def _upsert_contacts(db: AsyncSession, user_id: uuid.UUID, addrs: list[dict]) -> None:
    unique = {}
    for addr in addrs:
        email_addr = (addr.get("email") or "").strip().lower()
        if email_addr:
            unique[email_addr] = addr.get("name")

    for email_addr, name in unique.items():
        result = await db.execute(select(Contact).where(Contact.email == email_addr))
        contact = result.scalar_one_or_none()
        if contact is None:
            db.add(Contact(user_id=user_id, email=email_addr, display_name=name))
        else:
            contact.last_seen_at = datetime.now(timezone.utc)
            if name and not contact.display_name:
                contact.display_name = name
    await db.flush()


async def _store_message(db: AsyncSession, account: Account, folder: Folder, uid: int, raw: bytes, flags: list[str]) -> Message:
    parsed = parser.parse_message(raw)

    message = Message(
        account_id=account.id, folder_id=folder.id, uid=uid,
        message_id_header=parsed.message_id_header, in_reply_to=parsed.in_reply_to,
        references=parsed.references, thread_id=parsed.thread_id,
        from_addrs=parsed.from_addrs, to_addrs=parsed.to_addrs,
        cc_addrs=parsed.cc_addrs, bcc_addrs=parsed.bcc_addrs,
        subject=parsed.subject, date=parsed.date, snippet=parsed.snippet,
        flags=flags, has_attachments=parsed.has_attachments, is_encrypted=parsed.is_encrypted,
        eml_path="", body_text=parsed.body_text,
    )
    db.add(message)
    await db.flush()  # need message.id before we can name the .eml file

    message.eml_path = _write_eml(account.id, folder.id, message.id, raw)

    for att in parsed.attachments:
        db.add(Attachment(
            message_id=message.id, filename=att.filename, mime_type=att.mime_type,
            size=att.size, content_id=att.content_id, is_inline=att.is_inline,
        ))

    await _upsert_contacts(db, account.user_id, parsed.from_addrs + parsed.to_addrs + parsed.cc_addrs + parsed.bcc_addrs)
    await db.flush()
    return message


async def _fetch_range(db: AsyncSession, client, account: Account, folder: Folder, low: int, high: int) -> list[int]:
    if low > high:
        return []

    resp = await client.uid_search(f"UID {low}:{high}", charset=None)
    if resp.result != "OK" or not resp.lines or not resp.lines[0]:
        return []
    uids = [int(x) for x in resp.lines[0].split()]
    if not uids:
        return []

    result = await db.execute(select(Message.uid).where(Message.folder_id == folder.id, Message.uid.in_(uids)))
    existing = {row[0] for row in result.all()}

    new_ids = []
    for uid in uids:
        if uid in existing:
            continue
        fetch_resp = await client.uid("fetch", str(uid), "(FLAGS RFC822)")
        if fetch_resp.result != "OK":
            continue
        raw, flags = _parse_single_fetch(fetch_resp.lines)
        if raw is None:
            # Expunged between the SEARCH above and this FETCH -- skip.
            continue
        message = await _store_message(db, account, folder, uid, raw, flags)
        new_ids.append(message.id)
    return new_ids


async def _fetch_message_id_header(client, uid: int) -> str | None:
    resp = await client.uid("fetch", str(uid), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
    if resp.result != "OK":
        return None
    raw, _flags = _parse_single_fetch(resp.lines)
    if not raw:
        return None
    m = re.search(rb"Message-ID:\s*(.+)", raw, re.IGNORECASE)
    return m.group(1).decode(errors="replace").strip() if m else None


async def _reconcile_uidvalidity(db: AsyncSession, client, folder: Folder, status: FolderStatus) -> None:
    """UIDVALIDITY changed: every local `uid` for this folder is now stale
    (uids are only meaningful within one (account, folder, uidvalidity)
    tuple). Remap local rows to their new uid by matching Message-ID rather
    than blind wipe-and-resync, which would duplicate everything."""
    resp = await client.uid_search("ALL", charset=None)
    if resp.result != "OK":
        raise RuntimeError(f"UID SEARCH failed during reconciliation: {resp.lines}")
    live_uids = [int(x) for x in resp.lines[0].split()] if resp.lines and resp.lines[0] else []

    result = await db.execute(select(Message).where(Message.folder_id == folder.id))
    local_by_msgid = {m.message_id_header: m for m in result.scalars() if m.message_id_header}

    matched_max_uid = 0
    for uid in live_uids:
        msgid = await _fetch_message_id_header(client, uid)
        if msgid and msgid in local_by_msgid:
            local_by_msgid[msgid].uid = uid
            matched_max_uid = max(matched_max_uid, uid)

    folder.uidvalidity = status.uidvalidity
    folder.last_seen_uid = matched_max_uid
    # The old backfill_watermark referred to pre-renumbering uids, which are
    # now meaningless -- stop auto-backfill rather than risk skipping or
    # re-fetching the wrong range under the new numbering. A future manual
    # "resync from scratch" action can restart backfill from uidnext-1 if needed.
    folder.backfill_watermark = 0
    await db.flush()


async def sync_folder(db: AsyncSession, account: Account, folder: Folder,
                       initial_batch: int = INITIAL_BATCH, backfill_batch: int = BACKFILL_BATCH) -> FolderSyncResult:
    async with lock_for_folder(account.id, folder.id):
        return await _sync_folder_locked(db, account, folder, initial_batch, backfill_batch)


async def _sync_folder_locked(db: AsyncSession, account: Account, folder: Folder,
                               initial_batch: int, backfill_batch: int) -> FolderSyncResult:
    params = await imap_params(db, account)
    client = await connect_imap(params)
    try:
        login_resp = await imap_login(client, params)
        if login_resp.result != "OK":
            raise RuntimeError(f"Login failed: {login_resp.lines}")

        select_resp = await client.select(quote_mailbox(folder.name))
        if select_resp.result != "OK":
            raise RuntimeError(f"SELECT {folder.name!r} failed: {select_resp.lines}")
        status = _parse_folder_status(select_resp.lines)

        new_count = 0
        backfilled_count = 0
        reconciled = False
        new_message_ids: list[int] = []

        if folder.uidvalidity is None:
            folder.uidvalidity = status.uidvalidity
            highest = status.uidnext - 1
            if highest >= 1:
                low = max(1, highest - initial_batch + 1)
                # Initial population of a never-before-synced folder -- not
                # "new incoming mail" from the user's perspective, so these
                # ids deliberately don't flow into new_message_ids below.
                new_count = len(await _fetch_range(db, client, account, folder, low, highest))
                folder.backfill_watermark = low - 1 if low > 1 else 0
            else:
                folder.backfill_watermark = 0
            folder.last_seen_uid = max(highest, 0)
        else:
            if folder.uidvalidity != status.uidvalidity:
                await _reconcile_uidvalidity(db, client, folder, status)
                reconciled = True

            highest = status.uidnext - 1
            if highest > folder.last_seen_uid:
                new_message_ids = await _fetch_range(db, client, account, folder, folder.last_seen_uid + 1, highest)
                new_count = len(new_message_ids)
                folder.last_seen_uid = highest

        if folder.backfill_watermark not in (None, 0):
            low = max(1, folder.backfill_watermark - backfill_batch + 1)
            backfilled_count = len(await _fetch_range(db, client, account, folder, low, folder.backfill_watermark))
            folder.backfill_watermark = low - 1 if low > 1 else 0

        await db.commit()
        return FolderSyncResult(
            folder_name=folder.name, new_count=new_count, backfilled_count=backfilled_count,
            reconciled=reconciled, new_message_ids=new_message_ids,
        )
    except Exception:
        await db.rollback()
        raise
    finally:
        try:
            await asyncio.wait_for(client.logout(), timeout=5)
        except Exception:
            pass


async def sync_account(db: AsyncSession, account: Account) -> list[FolderSyncResult]:
    result = await db.execute(select(Folder).where(Folder.account_id == account.id, Folder.is_selectable.is_(True)))
    folders = list(result.scalars())

    results = []
    for folder in folders:
        results.append(await sync_folder(db, account, folder))
    return results
