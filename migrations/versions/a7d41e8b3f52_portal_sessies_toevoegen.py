"""portal_sessies toevoegen

Revision ID: a7d41e8b3f52
Revises: 2b8a6f31c9de
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d41e8b3f52'
down_revision: Union[str, Sequence[str], None] = '2b8a6f31c9de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "portal_sessies",
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("discord_id", sa.BigInteger(), nullable=False),
        sa.Column("weergavenaam", sa.String(length=64), nullable=False),
        sa.Column("verloopt_op", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("token"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("portal_sessies")
