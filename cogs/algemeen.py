import discord
from discord import app_commands
from discord.ext import commands

# Wat er nog op de planning staat, in tester-vriendelijke taal. Handmatig
# bijgehouden naast docs/dev-status.md ("Nog niet gebouwd"), dus bijwerken
# als daar iets bijkomt/wegvalt/klaar is.
TODO_ITEMS = [
    ("🛒 /craft-commando", "Een apart commando voor shop-items met een grondstof-recept (Slimme voerbak, Extra match token, etc.), met een preview van alle kosten (Chaos Coins + grondstoffen) vóórdat je bevestigt — i.p.v. de huidige `/shop`-foutmelding-bij-tekort."),
    ("📖 Critterdex", "Overzicht van alle pet-soorten met tier en element, en welke je al gevangen hebt. Max 10 per pagina, filterbaar op tier, standaard gesorteerd op tier + alfabet. Inclusief een `/info <soort>` losse lookup: gevecht/werk-stats, werkplek-voorkeur en hoeveel je er zelf al hebt."),
    ("❓ Mini-wiki", "Doorbladerbaar overzicht van alle commando's, met een dropdown per onderwerp."),
    ("🛠️ Admin panel", "Web-based paneel op casualchaos.nl om balans aan te passen zonder code-wijziging (geen Discord-commando)."),
    ("🐣 Fokken (lange termijn)", "Nieuwe pets kweken van je bestaande pets. Pas echt interessant vanaf 250 pet-soorten, dus staat achteraan."),
]

# Speler-gerichte commando's, met een korte uitleg per commando. Handmatig
# bijgehouden (geen introspectie op de command tree), dus bijwerken als er
# een nieuw commando bijkomt. Gebruikt door /commands en (indirect, via de
# aanwezigheid van dit overzicht) niet meer herhaald in elke /tests-oproep.
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
    ("/clan-aanmaken naam", "Richt een nieuwe clan op — je wordt automatisch lid. Werkplekken delen dan een eigen capaciteit-pool binnen je clan."),
    ("/clan-join naam", "Word lid van een bestaande clan."),
    ("/clan-verlaten", "Verlaat je huidige clan (ontbindt 'm automatisch als je het laatste lid was)."),
    ("/clan-ontbinden", "Ontbindt je clan meteen, alleen mogelijk voor de oprichter."),
    ("/clan-info [naam]", "Bekijk oprichter, ledenaantal, ledenlijst en totale werk-opbrengst van je eigen (of een andere) clan."),
    ("/clan-leaderboard", "Top 10 clans op cumulatieve werk-opbrengst."),
    ("/todo", "Bekijk wat er nog gepland staat voor Chaos Critters."),
    ("/spawn [tier] [naam]", "(admin) Forceer direct een spawn in dit kanaal, handig om niet op een natuurlijke spawn te hoeven wachten."),
    ("/give speler item [aantal]", "(admin) Geef jezelf of iemand anders een item, handig om spullen te testen zonder eerst Chaos Coins te verdienen."),
    ("/herstel [speler] [pet_id] [scope]", "(admin) Herstel honger + energie naar 100: 1 pet, een heel team, of alle pets — handig om niet steeds te hoeven wachten tijdens het testen."),
]


class AlgemeenCog(commands.Cog):
    """Algemene commando's die niet bij een specifiek spelsysteem horen."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check of de bot online is en meet de latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Pong! Latency: {round(self.bot.latency * 1000)}ms", ephemeral=False
        )

    @app_commands.command(name="todo", description="Bekijk wat er nog gepland staat voor Chaos Critters")
    async def todo(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🗺️ Chaos Critters — wat komt er nog aan?",
            description=(
                "Dit staat (ruwweg in deze volgorde) nog op de planning. "
                "(Nieuwe pet-soorten komen er trouwens doorlopend bij, dat stopt nooit echt.)"
            ),
            color=discord.Color.blurple(),
        )
        for titel, uitleg in TODO_ITEMS:
            embed.add_field(name=titel, value=uitleg, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="commands", description="Bekijk het volledige commando-overzicht")
    async def commands_overzicht(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="📋 Volledig commando-overzicht", color=discord.Color.blurple())
        for commando, uitleg in TEST_COMMANDOS:
            embed.add_field(name=commando, value=uitleg, inline=False)
        # Voor nu publiek zichtbaar (verzoek van de gebruiker), later evt. weer ephemeral maken.
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AlgemeenCog(bot))
