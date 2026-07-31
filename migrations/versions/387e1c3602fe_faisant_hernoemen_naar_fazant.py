"""Faisant hernoemen naar Fazant (spelfout)

Revision ID: 387e1c3602fe
Revises: b16522d16fa3
Create Date: 2026-07-30 00:00:00.000000

Verzoek van de gebruiker: "Faisant" was een verkeerde spelling, het is
"Fazant". Als migratie i.p.v. handmatig in de database (zoals bij eerdere
hernoemingen als Lemuur -> Maki), zodat het ook vanzelf op productie landt
bij de eerstvolgende deploy — de bot draait bij opstart wel migraties maar
niet scripts/seed.py.

Belangrijk: dit moet een UPDATE zijn en geen "verwijderen + opnieuw
seeden". seed.py gebruikt INSERT ... ON CONFLICT DO NOTHING op `naam`, dus
alleen de seed bijwerken zou de oude rij laten staan én een tweede rij
"Fazant" toevoegen. Bestaande Huisdier-records blijven ongemoeid: die
hebben hun eigen `naam`-kolom (bij het vangen gekopieerd), dus een al
gevangen exemplaar houdt de naam van toen. Op het moment van schrijven
waren er nul gevangen exemplaren.

De afbeelding is meegehernoemd (docs/assets/faisant.png -> fazant.png), dus
de URL wordt hier ook bijgewerkt. Die verwijst naar de `main`-branch op
GitHub; dit bestand is samen met de hernoemde afbeelding gepusht, dus de
URL bestaat zodra deze migratie op productie draait.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '387e1c3602fe'
down_revision: Union[str, Sequence[str], None] = 'b16522d16fa3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text(
            "UPDATE pet_soorten "
            "SET naam = 'Fazant', "
            "    afbeelding_url = REPLACE(afbeelding_url, 'faisant.png', 'fazant.png') "
            "WHERE naam = 'Faisant'"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        sa.text(
            "UPDATE pet_soorten "
            "SET naam = 'Faisant', "
            "    afbeelding_url = REPLACE(afbeelding_url, 'fazant.png', 'faisant.png') "
            "WHERE naam = 'Fazant'"
        )
    )
