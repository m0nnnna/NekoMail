import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from models.folder import Folder
from schemas.account import AccountCreate, AccountUpdate
from services.mail.account_conn import imap_params, smtp_params
from services.mail.probe import check_imap, check_smtp
from services.mail.probe import discover_folders as probe_discover_folders
from services.mail.sync import sync_account

logger = logging.getLogger(__name__)

_CONNECTION_FIELDS = {
    "imap_host", "imap_port", "imap_security", "imap_username", "imap_password",
    "smtp_host", "smtp_port", "smtp_security", "smtp_username", "smtp_password",
    "verify_ssl",
}

# Fixed for every Outlook/Microsoft 365 mailbox -- unlike self-hosted/Gmail
# accounts there's no per-user host/port to collect, XOAUTH2 handles auth.
OUTLOOK_IMAP_HOST = "outlook.office365.com"
OUTLOOK_IMAP_PORT = 993
OUTLOOK_SMTP_HOST = "smtp.office365.com"
OUTLOOK_SMTP_PORT = 587


def _describe_failure(result: dict) -> str:
    parts = []
    if not result["imap"]["ok"]:
        parts.append(f"IMAP: {result['imap']['detail']}")
    if not result["smtp"]["ok"]:
        parts.append(f"SMTP: {result['smtp']['detail']}")
    return " / ".join(parts)


async def test_connect(db: AsyncSession, account: Account) -> dict:
    imap_ok, imap_detail = await check_imap(await imap_params(db, account))
    smtp_ok, smtp_detail = await check_smtp(await smtp_params(db, account))
    return {"imap": {"ok": imap_ok, "detail": imap_detail}, "smtp": {"ok": smtp_ok, "detail": smtp_detail}}


async def _discover_and_sync_new_account(db: AsyncSession, account: Account) -> None:
    """Best-effort: test_connect already gated creation on real connectivity,
    so a hiccup here (an edge-case LIST response, a slow first sync) shouldn't
    roll back an otherwise-successful account creation -- the user can still
    retry via the existing manual Refresh Folders / Sync actions."""
    try:
        await refresh_folders(db, account)
        await sync_account(db, account)
    except Exception:
        logger.exception("Post-creation folder discovery/sync failed for account %s", account.id)


async def list_accounts(db: AsyncSession, user_id: uuid.UUID) -> list[Account]:
    result = await db.execute(select(Account).where(Account.user_id == user_id).order_by(Account.created_at))
    return list(result.scalars())


async def get_account(db: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID) -> Account | None:
    result = await db.execute(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    return result.scalar_one_or_none()


async def create_account(db: AsyncSession, user_id: uuid.UUID, data: AccountCreate) -> Account:
    account = Account(user_id=user_id, **data.model_dump())
    result = await test_connect(db, account)
    if not result["imap"]["ok"] or not result["smtp"]["ok"]:
        raise ValueError(_describe_failure(result))
    db.add(account)
    await db.flush()
    await _discover_and_sync_new_account(db, account)
    return account


async def create_oauth_outlook_account(
    db: AsyncSession, user_id: uuid.UUID, *,
    email: str, label: str, access_token: str, refresh_token: str, expires_at: datetime,
) -> Account:
    account = Account(
        user_id=user_id, label=label, email_address=email,
        imap_host=OUTLOOK_IMAP_HOST, imap_port=OUTLOOK_IMAP_PORT, imap_security="ssl",
        imap_username=email, imap_password=None,
        smtp_host=OUTLOOK_SMTP_HOST, smtp_port=OUTLOOK_SMTP_PORT, smtp_security="starttls",
        smtp_username=email, smtp_password=None,
        verify_ssl=True,
        # Exchange Online/Outlook.com reliably auto-saves its own Sent copy
        # on SMTP submission -- unlike self-hosted/Gmail this isn't a guess.
        auto_saves_sent=True,
        auth_type="oauth_outlook", oauth_provider="outlook",
        oauth_access_token=access_token, oauth_refresh_token=refresh_token, oauth_token_expires_at=expires_at,
    )
    result = await test_connect(db, account)
    if not result["imap"]["ok"] or not result["smtp"]["ok"]:
        raise ValueError(_describe_failure(result))
    db.add(account)
    await db.flush()
    await _discover_and_sync_new_account(db, account)
    return account


async def update_account(db: AsyncSession, account: Account, data: AccountUpdate) -> Account:
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(account, field, value)

    if _CONNECTION_FIELDS & changes.keys():
        result = await test_connect(db, account)
        if not result["imap"]["ok"] or not result["smtp"]["ok"]:
            raise ValueError(_describe_failure(result))

    await db.flush()
    # `updated_at` is server-computed (onupdate=func.now()); unlike INSERT,
    # SQLAlchemy doesn't eagerly RETURNING-fetch it on UPDATE for SQLite, so
    # it's left expired -- refresh explicitly or serialization crashes trying
    # to lazy-load it outside the async context.
    await db.refresh(account)
    return account


async def delete_account(db: AsyncSession, account: Account) -> None:
    await db.delete(account)
    await db.flush()


async def refresh_folders(db: AsyncSession, account: Account) -> list[Folder]:
    discovered = await probe_discover_folders(await imap_params(db, account))

    result = await db.execute(select(Folder).where(Folder.account_id == account.id))
    existing = {f.name: f for f in result.scalars()}

    seen_names = set()
    for d in discovered:
        seen_names.add(d.name)
        folder = existing.get(d.name)
        if folder is not None:
            folder.delimiter = d.delimiter
            folder.special_use = d.special_use
            folder.is_selectable = d.is_selectable
        else:
            db.add(Folder(
                account_id=account.id, name=d.name, delimiter=d.delimiter,
                special_use=d.special_use, is_selectable=d.is_selectable,
            ))

    for name, folder in existing.items():
        if name not in seen_names:
            await db.delete(folder)

    await db.flush()
    return await list_folders(db, account)


async def list_folders(db: AsyncSession, account: Account) -> list[Folder]:
    result = await db.execute(select(Folder).where(Folder.account_id == account.id).order_by(Folder.name))
    return list(result.scalars())
