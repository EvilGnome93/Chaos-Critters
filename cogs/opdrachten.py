"""`/opdrachten` — je drie dagelijkse opdrachten en hun voortgang.

De logica zit in utils/opdrachten.py; deze cog is puur de weergave. Bewust
één commando zonder subcommando's: opdrachten worden lui toegewezen bij de
eerste actie van de dag, dus er valt niets te "starten" of "claimen" — de
beloning wordt automatisch uitbetaald zodra een opdracht vol is.
"""

from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from db.engine import async_session
from utils import balans, opdrachten

VOORTGANGSBALK_BREEDTE = 10


def _balk(voortgang: int, doel: int) -> str:
    vol = round(VOORTGANGSBALK_BREEDTE * voortgang / doel) if doel else VOORTGANGSBALK_BREEDTE
    return "█" * vol + "░" * (VOORTGANGSBALK_BREEDTE - vol)


def _volgende_reset() -> datetime:
    """Het eerstvolgende resetmoment, in Amsterdamse tijd."""
    reset_uur = balans.get_int("opdracht_reset_uur", 4)
    nu = datetime.now(opdrachten.AMSTERDAM_TZ)
    vandaag = nu.replace(hour=reset_uur, minute=0, second=0, microsecond=0)
    return vandaag if vandaag > nu else vandaag + timedelta(days=1)


class OpdrachtenCog(commands.Cog):
    """Dagelijkse opdrachten (2026-08-05, verzoek van de gebruiker)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="opdrachten", description="Bekijk je dagelijkse opdrachten en hoe ver je bent"
    )
    async def opdrachten_bekijken(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            mijn = await opdrachten.zorg_voor_opdrachten(session, interaction.user.id)
            # zorg_voor_opdrachten() commit bewust niet zelf (aanroepers zitten
            # normaal midden in een transactie), maar hier zijn we de enige
            # schrijver — zonder dit zouden verse opdrachten weer verdwijnen.
            await session.commit()
            regels = []
            for opdracht in sorted(mijn, key=lambda o: o.sleutel):
                type_ = opdrachten.TYPES.get(opdracht.sleutel)
                emoji = type_.emoji if type_ else "•"
                label = type_.tekst(opdracht.doel) if type_ else opdracht.sleutel
                if opdracht.voltooid_op is not None:
                    regels.append(f"{emoji} ~~{label}~~ ✅ **+{opdracht.beloning}** Chaos Coins")
                else:
                    regels.append(
                        f"{emoji} **{label}**\n"
                        f"`{_balk(opdracht.voortgang, opdracht.doel)}` "
                        f"{opdracht.voortgang}/{opdracht.doel} — +{opdracht.beloning} Chaos Coins"
                    )

            alles_af = all(o.voltooid_op is not None for o in mijn)
            bonus = opdrachten.bonus_alle_drie()

        embed = discord.Embed(
            title="📋 Je dagelijkse opdrachten",
            description="\n\n".join(regels),
            color=discord.Color.green() if alles_af else discord.Color.blurple(),
        )
        embed.add_field(
            name="Bonus",
            value=(
                f"🎉 Alle drie af! Bonus van **{bonus}** Chaos Coins is uitbetaald."
                if alles_af
                else f"Rond alle drie af voor **{bonus}** extra Chaos Coins."
            ),
            inline=False,
        )
        # Relatieve Discord-timestamp: telt vanzelf af en staat voor iedereen
        # in de eigen tijdzone, dus geen "04:00 (Nederlandse tijd)"-uitleg nodig.
        embed.set_footer(text="Beloningen worden automatisch uitbetaald zodra een opdracht vol is.")
        embed.add_field(
            name="Nieuwe opdrachten",
            value=f"<t:{int(_volgende_reset().timestamp())}:R>",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OpdrachtenCog(bot))
