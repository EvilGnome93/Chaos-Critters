"""laatste verzorging op toevoegen

Revision ID: b3c7e1a9d264
Revises: 4faaffe78404
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c7e1a9d264'
down_revision: Union[str, Sequence[str], None] = '4faaffe78404'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'huisdieren',
        sa.Column('laatste_verzorging_op', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('huisdieren', 'laatste_verzorging_op')
