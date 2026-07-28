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
        "⚖️ Balans-audit: sneller levelen, receptkosten fors omhoog",
        "Levelen gaat nu ~19x sneller (doel: ~2-4 weken naar level 50 i.p.v. maanden). Korte/lange "
        "werk-shifts zijn ook een stuk aantrekkelijker geworden t.o.v. overnacht (was 4,5x zo "
        "efficiënt per uur, nu nog maar 1,3x). Daartegenover staan **fors hogere receptkosten**: elk "
        "shop-item met een recept (Slimme voerbak, Zelfreinigend systeem, Extra match token, "
        "Naamkaartje, etc.) vereist nu **2 verschillende grondstoffen** i.p.v. 1, in flink hogere "
        "hoeveelheden — Slimme voerbak kost bijv. nu 40x Schroot + 20x Erts (was 5x Schroot). Ook: "
        "Nachtwacht-capaciteit ging van 1 naar 2, en max. pets tegelijk aan het werk per speler van 3 "
        "naar 2 (voorkomt dat 1 speler een hele werkplek solo kan opvullen).\n\n"
        "Wat te testen: laat een pet werken en kijk of 'ie merkbaar sneller levelt dan je gewend was; "
        "probeer een duur shop-item (bijv. Slimme voerbak) te kopen zonder genoeg grondstoffen en "
        "check de foutmelding; probeer met een 3e pet te werken terwijl je er al 2 hebt lopen (moet nu "
        "geweigerd worden).",
    ),
    (
        "🛠️ Nieuw: /craft voor recept-items",
        "Items met een grondstof-recept (Slimme voerbak, Zelfreinigend systeem, Extra match token, "
        "etc.) koop je voortaan makkelijker via `/craft item aantal` — toont alle kosten (Chaos Coins "
        "+ elke grondstof, met ✅/❌ of je genoeg hebt) in een preview, met een Bevestigen-knop die "
        "uitgeschakeld is zolang je iets te kort komt. `/craft` zonder item geeft een overzicht van "
        "alle recept-items. `/shop` werkt voor deze items ook nog gewoon (met de bestaande "
        "foutmelding-bij-tekort).\n\n"
        "Wat te testen: `/craft item:Simpele voerbak` proberen zonder genoeg Water/Fruit (Bevestigen "
        "moet uitgeschakeld zijn), dan grondstoffen verzamelen en opnieuw `/craft` draaien om te "
        "bevestigen.",
    ),
    (
        "🏰 Nieuw: clan-systeem",
        "`/clan-aanmaken naam`, `/clan-join naam`, `/clan-verlaten`, `/clan-ontbinden` (alleen de "
        "oprichter), `/clan-info [naam]` en `/clan-leaderboard`. Elke clan krijgt zijn **eigen "
        "capaciteit-pool per werkplek**, los van andere clans en van spelers zonder clan — dus meer "
        "clans betekent meer totale werkplek-ruimte in de server. Het leaderboard telt de cumulatieve "
        "Chaos Coins-opbrengst van alle `/werk`-shifts van de leden samen bij elkaar op.\n\n"
        "Wat te testen: met 2 accounts dezelfde clan joinen en dezelfde (kleine) werkplek tegelijk "
        "vol proberen te zetten, en met een 3e (clanloos of andere clan) account checken dat die "
        "gewoon nog kan werken.",
    ),
    (
        "📖 Nieuw: /critterdex en /info",
        "`/critterdex` toont alle pet-soorten (gepagineerd, 10 per pagina), met dropdown-filters voor "
        "tier én element, en of/hoe vaak je elke soort al gevangen hebt. `/info soort` (autocomplete) "
        "geeft de details van één specifieke soort: gevecht/werk-stats als woord (Laag/Gemiddeld/"
        "Hoog/...), werkplek-voorkeur en je eigen vangst-aantal.\n\n"
        "Wat te testen: filter in `/critterdex` op een tier + element tegelijk en check of de lijst "
        "klopt, en vergelijk `/info` van een soort die je al gevangen hebt met een die je nog niet "
        "hebt.",
    ),
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
                "rare balans zijn te verwachten — laat het gewoon weten als je iets geks tegenkomt!\n\n"
                "Gebruik `/commands` voor het volledige commando-overzicht."
            ),
            color=discord.Color.green(),
        )
        embeds = [hoofd_embed]

        if NIEUW_OM_TE_TESTEN:
            nieuw_embed = discord.Embed(title="🆕 Nieuw om te testen", color=discord.Color.gold())
            for titel, uitleg in NIEUW_OM_TE_TESTEN:
                nieuw_embed.add_field(name=titel, value=uitleg, inline=False)
            embeds.append(nieuw_embed)

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
