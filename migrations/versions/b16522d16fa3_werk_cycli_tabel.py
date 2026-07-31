"""werk_cycli-tabel toevoegen (admin panel fase 2, blok 3)

Revision ID: b16522d16fa3
Revises: 447da3feed31
Create Date: 2026-07-30 00:00:00.000000

De drie bestaande cycli worden hier meteen ingevoegd met exact de waarden
die tot nu toe hardcoded in cogs/werk.py stonden, zodat het gedrag na de
migratie ongewijzigd is en de portal-editor meteen gevuld is. Bewust in de
migratie i.p.v. alleen in scripts/seed.py: de bot draait bij het opstarten
wel de migraties maar niet de seed, dus anders zou de tabel op productie
leeg blijven tot iemand handmatig de seed draait.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b16522d16fa3'
down_revision: Union[str, Sequence[str], None] = '447da3feed31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    tabel = op.create_table(
        "werk_cycli",
        sa.Column("sleutel", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=False),
        sa.Column("duur_uren", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("energie_kost", sa.Integer(), nullable=False),
        sa.Column("output_multiplier", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("volgorde", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("sleutel"),
    )
    op.bulk_insert(
        tabel,
        [
            {"sleutel": "korte", "label": "Korte shift", "duur_uren": 2, "energie_kost": 20,
             "output_multiplier": 2.0, "volgorde": 1},
            {"sleutel": "lange", "label": "Lange shift", "duur_uren": 6, "energie_kost": 50,
             "output_multiplier": 2.3, "volgorde": 2},
            {"sleutel": "overnacht", "label": "Overnacht", "duur_uren": 10, "energie_kost": 70,
             "output_multiplier": 2.6, "volgorde": 3},
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("werk_cycli")
