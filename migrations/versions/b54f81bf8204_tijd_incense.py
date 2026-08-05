"""tijd-incense

Revision ID: b54f81bf8204
Revises: 30e55efa5f53
Create Date: 2026-08-05 22:11:55.615433

Nieuw event-type dat op tijd spawnt i.p.v. op berichten (2026-08-05,
verzoek van de gebruiker: "dan wil ik ook een incense optie voor tijd, dus
zonder typen"). Geen schemawijziging nodig — het past in de bestaande
events-tabel — alleen de standaardwaarde als instelling.

De sterkte is hier een **interval in minuten**, geen vermenigvuldiger.
Dat is meteen ook wat de admin invult, want minuten per spawn zijn een
stuk makkelijker in te schatten dan een factor.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b54f81bf8204'
down_revision: Union[str, Sequence[str], None] = '30e55efa5f53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INSTELLINGEN = [
    (
        "event_tijd_incense_sterkte",
        "5",
        "Tijd-incense: standaard aantal minuten tussen twee spawns (geen vermenigvuldiger)",
    ),
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
