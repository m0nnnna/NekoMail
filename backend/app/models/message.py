import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.attachment import Attachment


class Message(Base):
    """A synced mail message (Phase 4). Keyed by an internal autoincrement
    id, not IMAP uid -- uid is only unique within
    (account, folder, uidvalidity) and gets reused after a UIDVALIDITY
    change, which would collide with `.eml` filenames if used as the key.

    `account_id` duplicates what's reachable via `folder_id` -> Folder --
    it's a deliberate denormalization so a unified-inbox query doesn't need
    a join through Folder.
    """

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("folder_id", "uid", name="uq_message_folder_uid"),
        Index("ix_message_message_id_header", "message_id_header"),
        Index("ix_message_thread_id", "thread_id"),
        Index("ix_message_folder_date", "folder_id", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), nullable=False)

    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)

    message_id_header: Mapped[str | None] = mapped_column(String(998))
    in_reply_to: Mapped[str | None] = mapped_column(String(998))
    references: Mapped[str | None] = mapped_column(Text)
    # Simple heuristic (first References entry, else In-Reply-To, else own
    # Message-ID, else a generated id for headerless mail) -- not full
    # JWZ-style thread merging.
    thread_id: Mapped[str] = mapped_column(String(998), nullable=False)

    # "from" is a Python keyword, hence from_addrs not from_.
    from_addrs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    to_addrs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    cc_addrs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    bcc_addrs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    subject: Mapped[str | None] = mapped_column(String(998))
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snippet: Mapped[str | None] = mapped_column(String(512))

    # Raw IMAP flags as fetched at sync time. Not kept in sync with
    # server-side flag changes made after the initial fetch (Phase 4 gap).
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    is_encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    eml_path: Mapped[str] = mapped_column(String(512), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    attachments: Mapped[list["Attachment"]] = relationship(back_populates="message", cascade="all, delete-orphan")
