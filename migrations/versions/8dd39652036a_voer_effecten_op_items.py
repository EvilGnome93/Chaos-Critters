"""voer-effecten als item-kolommen (admin panel fase 2, blok 5)

Revision ID: 8dd39652036a
Revises: 3a145a5dbc05
Create Date: 2026-07-30 00:00:00.000000

Zet de drie hardcoded voer-constanten uit utils/stats.py om in kolommen op
`items`, want ze waren alle drie op itemnaam gesleuteld en horen dus gewoon
bij het item zelf:

- HONGER_HERSTEL_WAARDEN -> items.honger_herstel
- VOLLEDIG_HERSTEL_ITEMS -> gaat op in honger_herstel = 100 (honger wordt
  altijd op 100 geklemd, dus het resultaat is identiek)
- VOERBAK_ITEMS_PER_NIVEAU -> items.voerbak_vanaf ("simpel" = bruikbaar
  door beide voerbakken, "slim" = alleen de Slimme, NULL = nooit
  automatisch)

De volgorde waarin een voerbak voer opeet (goedkoopste eerst) volgt uit
items.prijs en hoeft dus niet apart opgeslagen te worden: de bestaande
prijzen (10 / 35 / 60) geven precies de oude volgorde.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8dd39652036a'
down_revision: Union[str, Sequence[str], None] = '3a145a5dbc05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (itemnaam, honger_herstel, voerbak_vanaf) — exact het gedrag van vóór deze
# migratie. De Mysterie voedselzak staat er bewust niet bij: die kiest bij
# gebruik een willekeurig ánder voedingsitem en wordt nooit automatisch door
# een voerbak gepakt.
VOER = [
    ("Basis brokjes", 15, "simpel"),
    ("Graanvrije premium voeding", 40, "slim"),
    ("Vers vlees/vis", 100, "slim"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("items", sa.Column("honger_herstel", sa.Integer(), nullable=True))
    op.add_column("items", sa.Column("voerbak_vanaf", sa.String(length=16), nullable=True))

    verbinding = op.get_bind()
    for naam, herstel, vanaf in VOER:
        verbinding.execute(
            sa.text(
                "UPDATE items SET honger_herstel = :herstel, voerbak_vanaf = :vanaf WHERE naam = :naam"
            ),
            {"herstel": herstel, "vanaf": vanaf, "naam": naam},
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("items", "voerbak_vanaf")
    op.drop_column("items", "honger_herstel")
