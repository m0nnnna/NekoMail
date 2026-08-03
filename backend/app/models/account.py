import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, EncryptedString

# "ssl" = implicit TLS from connect (IMAPS 993 / SMTPS 465).
# "starttls" = connect in plaintext, then upgrade (IMAP 143 / SMTP 587).
# "none" = never encrypt (LAN-only self-hosted relays).
SECURITY_MODES = ("ssl", "starttls", "none")

# "password" = plain IMAP/SMTP LOGIN with the stored, Fernet-encrypted
# password. "oauth_outlook" = XOAUTH2 with a short-lived bearer token
# refreshed from oauth_refresh_token (see services/mail/oauth_token.py) --
# Microsoft killed IMAP/SMTP basic auth, so this is the only way in for
# Outlook/Microsoft 365. Immutable after creation (Phase 7).
AUTH_TYPES = ("password", "oauth_outlook")


class Account(Base):
    """A single mailbox linked under the app's one admin User (see models.user).
    Credentials are stored Fernet-encrypted (see database.EncryptedString)."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    label: Mapped[str] = mapped_column(String(128), nullable=False)
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)

    imap_host: Mapped[str] = mapped_column(String(256), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_security: Mapped[str] = mapped_column(String(16), default="ssl")
    imap_username: Mapped[str] = mapped_column(String(256), nullable=False)
    # Nullable because an oauth_outlook account never has one -- auth goes
    # through oauth_refresh_token/oauth_access_token below instead.
    imap_password: Mapped[str | None] = mapped_column(EncryptedString)

    smtp_host: Mapped[str] = mapped_column(String(256), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_security: Mapped[str] = mapped_column(String(16), default="starttls")
    smtp_username: Mapped[str] = mapped_column(String(256), nullable=False)
    smtp_password: Mapped[str | None] = mapped_column(EncryptedString)

    auth_type: Mapped[str] = mapped_column(String(16), default="password", server_default="password")
    oauth_provider: Mapped[str | None] = mapped_column(String(32))
    oauth_refresh_token: Mapped[str | None] = mapped_column(EncryptedString)
    oauth_access_token: Mapped[str | None] = mapped_column(EncryptedString)
    oauth_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Off by default: only a trusted self-signed/private-CA server (e.g. an
    # onsite LAN mail server) should ever disable verification.
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True)

    # Per-account override -- some providers auto-append sent mail to the Sent
    # folder via IMAP, others don't, and it's not reliably inferable from the
    # provider alone. See NEXT_STEPS.md "Key data-model gotchas".
    auto_saves_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
