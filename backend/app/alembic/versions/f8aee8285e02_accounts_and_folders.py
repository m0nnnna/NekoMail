"""accounts and folders

Revision ID: f8aee8285e02
Revises: 0001
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database

revision: str = "f8aee8285e02"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", database.GUID(), nullable=False),
        sa.Column("user_id", database.GUID(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("imap_host", sa.String(length=256), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False),
        sa.Column("imap_security", sa.String(length=16), nullable=False),
        sa.Column("imap_username", sa.String(length=256), nullable=False),
        sa.Column("imap_password", database.EncryptedString(), nullable=False),
        sa.Column("smtp_host", sa.String(length=256), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False),
        sa.Column("smtp_security", sa.String(length=16), nullable=False),
        sa.Column("smtp_username", sa.String(length=256), nullable=False),
        sa.Column("smtp_password", database.EncryptedString(), nullable=False),
        sa.Column("verify_ssl", sa.Boolean(), nullable=False),
        sa.Column("auto_saves_sent", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "folders",
        sa.Column("id", database.GUID(), nullable=False),
        sa.Column("account_id", database.GUID(), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("delimiter", sa.String(length=4), nullable=True),
        sa.Column("special_use", sa.String(length=16), nullable=True),
        sa.Column("is_selectable", sa.Boolean(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "name", name="uq_folder_account_name"),
    )


def downgrade() -> None:
    op.drop_table("folders")
    op.drop_table("accounts")
