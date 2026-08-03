import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from models.folder import Folder
from models.message import Message
from services.mail.sync import eml_abs_path


async def list_messages(
    db: AsyncSession, user_id: uuid.UUID, *,
    account_id: uuid.UUID | None = None, folder_id: uuid.UUID | None = None,
    special_use: str | None = None,
    limit: int = 50, offset: int = 0,
) -> list[Message]:
    query = (
        select(Message)
        .join(Account, Account.id == Message.account_id)
        .where(Account.user_id == user_id)
        .order_by(Message.date.desc().nulls_last(), Message.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if account_id is not None:
        query = query.where(Message.account_id == account_id)
    if folder_id is not None:
        query = query.where(Message.folder_id == folder_id)
    if special_use is not None:
        query = query.join(Folder, Folder.id == Message.folder_id).where(Folder.special_use == special_use)

    result = await db.execute(query)
    return list(result.scalars())


def read_eml_bytes(message: Message) -> bytes:
    return eml_abs_path(message.eml_path).read_bytes()


async def get_unread_counts(db: AsyncSession, account_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Per-folder unread count for an account's sidebar badges. Counted in
    Python rather than a SQLite json_each aggregate -- flags is a small JSON
    list per row and this stays portable across SQLite builds without a
    JSON1 dependency; fine at the personal-mailbox scale this app targets."""
    result = await db.execute(select(Message.folder_id, Message.flags).where(Message.account_id == account_id))
    counts: dict[uuid.UUID, int] = {}
    for folder_id, flags in result.all():
        if "\\Seen" not in (flags or []):
            counts[folder_id] = counts.get(folder_id, 0) + 1
    return counts


async def get_message(db: AsyncSession, user_id: uuid.UUID, message_id: int) -> Message | None:
    query = (
        select(Message)
        .join(Account, Account.id == Message.account_id)
        .where(Account.user_id == user_id, Message.id == message_id)
        .options(selectinload(Message.attachments))
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()
