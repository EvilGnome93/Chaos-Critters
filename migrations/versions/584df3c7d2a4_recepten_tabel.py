"""recepten-tabel toevoegen (admin panel fase 2, blok 4)

Revision ID: 584df3c7d2a4
Revises: 387e1c3602fe
Create Date: 2026-07-30 00:00:00.000000

Zet de tot nu toe hardcoded RECEPT_KOSTEN-dict (cogs/verzorging.py) om in
echte rijen met FK's naar `items`. De data wordt hier meteen ingevoegd door
op naam op te zoeken in de bestaande items-tabel, zodat het gedrag na de
migratie ongewijzigd is en de portal-editor meteen gevuld is — de bot
draait bij opstart wel migraties maar niet scripts/seed.py.

Als een itemnaam onverwacht niet bestaat wordt die combinatie overgeslagen
i.p.v. de migratie te laten crashen: een ontbrekend recept betekent
"gratis craften" (vervelend maar herstelbaar via de portal), een gecrashte
migratie betekent dat de bot helemaal niet opstart.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '584df3c7d2a4'
down_revision: Union[str, Sequence[str], None] = '387e1c3602fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Exact de waarden die tot 2026-07-30 in cogs/verzorging.py:RECEPT_KOSTEN
# stonden (na de balans-audit van 2026-07-28).
RECEPTEN = {
    "Graanvrije premium voeding": [("Groente", 12), ("Water", 1)],
    "Vers vlees/vis": [("Algen", 15), ("Takken", 8)],
    "Mysterie voedselzak": [("Fruit", 1), ("Bladeren", 1)],
    "Naamkaartje": [("Takken", 15), ("Spijker", 1)],
    "Focus drankje": [("Bladeren", 2), ("Edelsteen", 1)],
    "Werk-elixer": [("Erts", 12), ("Spijker", 2)],
    "Extra match token": [("Maanschijnkristal", 30), ("Edelsteen", 2)],
    "Simpele voerbak": [("Water", 2), ("Fruit", 2)],
    "Slimme voerbak": [("Schroot", 40), ("Erts", 20)],
    "Zelfreinigend systeem": [("Sterrenstof", 3), ("Schroot", 20)],
}


def upgrade() -> None:
    """Upgrade schema."""
    tabel = op.create_table(
        "recepten",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("grondstof_id", sa.Integer(), nullable=False),
        sa.Column("aantal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grondstof_id"], ["items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "grondstof_id", name="uq_recepten_item_grondstof"),
    )

    verbinding = op.get_bind()
    item_ids = dict(verbinding.execute(sa.text("SELECT naam, id FROM items")).all())

    rijen = []
    for item_naam, ingredienten in RECEPTEN.items():
        item_id = item_ids.get(item_naam)
        if item_id is None:
            continue
        for grondstof_naam, aantal in ingredienten:
            grondstof_id = item_ids.get(grondstof_naam)
            if grondstof_id is None:
                continue
            rijen.append({"item_id": item_id, "grondstof_id": grondstof_id, "aantal": aantal})

    if rijen:
        op.bulk_insert(tabel, rijen)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("recepten")
