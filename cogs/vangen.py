import random

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from db.engine import async_session
from db.models import Huisdier, PetSoort, Speler
from utils.discord_log import fmt_log, send_log

GENEN_VARIANTIE = 0.10  # +/- 10% rond de soort-basiswaarde


def _met_variantie(basis: float) -> float:
    factor = 1 + random.uniform(-GENEN_VARIANTIE, GENEN_VARIANTIE)
    return round(max(1.0, float(basis) * factor), 2)


class VangenCog(commands.Cog):
    """Spawns en het vangen van pets. Zie projectbrief sectie 7 en 8.

    Spawn-triggers (sectie 8) zijn nog niet gebouwd: /vang vangt op dit
    moment direct elke bekende soort op naam, zonder dat er eerst iets
    hoeft te spawnen. Dat volgt in de volgende stap.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="vang", description="Vang een pet die net gespawnd is")
    @app_commands.describe(naam="De naam van de pet-soort, zoals getoond in de spawn")
    async def vang(self, interaction: discord.Interaction, naam: str) -> None:
        async with async_session() as session:
            soort = await self._vind_soort(session, naam)
            if soort is None:
                await interaction.response.send_message(
                    f"Geen bekende pet-soort gevonden voor '{naam}'.", ephemeral=True
                )
                return
            if isinstance(soort, list):
                opties = ", ".join(s.naam for s in soort)
                await interaction.response.send_message(
                    f"'{naam}' is niet eenduidig, bedoelde je een van: {opties}?", ephemeral=True
                )
                return

            speler = await session.get(Speler, interaction.user.id)
            if speler is None:
                speler = Speler(discord_id=interaction.user.id)
                session.add(speler)

            huisdier = Huisdier(
                eigenaar_id=interaction.user.id,
                soort_id=soort.id,
                tier_id=soort.tier_id,
                naam=soort.naam,
                gevecht_genen=_met_variantie(soort.gevecht_basis),
                werk_genen=_met_variantie(soort.werk_basis),
            )
            session.add(huisdier)
            await session.commit()
            await session.refresh(huisdier)

        await interaction.response.send_message(
            f"{interaction.user.mention} heeft **{soort.naam}** gevangen! (pet #{huisdier.id})"
        )
        await send_log(
            self.bot,
            interaction.guild_id,
            "vangst",
            fmt_log("🟢", "vangst", f"{interaction.user.mention} ving **{soort.naam}** (pet #{huisdier.id})"),
        )

    @staticmethod
    async def _vind_soort(session, naam: str) -> PetSoort | list[PetSoort] | None:
        exact = await session.scalar(
            select(PetSoort).where(PetSoort.naam.ilike(naam))
        )
        if exact is not None:
            return exact

        kandidaten = (
            await session.execute(select(PetSoort).where(PetSoort.naam.ilike(f"%{naam}%")))
        ).scalars().all()
        if len(kandidaten) == 1:
            return kandidaten[0]
        if len(kandidaten) > 1:
            return kandidaten
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VangenCog(bot))
