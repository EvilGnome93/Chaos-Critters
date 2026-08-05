"""dagelijkse opdrachten

Revision ID: ff40d530dd7f
Revises: 5f0c1b7a94e2
Create Date: 2026-08-05 16:21:00.100862

Nieuwe tabel `speler_opdrachten` (zie db/models.py:SpelerOpdracht) plus de
bijbehorende balans-instellingen. De bot draait bij het opstarten wel
migraties maar niet scripts/seed.py, dus de instellingen moeten hier mee —
anders staan ze op productie niet in de database en valt alles terug op de
defaults in de code.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff40d530dd7f'
down_revision: Union[str, Sequence[str], None] = '5f0c1b7a94e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INSTELLINGEN = [
    ("opdracht_reset_uur", "4", "Uur (Europe/Amsterdam) waarop de dagelijkse opdrachten voor iedereen resetten"),
    ("opdracht_bonus_alle_drie", "150", "Extra Chaos Coins wanneer alle drie de dagopdrachten af zijn"),
    # Per opdracht-type een doel en een beloning. De types zelf liggen vast in
    # utils/opdrachten.py (elk type heeft eigen code nodig om voortgang op te
    # hogen), dus alleen deze getallen zijn zinvol aanpasbaar — zelfde
    # afweging als bij de tactiek-variantie in fase 2 blok 5.
    ("opdracht_vangen_doel", "3", "Dagopdracht 'vang critters': aantal te vangen critters"),
    ("opdracht_vangen_beloning", "60", "Dagopdracht 'vang critters': Chaos Coins bij voltooiing"),
    ("opdracht_werken_doel", "2", "Dagopdracht 'voltooi shifts': aantal af te ronden werk-cycli"),
    ("opdracht_werken_beloning", "70", "Dagopdracht 'voltooi shifts': Chaos Coins bij voltooiing"),
    ("opdracht_winnen_doel", "1", "Dagopdracht 'win gevechten': aantal te winnen gevechten"),
    ("opdracht_winnen_beloning", "80", "Dagopdracht 'win gevechten': Chaos Coins bij voltooiing"),
    ("opdracht_voeren_doel", "3", "Dagopdracht 'voer je pets': aantal keer voeren via /verzorg"),
    ("opdracht_voeren_beloning", "40", "Dagopdracht 'voer je pets': Chaos Coins bij voltooiing"),
    ("opdracht_craften_doel", "1", "Dagopdracht 'craft items': aantal te craften items"),
    ("opdracht_craften_beloning", "70", "Dagopdracht 'craft items': Chaos Coins bij voltooiing"),
    ("opdracht_zeldzaam_vangen_doel", "1", "Dagopdracht 'vang iets zeldzaams': aantal critters van Rare of hoger"),
    ("opdracht_zeldzaam_vangen_beloning", "90", "Dagopdracht 'vang iets zeldzaams': Chaos Coins bij voltooiing"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "speler_opdrachten",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("speler_id", sa.BigInteger(), nullable=False),
        sa.Column("dag", sa.Date(), nullable=False),
        sa.Column("sleutel", sa.String(length=32), nullable=False),
        sa.Column("voortgang", sa.Integer(), nullable=False),
        sa.Column("doel", sa.Integer(), nullable=False),
        sa.Column("beloning", sa.Integer(), nullable=False),
        sa.Column("voltooid_op", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["speler_id"], ["spelers.discord_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("speler_id", "dag", "sleutel", name="uq_speler_opdracht_dag_sleutel"),
    )
    # De hete query is "de opdrachten van deze speler voor deze dag" — die
    # draait bij élke vangst/shift/gevecht, dus die verdient een index.
    op.create_index(
        "ix_speler_opdrachten_speler_dag", "speler_opdrachten", ["speler_id", "dag"]
    )

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
    op.drop_index("ix_speler_opdrachten_speler_dag", table_name="speler_opdrachten")
    op.drop_table("speler_opdrachten")
