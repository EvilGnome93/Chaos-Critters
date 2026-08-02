"""actieve_spawns-tabel toevoegen (spawn overleeft een herstart)

Revision ID: 3a145a5dbc05
Revises: 584df3c7d2a4
Create Date: 2026-07-30 00:00:00.000000

De actieve spawn per kanaal stond alleen in het geheugen, waardoor elke
redeploy de lopende spawn onvangbaar maakte: de embed bleef in Discord
staan maar /vang antwoordde "geen spawn actief".

Geen data om over te zetten: wat er op het moment van de migratie in het
geheugen zit is per definitie al weg zodra de bot herstart.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a145a5dbc05'
down_revision: Union[str, Sequence[str], None] = '584df3c7d2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "actieve_spawns",
        sa.Column("channel_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("soort_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["soort_id"], ["pet_soorten.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("actieve_spawns")
