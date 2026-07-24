import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.werk import _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Item, Speler
from utils.checks import is_admin
from utils.discord_log import fmt_log, send_log, set_log_channel

# Wat er nieuw is sinds de vorige testronde, om testers direct naar de
# nieuwste features te wijzen i.p.v. dat ze het hele overzicht moeten
# doorspitten. Leegmaken/vervangen na elke aangekondigde testronde.
NIEUW_OM_TE_TESTEN = [
    (
        "🔄 Trading & 🕊️ /release zijn live",
        "Nieuw: `/trade speler` opent een paneel om een ruil samen te stellen — dropdowns voor wat "
        "je aanbiedt en terugvraagt (gevuld met jouw en hun items/pets), knoppen om aantal en Chaos "
        "Coins in te stellen. Daarna krijgt de ander een Accepteren/Weigeren-knop, en jij moet "
        "daarna nog één keer definitief bevestigen voor de ruil echt plaatsvindt (dubbele check "
        "tegen typefouten).\n\n"
        "Ook nieuw: `/release pet_id` om een pet vrij te laten in ruil voor Chaos Coins (schaalt met "
        "tier + level) plus een kleine kans op een bonus-grondstof. Eén bevestigingsknop, daarna is "
        "de pet echt weg.\n\n"
        "Wat te testen: item-voor-item en pet-voor-coins ruilen, een ruil weigeren/laten verlopen, "
        "en een paar pets vrijlaten (ook een werkende pet proberen — dat hoort geweigerd te worden).",
    ),
    (
        "🐾 2 nieuwe tiers + 99 nieuwe pet-soorten (totaal nu 125)",
        "Naast Common/Rare/Legendary bestaan nu ook **Uncommon** (groen) en **Epic** (paars). "
        "Sinds de vorige testronde zijn er in totaal 99 nieuwe pet-soorten bijgekomen, verdeeld over "
        "alle vijf tiers — gebruik `/vang` om ze tegen te komen, of vraag de volledige lijst op.",
    ),
]

# Speler-gerichte commando's om aan te kondigen bij een testronde, met een
# korte uitleg per commando. Handmatig bijgehouden (geen introspectie op de
# command tree), dus bijwerken als er een nieuw speler-commando bijkomt.
TEST_COMMANDOS = [
    ("/vang <naam>", "Vang de pet die net gespawnd is in dit kanaal (exacte naam, of het stuk vóór de haakjes, bijv. 'Hond')."),
    ("/lijst", "Bekijk al je pets: level+XP, werkstatus en honger/energie. Sorteerbaar via de knoppen."),
    ("/werk pet_id werkplek cyclus", "Zet een pet aan het werk voor grondstoffen + Chaos Coins + XP. `/werk pet_id` zonder extra opties haalt de opbrengst op zodra de shift klaar is (met eventuele level-up)."),
    ("/verzorg pet_id [item]", "Bekijk het level, XP en de stats van een pet, of voer 'm met voeding uit je inventaris om honger aan te vullen."),
    ("/slaap pet_id", "Laat een pet direct volledig uitrusten (energie naar 100), kost honger, max 1x per dag per pet."),
    ("/shop [item] [aantal]", "Bekijk de shop, of koop voeding/boosts/extra's met je Chaos Coins."),
    ("/items", "Bekijk je inventaris: alles wat je hebt gekocht of via werken hebt verdiend."),
    ("/team", "Stel je team van 3 pets samen voor gevechten."),
    ("/vecht [tegenstander] [inzet_coins] [inzet_item] [inzet_aantal]", "Vecht tegen een gesimuleerde tegenstander, of daag een speler uit (optioneel met inzet)."),
    ("/trade speler", "Open een paneel om een ruil samen te stellen: dropdowns voor wat je aanbiedt/terugvraagt (items/pets van jou en de ander), knoppen voor aantal + Chaos Coins."),
    ("/release pet_id", "Laat een pet vrij in ruil voor Chaos Coins (schaalt met tier + level) plus een kleine kans op een bonus-grondstof. Onomkeerbaar."),
    ("/spawn [tier] [naam]", "(admin) Forceer direct een spawn in dit kanaal, handig om niet op een natuurlijke spawn te hoeven wachten."),
    ("/give speler item [aantal]", "(admin) Geef jezelf of iemand anders een item, handig om spullen te testen zonder eerst Chaos Coins te verdienen."),
]


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
        name="tests", description="Stuur een @everyone-oproep met de huidige teststatus (admin)"
    )
    @app_commands.check(is_admin)
    async def tests(self, interaction: discord.Interaction) -> None:
        hoofd_embed = discord.Embed(
            title="🧪 Chaos Critters — klaar om getest te worden!",
            description=(
                "Er staat genoeg om mee te spelen. Dit is een vroege testversie, dus bugs en "
                "rare balans zijn te verwachten — laat het gewoon weten als je iets geks tegenkomt!"
            ),
            color=discord.Color.green(),
        )
        embeds = [hoofd_embed]

        if NIEUW_OM_TE_TESTEN:
            nieuw_embed = discord.Embed(title="🆕 Nieuw om te testen", color=discord.Color.gold())
            for titel, uitleg in NIEUW_OM_TE_TESTEN:
                nieuw_embed.add_field(name=titel, value=uitleg, inline=False)
            embeds.append(nieuw_embed)

        overzicht_embed = discord.Embed(title="📋 Volledig commando-overzicht", color=discord.Color.blurple())
        for commando, uitleg in TEST_COMMANDOS:
            overzicht_embed.add_field(name=commando, value=uitleg, inline=False)
        embeds.append(overzicht_embed)

        await interaction.response.send_message(
            "@everyone", embeds=embeds, allowed_mentions=discord.AllowedMentions(everyone=True)
        )
        await send_log(
            self.bot,
            interaction.guild_id,
            "main",
            fmt_log("🟡", "tests", f"{interaction.user.mention} stuurde een testoproep"),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
