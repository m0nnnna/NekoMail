"""sync engine: folder checkpoints, messages, attachments, contacts

Revision ID: 7a1c9f4e2b6d
Revises: f8aee8285e02
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database

revision: str = "7a1c9f4e2b6d"
down_revision: Union[str, None] = "f8aee8285e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("folders", sa.Column("uidvalidity", sa.BigInteger(), nullable=True))
    op.add_column("folders", sa.Column("last_seen_uid", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("folders", sa.Column("backfill_watermark", sa.BigInteger(), nullable=True))

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", database.GUID(), nullable=False),
        sa.Column("folder_id", database.GUID(), nullable=False),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("message_id_header", sa.String(length=998), nullable=True),
        sa.Column("in_reply_to", sa.String(length=998), nullable=True),
        sa.Column("references", sa.Text(), nullable=True),
        sa.Column("thread_id", sa.String(length=998), nullable=False),
        sa.Column("from_addrs", sa.JSON(), nullable=False),
        sa.Column("to_addrs", sa.JSON(), nullable=False),
        sa.Column("cc_addrs", sa.JSON(), nullable=False),
        sa.Column("bcc_addrs", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=True),
        sa.Column("date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snippet", sa.String(length=512), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("has_attachments", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("eml_path", sa.String(length=512), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("folder_id", "uid", name="uq_message_folder_uid"),
    )
    op.create_index("ix_message_message_id_header", "messages", ["message_id_header"])
    op.create_index("ix_message_thread_id", "messages", ["thread_id"])
    op.create_index("ix_message_folder_date", "messages", ["folder_id", "date"])

    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=256), nullable=False, server_default="application/octet-stream"),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("content_id", sa.String(length=256), nullable=True),
        sa.Column("is_inline", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attachment_message_id", "attachments", ["message_id"])

    op.create_table(
        "contacts",
        sa.Column("id", database.GUID(), nullable=False),
        sa.Column("user_id", database.GUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_contact_email"),
    )


def downgrade() -> None:
    op.drop_table("contacts")
    op.drop_index("ix_attachment_message_id", table_name="attachments")
    op.drop_table("attachments")
    op.drop_index("ix_message_folder_date", table_name="messages")
    op.drop_index("ix_message_thread_id", table_name="messages")
    op.drop_index("ix_message_message_id_header", table_name="messages")
    op.drop_table("messages")
    op.drop_column("folders", "backfill_watermark")
    op.drop_column("folders", "last_seen_uid")
    op.drop_column("folders", "uidvalidity")
