"""clan systeem toevoegen

Revision ID: f52f01a95370
Revises: c9b449602e80
Create Date: 2026-07-27 22:35:28.050662

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f52f01a95370'
down_revision: Union[str, Sequence[str], None] = 'c9b449602e80'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('spelers', 'gilde_id', new_column_name='clan_id')
    op.create_table(
        'clans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('naam', sa.String(length=32), nullable=False),
        sa.Column('oprichter_id', sa.BigInteger(), nullable=False),
        sa.Column('totale_werk_opbrengst', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['oprichter_id'], ['spelers.discord_id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('naam'),
    )
    op.create_foreign_key(
        'fk_spelers_clan_id_clans', 'spelers', 'clans', ['clan_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_spelers_clan_id_clans', 'spelers', type_='foreignkey')
    op.drop_table('clans')
    op.alter_column('spelers', 'clan_id', new_column_name='gilde_id')
