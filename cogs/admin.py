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
        "🐾 10 nieuwe pet-soorten (totaal nu 100)",
        "Krekel, Vlinder, Worm, Kakkerlak, Vlo (Common), Stinkdier, Kolibrie, Buidelrat (Uncommon), "
        "Axolotl (Rare), Struisvogel (Epic). Toegevoegd om de vangkans per soort tussen tiers "
        "gelijkmatiger te maken. Deze 10 hebben nog geen eigen afbeelding (placeholder).",
    ),
    (
        "🆕 2 nieuwe tiers: Uncommon & Epic",
        "Naast Common/Rare/Legendary bestaan nu ook **Uncommon** (groen) en **Epic** (paars), "
        "qua zeldzaamheid tussen hun buren in. 30 nieuwe soorten om te vangen: Hamster, Varken, Ezel, "
        "Wezel, Bunzing, Zeepaardje, Kraanvogel, Alpaca, Lama, Kwartel, Parkiet, Faisant, Stokstaartje, "
        "Chaos Kangoeroe, Chaos Toekan (Uncommon), IJsbeer, Luipaard, Poema, Krokodil, Anaconda, "
        "Hyena, Gier, Walrus, Zeekoe, Haai, Veelvraat, Gorilla, Nijlpaard, Chaos Octopus, "
        "Chaos Stier (Epic).",
    ),
    (
        "🐾 20 nieuwe pet-soorten (totaal was 60)",
        "Fret, Schaap, Geit, Kikker, Pauw, Goudvis, Muis, Mus, Chaos Spin (Common), Kraai, Pelikaan, "
        "Flamingo, Stekelvarken, Kwal, Zwaan, Chaos Kameleon (Rare), Tijger, Panter, Neushoorn, "
        "Chaos Giraffe (Legendary).",
    ),
    (
        "🐾 14 nieuwe pet-soorten (totaal was 40)",
        "Duif, Cavia, Krab, Mier, Chaos Mol, Specht, Slak (Common), Das, Zeehond, Havik, Vleermuis, "
        "Chaos Reiger (Rare), Beer, Chaos Olifant (Legendary). Nieuw: de **Mijnschacht**-werkplek "
        "(6e werkplek, levert Erts), gekoppeld aan Das en Chaos Mol.",
    ),
    (
        "🧹 Database is gereset",
        "Alle spelers, pets en inventarissen zijn gewist voor deze testronde — iedereen begint "
        "weer bij nul. **Ook `/setlog` en `/setspawnkanaal` moeten opnieuw ingesteld worden** "
        "door een admin, die stonden ook op nul.",
    ),
    (
        "🔢 Pet-nummers zijn nu per speler",
        "Je pets heten nu #1, #2, #3, ... geteld vanaf jouw eigen eerste vangst, i.p.v. een "
        "doorlopend nummer over alle spelers heen (dus geen 'pet #1546' meer na een week spelen).",
    ),
    (
        "⚔️ Team & gevechten",
        "Nieuw: `/team` om een team van 3 pets samen te stellen, en `/vecht` om te vechten — "
        "tegen een gesimuleerde tegenstander (op basis van je MMR), of een echte speler "
        "uitdagen met optioneel een inzet (Chaos Coins en/of een item).\n\n"
        "Een gevecht is een best-of-3: je pet 1 vs hun pet 1, dan pet 2, dan pet 3. Per matchup "
        "kies je een tactiek (🗡️ Aggressief / ⚖️ Gebalanceerd / 🛡️ Voorzichtig, elk een ander "
        "risicoprofiel) of je rent weg (🏃, telt als verlies). Een verslagen pet krijgt 0 energie "
        "en is even geblesseerd (niet inzetbaar).",
    ),
    (
        "⚔️ Wat te testen bij gevechten",
        "1. `/team` — stel een team van 3 pets samen via de dropdown.\n"
        "2. `/vecht` zonder tegenstander — vecht tegen een gesimuleerde tegenstander, probeer "
        "verschillende tactieken en ook een keer wegrennen.\n"
        "3. `/vecht tegenstander:@iemand inzet_coins:10` — daag iemand uit met een inzet, laat "
        "die persoon accepteren, check dat de winnaar de pot krijgt.\n"
        "4. Check `/lijst` na een verlies — is de verslagen pet echt geblesseerd/niet inzetbaar?\n"
        "5. Check of je MMR en Chaos Coins kloppen na afloop, en of je dagelijkse ranked-pogingen "
        "opraken na een paar gevechten (`ranked_gratis_per_dag`).",
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
