import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from db.engine import async_session
from db.models import Clan, Speler
from utils.discord_log import fmt_log, send_log

MAX_NAAM_LENGTE = 32
LEADERBOARD_TOP_N = 10


async def _haal_speler_op(session, discord_id: int) -> Speler:
    speler = await session.get(Speler, discord_id)
    if speler is None:
        speler = Speler(discord_id=discord_id)
        session.add(speler)
        await session.flush()
    return speler


async def _aantal_leden(session, clan_id: int) -> int:
    return await session.scalar(
        select(func.count()).select_from(Speler).where(Speler.clan_id == clan_id)
    )


class ClanCog(commands.Cog):
    """Clan-systeem: gedeelde werkplek-capaciteit per clan + leaderboard
    op werk-opbrengst. Zie projectbrief sectie 16 ("gilde", hier "clan"
    genoemd om een naam-botsing met discord.py's Guild-concept te
    voorkomen)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _clan_naam_autocomplete(
        self, interaction: discord.Interaction, huidig: str
    ) -> list[app_commands.Choice[str]]:
        async with async_session() as session:
            namen = (await session.execute(select(Clan.naam))).scalars().all()
        huidig = huidig.lower()
        return [app_commands.Choice(name=naam, value=naam) for naam in namen if huidig in naam.lower()][:25]

    @app_commands.command(name="clan-aanmaken", description="Richt een nieuwe clan op")
    @app_commands.describe(naam=f"Naam van de clan (max {MAX_NAAM_LENGTE} tekens)")
    async def clan_aanmaken(self, interaction: discord.Interaction, naam: str) -> None:
        naam = naam.strip()
        if not naam or len(naam) > MAX_NAAM_LENGTE:
            await interaction.response.send_message(
                f"Geef een naam van 1 t/m {MAX_NAAM_LENGTE} tekens.", ephemeral=True
            )
            return

        async with async_session() as session:
            speler = await _haal_speler_op(session, interaction.user.id)
            if speler.clan_id is not None:
                huidige = await session.get(Clan, speler.clan_id)
                await session.commit()
                await interaction.response.send_message(
                    f"Je zit al in clan **{huidige.naam}**. Verlaat die eerst met `/clan-verlaten`.",
                    ephemeral=True,
                )
                return

            clan = Clan(naam=naam, oprichter_id=interaction.user.id)
            session.add(clan)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                await interaction.response.send_message(
                    f"Er bestaat al een clan met de naam **{naam}**. Kies een andere naam.", ephemeral=True
                )
                return

            speler.clan_id = clan.id
            await session.commit()

        await interaction.response.send_message(
            f"🏰 Clan **{naam}** opgericht! Je bent automatisch lid. "
            "Werkplekken delen nu een aparte capaciteit-pool binnen je clan, los van spelers zonder clan.",
            ephemeral=False,
        )
        await send_log(
            self.bot, interaction.guild_id, "main",
            fmt_log("🟢", "clan", f"{interaction.user.mention} richtte clan **{naam}** op"),
        )

    @app_commands.command(name="clan-join", description="Word lid van een bestaande clan")
    @app_commands.describe(naam="Naam van de clan")
    @app_commands.autocomplete(naam=_clan_naam_autocomplete)
    async def clan_join(self, interaction: discord.Interaction, naam: str) -> None:
        async with async_session() as session:
            speler = await _haal_speler_op(session, interaction.user.id)
            if speler.clan_id is not None:
                huidige = await session.get(Clan, speler.clan_id)
                await session.commit()
                await interaction.response.send_message(
                    f"Je zit al in clan **{huidige.naam}**. Verlaat die eerst met `/clan-verlaten`.",
                    ephemeral=True,
                )
                return

            clan = await session.scalar(select(Clan).where(Clan.naam == naam))
            if clan is None:
                await session.commit()
                await interaction.response.send_message(f"Geen clan gevonden met de naam **{naam}**.", ephemeral=True)
                return

            speler.clan_id = clan.id
            await session.commit()

        await interaction.response.send_message(f"🏰 Je bent nu lid van clan **{naam}**!", ephemeral=False)
        await send_log(
            self.bot, interaction.guild_id, "main",
            fmt_log("🟢", "clan", f"{interaction.user.mention} werd lid van clan **{naam}**"),
        )

    @app_commands.command(name="clan-verlaten", description="Verlaat je huidige clan")
    async def clan_verlaten(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            speler = await _haal_speler_op(session, interaction.user.id)
            if speler.clan_id is None:
                await session.commit()
                await interaction.response.send_message("Je zit niet in een clan.", ephemeral=True)
                return

            clan = await session.get(Clan, speler.clan_id)
            speler.clan_id = None
            await session.flush()

            overige_leden = await _aantal_leden(session, clan.id)
            ontbonden = overige_leden == 0
            if ontbonden:
                await session.delete(clan)
            await session.commit()

        extra = " De clan had geen leden meer over en is automatisch ontbonden." if ontbonden else ""
        await interaction.response.send_message(f"Je hebt clan **{clan.naam}** verlaten.{extra}", ephemeral=False)
        await send_log(
            self.bot, interaction.guild_id, "main",
            fmt_log(
                "🔴", "clan",
                f"{interaction.user.mention} verliet clan **{clan.naam}**" + (" (automatisch ontbonden)" if ontbonden else ""),
            ),
        )

    @app_commands.command(name="clan-ontbinden", description="Ontbindt je clan (alleen de oprichter)")
    async def clan_ontbinden(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            speler = await _haal_speler_op(session, interaction.user.id)
            if speler.clan_id is None:
                await session.commit()
                await interaction.response.send_message("Je zit niet in een clan.", ephemeral=True)
                return

            clan = await session.get(Clan, speler.clan_id)
            if clan.oprichter_id != interaction.user.id:
                await session.commit()
                await interaction.response.send_message(
                    "Alleen de oprichter kan de clan ontbinden.", ephemeral=True
                )
                return

            await session.execute(
                Speler.__table__.update().where(Speler.clan_id == clan.id).values(clan_id=None)
            )
            naam = clan.naam
            await session.delete(clan)
            await session.commit()

        await interaction.response.send_message(f"🏰 Clan **{naam}** is ontbonden.", ephemeral=False)
        await send_log(
            self.bot, interaction.guild_id, "main",
            fmt_log("🔴", "clan", f"{interaction.user.mention} ontbond clan **{naam}**"),
        )

    @app_commands.command(name="clan-info", description="Bekijk info over een clan (standaard: je eigen clan)")
    @app_commands.describe(naam="Naam van de clan (optioneel, standaard je eigen clan)")
    @app_commands.autocomplete(naam=_clan_naam_autocomplete)
    async def clan_info(self, interaction: discord.Interaction, naam: str | None = None) -> None:
        async with async_session() as session:
            if naam is None:
                speler = await session.get(Speler, interaction.user.id)
                if speler is None or speler.clan_id is None:
                    await interaction.response.send_message(
                        "Je zit niet in een clan. Geef een `naam` op om een andere clan te bekijken.",
                        ephemeral=True,
                    )
                    return
                clan = await session.get(Clan, speler.clan_id)
            else:
                clan = await session.scalar(select(Clan).where(Clan.naam == naam))
                if clan is None:
                    await interaction.response.send_message(f"Geen clan gevonden met de naam **{naam}**.", ephemeral=True)
                    return

            leden = (await session.execute(select(Speler.discord_id).where(Speler.clan_id == clan.id))).scalars().all()

        embed = discord.Embed(title=f"🏰 {clan.naam}", color=discord.Color.gold())
        embed.add_field(name="Oprichter", value=f"<@{clan.oprichter_id}>", inline=True)
        embed.add_field(name="Leden", value=str(len(leden)), inline=True)
        embed.add_field(name="Totale werk-opbrengst", value=f"{clan.totale_werk_opbrengst} Chaos Coins", inline=True)
        if leden:
            embed.add_field(
                name="Ledenlijst", value=", ".join(f"<@{lid}>" for lid in leden), inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="clan-leaderboard", description="Bekijk de top-clans op werk-opbrengst")
    async def clan_leaderboard(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            clans = (
                await session.execute(
                    select(Clan).order_by(Clan.totale_werk_opbrengst.desc()).limit(LEADERBOARD_TOP_N)
                )
            ).scalars().all()

        if not clans:
            await interaction.response.send_message("Er bestaan nog geen clans.", ephemeral=True)
            return

        medailles = ["🥇", "🥈", "🥉"]
        beschrijving = "\n".join(
            f"{medailles[i] if i < len(medailles) else f'{i + 1}.'} **{clan.naam}** — "
            f"{clan.totale_werk_opbrengst} Chaos Coins"
            for i, clan in enumerate(clans)
        )
        embed = discord.Embed(title="🏆 Clan-leaderboard", description=beschrijving, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClanCog(bot))
