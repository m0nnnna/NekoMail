"""Compose & send (Phase 6). Builds a MIME message, sends it over SMTP, and
mirrors the result into IMAP -- Sent-folder append (skipped when the account
already auto-saves sent mail) and draft autosave.

Deliberately not a new DB table: a draft is just a `Message` row synced out
of the account's real Drafts folder, same as everything else in this app.
"Autosave" means APPEND a fresh copy, then delete the previous version by
its own uid -- see `save_draft`.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import formataddr, formatdate, getaddresses, make_msgid

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from models.folder import Folder
from models.message import Message
from services.mail.account_conn import imap_params, smtp_params
from services.mail.actions import resolve_special_folder
from services.mail.probe import CONNECT_TIMEOUT, build_ssl_context, connect_imap, imap_login, smtp_login
from services.mail.sync import eml_abs_path, lock_for_folder, quote_mailbox, sync_folder

logger = logging.getLogger(__name__)


def parse_recipients(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [addr for _name, addr in getaddresses([raw]) if addr]


@dataclass
class ComposeAttachment:
    filename: str
    mime_type: str
    data: bytes


def build_mime(
    *, from_email: str, from_name: str | None,
    to: str, cc: str, bcc: str, subject: str, body_text: str, message_id: str,
    in_reply_to: str | None, references: str | None,
    attachments: list[ComposeAttachment],
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    if to.strip():
        msg["To"] = to
    if cc.strip():
        msg["Cc"] = cc
    # Bcc is deliberately never set as a header -- it only ever becomes an
    # SMTP envelope recipient (see send_mail), otherwise it wouldn't be blind.
    msg["Subject"] = subject or ""
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body_text or "")
    for att in attachments:
        mime_type = att.mime_type or "application/octet-stream"
        maintype, _, subtype = mime_type.partition("/")
        msg.add_attachment(att.data, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=att.filename or "attachment")
    return msg


def _extract_message_id(raw: bytes) -> str | None:
    msg = message_from_bytes(raw, policy=default_policy)
    msgid = msg.get("Message-ID")
    return str(msgid).strip() if msgid else None


async def send_via_smtp(
    db: AsyncSession, account: Account, recipients: list[str], *,
    msg: EmailMessage | None = None, raw_bytes: bytes | None = None,
) -> None:
    params = await smtp_params(db, account)
    ctx = build_ssl_context(params.verify_ssl)
    kwargs = dict(hostname=params.host, port=params.port, timeout=CONNECT_TIMEOUT)
    if params.security == "ssl":
        kwargs["use_tls"] = True
        kwargs["tls_context"] = ctx
    elif params.security == "starttls":
        kwargs["start_tls"] = True
        kwargs["tls_context"] = ctx

    client = aiosmtplib.SMTP(**kwargs)
    await client.connect()
    try:
        await smtp_login(client, params)
        if raw_bytes is not None:
            # Client-side-encrypted PGP/MIME message (Phase 9) -- already
            # fully-formed bytes from the browser, sent as-is. The backend
            # never sees the plaintext for these.
            await client.sendmail(account.email_address, recipients, raw_bytes)
        else:
            await client.send_message(msg, recipients=recipients)
    finally:
        try:
            await client.quit()
        except Exception:
            pass


async def _append_and_sync(db: AsyncSession, account: Account, folder: Folder, raw: bytes, flags: list[str]) -> None:
    async with lock_for_folder(account.id, folder.id):
        params = await imap_params(db, account)
        client = await connect_imap(params)
        try:
            login_resp = await imap_login(client, params)
            if login_resp.result != "OK":
                raise RuntimeError(f"Login failed: {login_resp.lines}")
            flag_str = " ".join(flags) if flags else None
            resp = await client.append(raw, quote_mailbox(folder.name), flag_str)
            if resp.result != "OK":
                raise RuntimeError(f"APPEND to {folder.name!r} failed: {resp.lines}")
        finally:
            try:
                await asyncio.wait_for(client.logout(), timeout=5)
            except Exception:
                pass
    await sync_folder(db, account, folder)


async def _delete_message(db: AsyncSession, account: Account, folder: Folder, message: Message) -> None:
    """Permanently remove one message from its folder (STORE \\Deleted +
    EXPUNGE, no COPY) -- used to retire a draft's previous version once a
    newer APPEND has superseded it."""
    async with lock_for_folder(account.id, folder.id):
        params = await imap_params(db, account)
        client = await connect_imap(params)
        try:
            login_resp = await imap_login(client, params)
            if login_resp.result != "OK":
                raise RuntimeError(f"Login failed: {login_resp.lines}")
            select_resp = await client.select(quote_mailbox(folder.name))
            if select_resp.result != "OK":
                raise RuntimeError(f"SELECT {folder.name!r} failed: {select_resp.lines}")
            store_resp = await client.uid("store", str(message.uid), "+FLAGS", "(\\Deleted)")
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

        eml_abs_path(message.eml_path).unlink(missing_ok=True)
        await db.delete(message)
        await db.commit()


async def _find_by_message_id(db: AsyncSession, folder_id: uuid.UUID, message_id: str) -> Message | None:
    result = await db.execute(
        select(Message).where(Message.folder_id == folder_id, Message.message_id_header == message_id).limit(1)
    )
    return result.scalar_one_or_none()


async def save_draft(
    db: AsyncSession, account: Account, *,
    to: str, cc: str, bcc: str, subject: str, body_text: str,
    in_reply_to: str | None, references: str | None,
    attachments: list[ComposeAttachment], replace_message: Message | None,
    raw_mime: bytes | None = None,
) -> Message:
    drafts_folder = await resolve_special_folder(db, account.id, ("drafts",))
    if drafts_folder is None:
        raise RuntimeError("No Drafts folder found for this account")

    if raw_mime is not None:
        # Client-side-encrypted draft (Phase 9) -- already fully-formed,
        # relayed as-is; see send_mail's raw_mime branch for the full story.
        message_id = _extract_message_id(raw_mime) or make_msgid()
        raw_bytes = raw_mime
    else:
        message_id = make_msgid()
        msg = build_mime(
            from_email=account.email_address, from_name=account.label,
            to=to, cc=cc, bcc=bcc, subject=subject, body_text=body_text, message_id=message_id,
            in_reply_to=in_reply_to, references=references, attachments=attachments,
        )
        raw_bytes = msg.as_bytes()

    await _append_and_sync(db, account, drafts_folder, raw_bytes, ["\\Draft"])

    if replace_message is not None and replace_message.folder_id == drafts_folder.id:
        try:
            await _delete_message(db, account, drafts_folder, replace_message)
        except Exception:
            logger.exception("Failed to delete superseded draft %s", replace_message.id)

    saved = await _find_by_message_id(db, drafts_folder.id, message_id)
    if saved is None:
        raise RuntimeError("Draft saved but could not be re-read from Drafts folder")
    return saved


async def send_mail(
    db: AsyncSession, account: Account, *,
    to: str, cc: str, bcc: str, subject: str, body_text: str,
    in_reply_to: str | None, references: str | None,
    attachments: list[ComposeAttachment], draft_message: Message | None,
    raw_mime: bytes | None = None,
) -> Message | None:
    recipients = parse_recipients(to) + parse_recipients(cc) + parse_recipients(bcc)
    if not recipients:
        raise ValueError("At least one recipient is required")

    if raw_mime is not None:
        # Client-side PGP-encrypted send (Phase 9): the browser already
        # built the full PGP/MIME multipart/encrypted structure and
        # encrypted the body+attachments with openpgp.js -- this is the one
        # path where the backend genuinely never sees plaintext. `to`/`cc`/
        # `bcc` above are still used for the SMTP envelope recipient list
        # (email addresses aren't secret; only content is), but body_text/
        # attachments/subject are ignored here since raw_mime already has
        # the real (encrypted) content and headers baked in.
        message_id = _extract_message_id(raw_mime) or make_msgid()
        raw_bytes = raw_mime
        await send_via_smtp(db, account, recipients, raw_bytes=raw_bytes)
    else:
        message_id = make_msgid()
        msg = build_mime(
            from_email=account.email_address, from_name=account.label,
            to=to, cc=cc, bcc=bcc, subject=subject, body_text=body_text, message_id=message_id,
            in_reply_to=in_reply_to, references=references, attachments=attachments,
        )
        raw_bytes = msg.as_bytes()
        await send_via_smtp(db, account, recipients, msg=msg)

    if draft_message is not None:
        drafts_folder = await db.get(Folder, draft_message.folder_id)
        if drafts_folder is not None:
            try:
                await _delete_message(db, account, drafts_folder, draft_message)
            except Exception:
                logger.exception("Failed to delete draft %s after send", draft_message.id)

    sent_folder = await resolve_special_folder(db, account.id, ("sent",))
    if sent_folder is None:
        return None

    if not account.auto_saves_sent:
        await _append_and_sync(db, account, sent_folder, raw_bytes, ["\\Seen"])
    else:
        # The server already appended its own copy of what we just sent --
        # just resync Sent so it shows up locally without also double-appending.
        await sync_folder(db, account, sent_folder)

    return await _find_by_message_id(db, sent_folder.id, message_id)
