"""outlook oauth: account auth_type + token columns, password columns
become optional

Revision ID: 5da95950ce47
Revises: 7a1c9f4e2b6d
Create Date: 2026-08-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import database

revision: str = "5da95950ce47"
down_revision: Union[str, None] = "7a1c9f4e2b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column("imap_password", existing_type=database.EncryptedString(), nullable=True)
        batch_op.alter_column("smtp_password", existing_type=database.EncryptedString(), nullable=True)
        batch_op.add_column(sa.Column("auth_type", sa.String(length=16), nullable=False, server_default="password"))
        batch_op.add_column(sa.Column("oauth_provider", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("oauth_refresh_token", database.EncryptedString(), nullable=True))
        batch_op.add_column(sa.Column("oauth_access_token", database.EncryptedString(), nullable=True))
        batch_op.add_column(sa.Column("oauth_token_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("oauth_token_expires_at")
        batch_op.drop_column("oauth_access_token")
        batch_op.drop_column("oauth_refresh_token")
        batch_op.drop_column("oauth_provider")
        batch_op.drop_column("auth_type")
        batch_op.alter_column("smtp_password", existing_type=database.EncryptedString(), nullable=False)
        batch_op.alter_column("imap_password", existing_type=database.EncryptedString(), nullable=False)
