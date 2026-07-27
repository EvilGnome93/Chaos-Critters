import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.werk import _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Huisdier, Item, PetStatus, Speler
from utils.checks import is_admin
from utils.discord_log import fmt_log, send_log, set_log_channel

# Wat er nieuw is sinds de vorige testronde, om testers direct naar de
# nieuwste features te wijzen i.p.v. dat ze het hele overzicht moeten
# doorspitten. Leegmaken/vervangen na elke aangekondigde testronde.
NIEUW_OM_TE_TESTEN = [
    (
        "🤝 /vecht: vriendschappelijke modus",
        "`/vecht [tegenstander] modus:vriendschappelijk` — altijd beschikbaar, ook als je dagelijkse "
        "ranked-pogingen op zijn. Geen MMR-verandering, geen Chaos Coins/XP-beloning, geen blessures, "
        "en geen inzet mogelijk. Verder identiek: tactieken, elementen, VS-afbeelding, PvE én PvP.\n\n"
        "Wat te testen: een vriendschappelijk gevecht starten nadat je ranked-pogingen op zijn, en "
        "checken dat je MMR/coins na afloop echt niet veranderd zijn.",
    ),
    (
        "👷 Werkplekken: gedeelde capaciteit + tweede grondstof",
        "Elke werkplek heeft nu een écht afgedwongen maximum aantal pets tegelijk, over ALLE spelers "
        "heen (niet meer per speler) — zit 'm vol, dan krijg je een duidelijke melding. Daarnaast heeft "
        "elke werkplek een kans op een zeldzame bonus-grondstof per voltooide shift (Fruit, Water, "
        "Spijker, Bladeren, Sterrenstof, Edelsteen). Bonus: de 'Mijnschacht'-werkplek stond al in het "
        "systeem maar ontbrak in `/werk`'s keuzelijst — kan nu ook echt gekozen worden.\n\n"
        "Wat te testen: met 2 accounts dezelfde (kleine) werkplek tegelijk vol proberen te zetten, en "
        "een paar shifts draaien om de bonus-grondstof een keer te zien opduiken.",
    ),
    (
        "🎒 Voerbakken & Zelfreinigend systeem hebben nu effect",
        "Deze shop-items deden nog niets — nu wel, en per pet uit te rusten met het nieuwe "
        "`/uitrusten pet_id item` (en `afkoppelen:True` om het weer los te halen). Voerbakken geven "
        "passief **honger** terug (Slimme vult het volledige verval aan, Simpele de helft); "
        "Zelfreinigend systeem laat **energie** ook buiten rust herstellen (bijv. tijdens werk). "
        "Slimme voerbak kost er ook 5x Schroot bij in de shop.\n\n"
        "Wat te testen: een voerbak uitrusten en kijken of honger niet (of trager) daalt, en "
        "Zelfreinigend systeem uitrusten en kijken of energie oploopt terwijl een pet aan het werk is "
        "(normaal gebeurt dat alleen in rust).",
    ),
    (
        "💰 Alle grondstoffen hebben nu een doel + Extra match token duurder",
        "De 11 grondstoffen die tot nu toe nutteloos waren, kosten nu wat in de shop: Water → Simpele "
        "voerbak, Sterrenstof → Zelfreinigend systeem, Groente → Graanvrije premium voeding, Fruit → "
        "Mysterie voedselzak, Algen → Vers vlees/vis, Takken → Naamkaartje, Bladeren → Focus drankje, "
        "Erts+Spijker → Werk-elixer, Maanschijnkristal+Edelsteen → Extra match token. **Extra match "
        "token ging ook van 50 naar 150 Chaos Coins** — was te makkelijk te herkopen van wat "
        "gevecht-winst, dat mag nu meer moeite kosten.\n\n"
        "Wat te testen: iets uit de shop kopen waar je de grondstof nog niet voor hebt (moet een "
        "duidelijke foutmelding geven met hoeveel je te kort komt), en dan met genoeg grondstof "
        "opnieuw proberen.",
    ),
]

# Speler-gerichte commando's om aan te kondigen bij een testronde, met een
# korte uitleg per commando. Handmatig bijgehouden (geen introspectie op de
# command tree), dus bijwerken als er een nieuw speler-commando bijkomt.
TEST_COMMANDOS = [
    ("/vang <naam>", "Vang de pet die net gespawnd is in dit kanaal (exacte naam, of het stuk vóór de haakjes, bijv. 'Hond')."),
    ("/lijst", "Bekijk al je pets: level+XP, werkstatus en honger/energie. Sorteerbaar via de knoppen."),
    ("/werk pet_id werkplek cyclus", "Zet een pet aan het werk voor grondstoffen + Chaos Coins + XP. `/werk pet_id` zonder extra opties haalt de opbrengst op zodra de shift klaar is (met eventuele level-up)."),
    ("/verzorg pet_id [item] [aantal]", "Bekijk het level, XP en de stats van een pet, of voer 'm met voeding uit je inventaris om honger aan te vullen (optioneel meerdere stuks in één keer)."),
    ("/slaap pet_id", "Laat een pet direct volledig uitrusten (energie naar 100), kost honger, max 1x per dag per pet."),
    ("/shop [item] [aantal]", "Bekijk de shop, of koop voeding/boosts/extra's met je Chaos Coins."),
    ("/items", "Bekijk je inventaris: alles wat je hebt gekocht of via werken hebt verdiend."),
    ("/uitrusten pet_id item [afkoppelen]", "Rust een pet uit met een voerbak of Zelfreinigend systeem uit je inventaris, of koppel 'm weer af (komt terug in je inventaris)."),
    ("/team", "Stel je team van 3 pets samen voor gevechten."),
    ("/vecht [tegenstander] [modus]", "Vecht tegen een gesimuleerde tegenstander, of daag een speler uit — bij een uitdaging opent een paneel om optioneel een item/Chaos Coins in te zetten. `modus:vriendschappelijk` telt niet mee voor ranked (geen MMR/beloning/blessures, altijd beschikbaar)."),
    ("/trade speler", "Open een paneel om een ruil samen te stellen: dropdowns voor wat je aanbiedt/terugvraagt (items/pets van jou en de ander), knoppen voor aantal + Chaos Coins."),
    ("/release pet_id", "Laat een pet vrij in ruil voor Chaos Coins (schaalt met tier + level) plus een kleine kans op een bonus-grondstof. Onomkeerbaar."),
    ("/spawn [tier] [naam]", "(admin) Forceer direct een spawn in dit kanaal, handig om niet op een natuurlijke spawn te hoeven wachten."),
    ("/give speler item [aantal]", "(admin) Geef jezelf of iemand anders een item, handig om spullen te testen zonder eerst Chaos Coins te verdienen."),
    ("/herstel [speler] [pet_id] [scope]", "(admin) Herstel honger + energie naar 100: 1 pet, een heel team, of alle pets — handig om niet steeds te hoeven wachten tijdens het testen."),
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
