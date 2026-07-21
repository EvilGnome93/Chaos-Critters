"""grondstof-items hernoemen naar thematische namen

Revision ID: 9d3f2b6a7c41
Revises: b3c7e1a9d264
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d3f2b6a7c41'
down_revision: Union[str, Sequence[str], None] = 'b3c7e1a9d264'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# oude naam -> nieuwe naam
HERNOEMINGEN = {
    "Moestuin-oogst": "Groente",
    "Vijver-extract": "Algen",
    "Werkbank-materiaal": "Schroot",
    "Bos-oogst": "Takken",
    "Nachtwacht-extract": "Maanschijnkristal",
}

items = sa.table("items", sa.column("naam", sa.String))


def upgrade() -> None:
    """Upgrade schema."""
    for oud, nieuw in HERNOEMINGEN.items():
        op.execute(items.update().where(items.c.naam == oud).values(naam=nieuw))


def downgrade() -> None:
    """Downgrade schema."""
    for oud, nieuw in HERNOEMINGEN.items():
        op.execute(items.update().where(items.c.naam == nieuw).values(naam=oud))
