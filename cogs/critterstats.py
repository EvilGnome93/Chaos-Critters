"""/critter-stats: persoonlijk statistieken-overzicht, zelfde idee als
Botv3's /mystats maar dan voor Chaos Critters (2026-07-30, verzoek van de
gebruiker). Hernoemd naar "critter-stats" i.p.v. "mystats" om verwarring
met Botv3's eigen /mystats in dezelfde server te voorkomen.

Twee tellers (shiften_voltooid, pvp/pve-winst/verlies) bestonden nog
nergens en zijn nieuw op Speler (db/models.py) — die starten voor
iedereen op 0 vanaf deze toevoeging, geen terugwerkende kracht (expliciet
akkoord van de gebruiker). Huidige pets, totaal-ooit-ontvangen en de
Critterdex-voortgang zijn wel met terugwerkende kracht correct, want die
worden afgeleid uit al bestaande data (Huisdier-rijen en
Speler.volgend_pet_nummer).
"""

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from db.engine import async_session
from db.models import Huisdier, PetSoort, Speler


class CritterStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="critter-stats", description="Bekijk je persoonlijke Chaos Critters-statistieken"
    )
    @app_commands.describe(speler="Bekijk de stats van een ander lid (optioneel)")
    async def critter_stats(
        self, interaction: discord.Interaction, speler: discord.Member | None = None
    ) -> None:
        doel = speler or interaction.user
        if doel.bot:
            await interaction.response.send_message("Bots hebben geen Chaos Critters-stats.", ephemeral=True)
            return

        async with async_session() as session:
            speler_obj = await session.get(Speler, doel.id)
            if speler_obj is None:
                await interaction.response.send_message(
                    f"{doel.mention} heeft nog niet gespeeld." if speler else "Je hebt nog niet gespeeld, vang eerst een pet met `/vang`.",
                    ephemeral=True,
                )
                return

            huidige_pets = await session.scalar(
                select(func.count()).select_from(Huisdier).where(Huisdier.eigenaar_id == doel.id)
            )
            unieke_soorten = await session.scalar(
                select(func.count(func.distinct(Huisdier.soort_id))).where(Huisdier.eigenaar_id == doel.id)
            )
            totaal_soorten = await session.scalar(select(func.count()).select_from(PetSoort))

        totaal_ooit = speler_obj.volgend_pet_nummer - 1
        critterdex_pct = round(unieke_soorten / totaal_soorten * 100, 1) if totaal_soorten else 0.0

        embed = discord.Embed(
            title=f"📊 Chaos Critters-stats van {doel.display_name}",
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=doel.display_avatar.url)
        embed.add_field(
            name="🐾 Pets",
            value=f"**{huidige_pets}** huidige\n**{totaal_ooit}** ooit ontvangen (vangst + ruil)",
            inline=True,
        )
        embed.add_field(
            name="📖 Critterdex",
            value=f"**{critterdex_pct}%**\n({unieke_soorten}/{totaal_soorten} soorten)",
            inline=True,
        )
        embed.add_field(
            name="👷 Werken",
            value=f"**{speler_obj.shiften_voltooid}** shifts voltooid",
            inline=True,
        )
        embed.add_field(
            name="⚔️ PvP (ranked)",
            value=f"**{speler_obj.pvp_gewonnen}** gewonnen / **{speler_obj.pvp_verloren}** verloren\nMMR: {speler_obj.mmr}",
            inline=True,
        )
        embed.add_field(
            name="🐺 PvE",
            value=f"**{speler_obj.pve_gewonnen}** gewonnen / **{speler_obj.pve_verloren}** verloren",
            inline=True,
        )
        embed.add_field(
            name="💰 Chaos Coins",
            value=f"**{speler_obj.currency}**",
            inline=True,
        )
        embed.set_footer(text="Meer info op: critters.casualchaos.nl")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CritterStatsCog(bot))
