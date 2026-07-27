"""tweede grondstof toevoegen aan werkplekken

Revision ID: 86eb7fa1f495
Revises: 0326f4a6c27c
Create Date: 2026-07-27 07:52:07.175159

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '86eb7fa1f495'
down_revision: Union[str, Sequence[str], None] = '0326f4a6c27c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('werkplekken', sa.Column('opbrengst_item_2_id', sa.Integer(), nullable=True))
    op.add_column(
        'werkplekken',
        sa.Column('opbrengst_2_kans', sa.Numeric(4, 3), nullable=False, server_default='0.25'),
    )
    op.create_foreign_key(
        'fk_werkplekken_opbrengst_item_2_id_items',
        'werkplekken', 'items', ['opbrengst_item_2_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_werkplekken_opbrengst_item_2_id_items', 'werkplekken', type_='foreignkey')
    op.drop_column('werkplekken', 'opbrengst_2_kans')
    op.drop_column('werkplekken', 'opbrengst_item_2_id')
