import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

# RFC 6154 special-use attributes we recognize, plus "inbox" which RFC 6154
# doesn't tag (INBOX is already structurally distinguished) but the UI still
# needs to know about.
SPECIAL_USE_KINDS = ("inbox", "all", "archive", "drafts", "flagged", "junk", "sent", "trash", "important")


class Folder(Base):
    """A mailbox/folder discovered on an Account via IMAP LIST, plus the
    sync engine's per-folder checkpoint state (Phase 4).

    - uidvalidity: None until the folder has been synced at least once.
      When the server reports a different value than this, the sync engine
      must reconcile local Message rows by Message-ID rather than trust
      their `uid` column, since UIDs are only unique within
      (account, folder, uidvalidity) and get reused after a change.
    - last_seen_uid: highest UID the forward-sync pass has confirmed. New
      mail is anything with UID > last_seen_uid.
    - backfill_watermark: None until first sync initializes it; N means
      "resume backfilling older mail starting at UID 1:{N-1}"; 0 means
      backfill is complete.
    """

    __tablename__ = "folders"
    __table_args__ = (UniqueConstraint("account_id", "name", name="uq_folder_account_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    delimiter: Mapped[str | None] = mapped_column(String(4))
    special_use: Mapped[str | None] = mapped_column(String(16))
    is_selectable: Mapped[bool] = mapped_column(Boolean, default=True)

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    uidvalidity: Mapped[int | None] = mapped_column(BigInteger)
    last_seen_uid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    backfill_watermark: Mapped[int | None] = mapped_column(BigInteger)
