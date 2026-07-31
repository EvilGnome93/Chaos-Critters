"""speler lifetime-tellers toevoegen (shiften, pvp/pve win/verlies)

Revision ID: 447da3feed31
Revises: 1b729b53b4a9
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '447da3feed31'
down_revision: Union[str, Sequence[str], None] = '1b729b53b4a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("spelers", sa.Column("shiften_voltooid", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("spelers", sa.Column("pvp_gewonnen", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("spelers", sa.Column("pvp_verloren", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("spelers", sa.Column("pve_gewonnen", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("spelers", sa.Column("pve_verloren", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("spelers", "pve_verloren")
    op.drop_column("spelers", "pve_gewonnen")
    op.drop_column("spelers", "pvp_verloren")
    op.drop_column("spelers", "pvp_gewonnen")
    op.drop_column("spelers", "shiften_voltooid")
