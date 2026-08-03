import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Contact(Base):
    """Auto-upserted from From/To/Cc headers during sync (Phase 4) --
    compose autocomplete only, not a full address-book feature. Phase 9
    (PGP) added `pgp_public_key`, the only field a user can set directly
    (rather than have derived from mail) -- a contact with no mail history
    yet can still be created just to hold a key for composing to them.

    `email` is globally unique, which only makes sense while NekoMail
    stays single-admin-user; a multi-user version would need a
    (user_id, email) composite unique instead.
    """

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(256))

    # Armored ASCII public key text -- not sensitive (it's public by
    # definition), stored plain (unlike Account's credential columns, no
    # EncryptedString needed). NekoMail never holds a *private* key
    # server-side, for anyone (see services/mail/compose.py's raw_mime path).
    pgp_public_key: Mapped[str | None] = mapped_column(Text)

    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
