"""uitrusting toevoegen aan huisdieren

Revision ID: c9b449602e80
Revises: 86eb7fa1f495
Create Date: 2026-07-27 08:07:28.308002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9b449602e80'
down_revision: Union[str, Sequence[str], None] = '86eb7fa1f495'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('huisdieren', sa.Column('voerbak_niveau', sa.String(length=16), nullable=True))
    op.add_column(
        'huisdieren',
        sa.Column('zelfreinigend_actief', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('huisdieren', 'zelfreinigend_actief')
    op.drop_column('huisdieren', 'voerbak_niveau')
