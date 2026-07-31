import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.werk import _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Huisdier, Item, PetStatus, Speler
from utils.checks import is_admin
from utils.discord_log import fmt_log, send_log, set_log_channel


class AdminCog(commands.Cog):
    """Admin-commando's. Balans-instellingen zelf komen niet via Discord maar
    via een web-based admin panel op casualchaos.nl (brief sectie 14),
    nog te bouwen — dit is geen Discord-cog-taak."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setlog", description="Stel het logkanaal voor een categorie in")
    @app_commands.describe(
        categorie="De logcategorie",
        kanaal="Het tekstkanaal waar logs van deze categorie naartoe gestuurd worden",
    )
    @app_commands.choices(
        categorie=[
            app_commands.Choice(name="Main (bot start/fouten)", value="main"),
            app_commands.Choice(name="Vangst (catches + geforceerde spawns)", value="vangst"),
            app_commands.Choice(name="Werk (shifts starten/opbrengst)", value="werk"),
            app_commands.Choice(name="Gevecht (team/vecht-gerelateerd)", value="gevecht"),
            app_commands.Choice(name="Trade (ruilvoorstellen)", value="trade"),
            app_commands.Choice(name="Changelog-admin ('Voor admins & moderators'-gedeelte)", value="changelog-admin"),
        ]
    )
    @app_commands.check(is_admin)
    async def setlog(
        self, interaction: discord.Interaction, categorie: app_commands.Choice[str], kanaal: discord.TextChannel
    ) -> None:
        categorie = categorie.value
        await set_log_channel(interaction.guild_id, categorie, kanaal.id)
        await interaction.response.send_message(
            f"Logkanaal voor categorie **{categorie}** ingesteld op {kanaal.mention}.", ephemeral=True
        )
        await send_log(
            self.bot,
            interaction.guild_id,
            categorie,
            fmt_log("🟢", "setlog", f"Logcategorie **{categorie}** gekoppeld aan {kanaal.mention} door {interaction.user.mention}"),
        )

    async def _item_autocomplete(
        self, interaction: discord.Interaction, huidig: str
    ) -> list[app_commands.Choice[str]]:
        async with async_session() as session:
            namen = (await session.execute(select(Item.naam))).scalars().all()
        huidig = huidig.lower()
        return [app_commands.Choice(name=naam, value=naam) for naam in namen if huidig in naam.lower()][:25]

    @app_commands.command(
        name="give", description="Geef een speler een item (admin/test, tijdelijk tot de shop er is)"
    )
    @app_commands.describe(
        speler="Wie krijgt het item", item="Welk item", aantal="Hoeveel stuks (standaard 1)"
    )
    @app_commands.autocomplete(item=_item_autocomplete)
    @app_commands.check(is_admin)
    async def give(
        self, interaction: discord.Interaction, speler: discord.Member, item: str, aantal: int = 1
    ) -> None:
        if aantal < 1:
            await interaction.response.send_message("`aantal` moet minstens 1 zijn.", ephemeral=True)
            return

        async with async_session() as session:
            item_obj = await session.scalar(select(Item).where(Item.naam == item))
            if item_obj is None:
                await interaction.response.send_message(f"Onbekend item: **{item}**.", ephemeral=True)
                return

            if await session.get(Speler, speler.id) is None:
                session.add(Speler(discord_id=speler.id))

            await _voeg_toe_aan_inventaris(session, speler.id, item_obj.id, aantal)
            await session.commit()

        await interaction.response.send_message(
            f"✅ {speler.mention} kreeg {aantal}x **{item}**.", ephemeral=True
        )
        await send_log(
            self.bot,
            interaction.guild_id,
            "main",
            fmt_log(
                "🟡",
                "give",
                f"{interaction.user.mention} gaf {aantal}x **{item}** aan {speler.mention} (admin/test)",
            ),
        )

    @app_commands.command(
        name="herstel",
        description="(admin/test) Herstel honger + energie: 1 pet, een team, of alle pets van een speler",
    )
    @app_commands.describe(
        speler="Wiens pets herstellen (standaard jezelf)",
        pet_id="Herstel alleen deze pet (optioneel, negeert 'scope' als gezet)",
        scope="Herstel het hele team of alle pets (genegeerd als pet_id is gezet)",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Team", value="team"),
            app_commands.Choice(name="Alle pets", value="alles"),
        ]
    )
    @app_commands.check(is_admin)
    async def herstel(
        self,
        interaction: discord.Interaction,
        speler: discord.Member | None = None,
        pet_id: int | None = None,
        scope: app_commands.Choice[str] | None = None,
    ) -> None:
        doel = speler or interaction.user
        async with async_session() as session:
            if pet_id is not None:
                pet = await session.scalar(
                    select(Huisdier).where(Huisdier.eigenaar_id == doel.id, Huisdier.volgnummer == pet_id)
                )
                if pet is None:
                    await interaction.response.send_message(f"Geen pet #{pet_id} gevonden bij {doel.mention}.", ephemeral=True)
                    return
                pets = [pet]
            else:
                stmt = select(Huisdier).where(Huisdier.eigenaar_id == doel.id)
                if scope is not None and scope.value == "team":
                    stmt = stmt.where(Huisdier.status == PetStatus.team)
                pets = (await session.execute(stmt)).scalars().all()
                if not pets:
                    await interaction.response.send_message(f"Geen pets gevonden bij {doel.mention}.", ephemeral=True)
                    return

            for pet in pets:
                pet.honger = 100
                pet.energie = 100
            await session.commit()

        await interaction.response.send_message(
            f"✅ {len(pets)} pet(s) van {doel.mention} hersteld naar volle honger + energie.", ephemeral=True
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
