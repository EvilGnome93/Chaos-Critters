"""balans-audit: nachtwacht capaciteit + max werkende pets + item-teksten

Revision ID: 2b8a6f31c9de
Revises: f52f01a95370
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b8a6f31c9de'
down_revision: Union[str, Sequence[str], None] = 'f52f01a95370'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

werkplekken = sa.table("werkplekken", sa.column("type", sa.String), sa.column("capaciteit", sa.Integer))
instellingen = sa.table("instellingen", sa.column("sleutel", sa.String), sa.column("waarde", sa.String))
items = sa.table("items", sa.column("naam", sa.String), sa.column("beschrijving", sa.String))

BESCHRIJVINGEN_NIEUW = {
    "Graanvrije premium voeding": "Groter honger-herstel + tijdelijke stat boost voor 1 match. Kost ook 12x Groente + 1x Water",
    "Vers vlees/vis": "Volledig honger-herstel, duur. Kost ook 15x Algen + 8x Takken",
    "Simpele voerbak": "Per pet uit te rusten met /uitrusten. Geeft passief honger terug, vult de helft van het verval aan. Kost ook 2x Water + 2x Fruit",
    "Slimme voerbak": "Per pet uit te rusten met /uitrusten. Geeft passief honger terug, vult het volledige verval aan. Kost ook 40x Schroot + 20x Erts",
    "Zelfreinigend systeem": "Per pet uit te rusten met /uitrusten. Energie herstelt ook buiten rust (bijv. tijdens werk). Kost ook 3x Sterrenstof + 20x Schroot",
    "Focus drankje": "Tijdelijke gevecht_genen boost voor 1 ranked match. Kost ook 2x Bladeren + 1x Edelsteen",
    "Werk-elixer": "Tijdelijke werk_genen boost voor 1 werk cyclus. Kost ook 12x Erts + 2x Spijker",
    "Extra match token": "Koopt een ranked poging boven de dagelijkse gratis cooldown. Kost ook 30x Maanschijnkristal + 2x Edelsteen",
    "Naamkaartje": "Hernoem je pet. Kost ook 15x Takken + 1x Spijker",
    "Mysterie voedselzak": "Willekeurige voeding, goedkoper dan los kopen. Kost ook 1x Fruit + 1x Bladeren",
}

BESCHRIJVINGEN_OUD = {
    "Graanvrije premium voeding": "Groter honger-herstel + tijdelijke stat boost voor 1 match. Kost ook 3x Groente",
    "Vers vlees/vis": "Volledig honger-herstel, duur. Kost ook 3x Algen",
    "Simpele voerbak": "Per pet uit te rusten met /uitrusten. Geeft passief honger terug, vult de helft van het verval aan. Kost ook 2x Water",
    "Slimme voerbak": "Per pet uit te rusten met /uitrusten. Geeft passief honger terug, vult het volledige verval aan. Kost ook 5x Schroot",
    "Zelfreinigend systeem": "Per pet uit te rusten met /uitrusten. Energie herstelt ook buiten rust (bijv. tijdens werk). Kost ook 2x Sterrenstof",
    "Focus drankje": "Tijdelijke gevecht_genen boost voor 1 ranked match. Kost ook 2x Bladeren",
    "Werk-elixer": "Tijdelijke werk_genen boost voor 1 werk cyclus. Kost ook 3x Erts + 2x Spijker",
    "Extra match token": "Koopt een ranked poging boven de dagelijkse gratis cooldown. Kost ook 2x Maanschijnkristal + 1x Edelsteen",
    "Naamkaartje": "Hernoem je pet. Kost ook 3x Takken",
    "Mysterie voedselzak": "Willekeurige voeding, goedkoper dan los kopen. Kost ook 1x Fruit",
}


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(werkplekken.update().where(werkplekken.c.type == "Nachtwacht").values(capaciteit=2))
    op.execute(
        instellingen.update()
        .where(instellingen.c.sleutel == "max_werkende_pets_per_speler")
        .values(waarde="2")
    )
    for naam, tekst in BESCHRIJVINGEN_NIEUW.items():
        op.execute(items.update().where(items.c.naam == naam).values(beschrijving=tekst))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(werkplekken.update().where(werkplekken.c.type == "Nachtwacht").values(capaciteit=1))
    op.execute(
        instellingen.update()
        .where(instellingen.c.sleutel == "max_werkende_pets_per_speler")
        .values(waarde="3")
    )
    for naam, tekst in BESCHRIJVINGEN_OUD.items():
        op.execute(items.update().where(items.c.naam == naam).values(beschrijving=tekst))
