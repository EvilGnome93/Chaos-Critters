"""element toevoegen aan pet_soorten

Revision ID: 0326f4a6c27c
Revises: 4a81b4aab69b
Create Date: 2026-07-26 13:28:38.233574

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0326f4a6c27c'
down_revision: Union[str, Sequence[str], None] = '4a81b4aab69b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


element_enum = sa.Enum('grond', 'water', 'lucht', 'vuur', 'chaos', name='element')


def upgrade() -> None:
    """Upgrade schema."""
    element_enum.create(op.get_bind(), checkfirst=True)
    op.add_column('pet_soorten', sa.Column('element', element_enum, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('pet_soorten', 'element')
    element_enum.drop(op.get_bind(), checkfirst=True)
