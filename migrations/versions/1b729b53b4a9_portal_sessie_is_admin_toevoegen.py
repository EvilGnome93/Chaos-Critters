"""portal_sessie is_admin toevoegen

Revision ID: 1b729b53b4a9
Revises: a7d41e8b3f52
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b729b53b4a9'
down_revision: Union[str, Sequence[str], None] = 'a7d41e8b3f52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "portal_sessies",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("portal_sessies", "is_admin")
