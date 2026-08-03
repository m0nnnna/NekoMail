from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.message import Message


class Attachment(Base):
    """Attachment metadata for a synced Message (Phase 4). Only metadata is
    recorded at sync time -- the bytes already live inside the message's
    stored `.eml` file. `storage_path` stays null until a future on-demand
    extraction feature pulls the attachment out into its own file."""

    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachment_message_id", "message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)

    filename: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(256), nullable=False, default="application/octet-stream")
    size: Mapped[int | None] = mapped_column(BigInteger)
    content_id: Mapped[str | None] = mapped_column(String(256))
    is_inline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    storage_path: Mapped[str | None] = mapped_column(String(512))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["Message"] = relationship(back_populates="attachments")
