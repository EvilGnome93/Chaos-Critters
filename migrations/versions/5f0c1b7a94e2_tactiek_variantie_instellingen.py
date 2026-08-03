"""tactiek-variantie als instellingen (admin panel fase 2, blok 5)

Revision ID: 5f0c1b7a94e2
Revises: 8dd39652036a
Create Date: 2026-07-30 00:00:00.000000

TACTIEK_VARIANTIE stond hardcoded in utils/gevechten.py. De drie tactieken
liggen vast in de keuzemenu's van /pvp en /pve, dus een eigen tabel voegt
niets toe (rijen bij- of weghalen zou geen effect hebben): alleen de zes
getallen zijn zinvol aanpasbaar, en die passen prima in `instellingen`.

De bot draait bij het opstarten wel migraties maar niet seed.py, dus de
rijen moeten hier aangemaakt worden en niet alleen in scripts/seed.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f0c1b7a94e2'
down_revision: Union[str, Sequence[str], None] = '8dd39652036a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INSTELLINGEN = [
    ("tactiek_aggressief_variantie_min", "-0.25", "Aggressief: ondergrens van de machtsvariatie per ronde"),
    ("tactiek_aggressief_variantie_max", "0.35", "Aggressief: bovengrens van de machtsvariatie per ronde"),
    ("tactiek_gebalanceerd_variantie_min", "-0.15", "Gebalanceerd: ondergrens van de machtsvariatie per ronde"),
    ("tactiek_gebalanceerd_variantie_max", "0.15", "Gebalanceerd: bovengrens van de machtsvariatie per ronde"),
    ("tactiek_voorzichtig_variantie_min", "-0.10", "Voorzichtig: ondergrens van de machtsvariatie per ronde"),
    ("tactiek_voorzichtig_variantie_max", "0.10", "Voorzichtig: bovengrens van de machtsvariatie per ronde"),
]


def upgrade() -> None:
    """Upgrade schema."""
    verbinding = op.get_bind()
    for sleutel, waarde, beschrijving in INSTELLINGEN:
        verbinding.execute(
            sa.text(
                "INSERT INTO instellingen (sleutel, waarde, beschrijving) "
                "VALUES (:sleutel, :waarde, :beschrijving) ON CONFLICT (sleutel) DO NOTHING"
            ),
            {"sleutel": sleutel, "waarde": waarde, "beschrijving": beschrijving},
        )


def downgrade() -> None:
    """Downgrade schema."""
    verbinding = op.get_bind()
    for sleutel, _waarde, _beschrijving in INSTELLINGEN:
        verbinding.execute(
            sa.text("DELETE FROM instellingen WHERE sleutel = :sleutel"), {"sleutel": sleutel}
        )
