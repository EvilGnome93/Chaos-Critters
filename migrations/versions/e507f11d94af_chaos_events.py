"""chaos events

Revision ID: e507f11d94af
Revises: ff40d530dd7f
Create Date: 2026-08-05 17:38:45.286104

Nieuwe tabel `events` (zie db/models.py:Event) plus de standaardsterkte en
-duur per event-type als balans-instellingen. De bot draait bij het
opstarten wel migraties maar niet scripts/seed.py, dus die instellingen
moeten hier mee — anders staan ze op productie niet in de database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e507f11d94af'
down_revision: Union[str, Sequence[str], None] = 'ff40d530dd7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INSTELLINGEN = [
    ("event_standaard_duur_minuten", "60", "Standaardduur van een chaos-event, als het portal niets anders meegeeft"),
    ("event_incense_sterkte", "0.25", "Incense: factor op de spawn-drempel (0.25 = viermaal zo snel een spawn)"),
    ("event_sterrenregen_sterkte", "3.0", "Sterrenregen: factor op de spawnkans van Rare en hoger"),
    ("event_dubbele_grondstoffen_sterkte", "2.0", "Grondstoffenregen: factor op de grondstof-opbrengst per shift"),
    ("event_dubbele_coins_sterkte", "2.0", "Muntregen: factor op Chaos Coins uit werk en gevechten"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sleutel", sa.String(length=32), nullable=False),
        sa.Column("sterkte", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("gestart_op", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("eindigt_op", sa.DateTime(), nullable=False),
        sa.Column("aankondiging_kanaal_id", sa.BigInteger(), nullable=True),
        sa.Column("gestart_door", sa.BigInteger(), nullable=True),
        sa.Column("einde_gemeld", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    # De hete query is "welke events lopen er nu" — die draait bij het laden
    # van de cache en in de achtergrondtaak.
    op.create_index("ix_events_eindigt_op", "events", ["eindigt_op"])

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
    op.drop_index("ix_events_eindigt_op", table_name="events")
    op.drop_table("events")
