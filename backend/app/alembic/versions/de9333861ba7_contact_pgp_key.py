"""contact pgp public key (Phase 9)

Revision ID: de9333861ba7
Revises: 3fc8cd9265eb
Create Date: 2026-08-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "de9333861ba7"
down_revision: Union[str, None] = "3fc8cd9265eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("pgp_public_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("contacts", "pgp_public_key")
