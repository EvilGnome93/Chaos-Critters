"""events per kanaal

Revision ID: 30e55efa5f53
Revises: e507f11d94af
Create Date: 2026-08-05 20:08:54.959312

Spawn-gebonden events (incense, sterrenregen) gelden voortaan per kanaal
i.p.v. server-breed (2026-08-05, verzoek van de gebruiker: "ik wil per
kanaal kunnen kiezen, om bijvoorbeeld een event kanaal te kunnen gebruiken
LOS van de spawn kanalen").

NULL blijft "overal", dus bestaande events houden hun huidige gedrag.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '30e55efa5f53'
down_revision: Union[str, Sequence[str], None] = 'e507f11d94af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("events", sa.Column("kanaal_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events", "kanaal_id")
