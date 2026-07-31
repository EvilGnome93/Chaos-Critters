import discord
from discord import app_commands
from discord.ext import commands

# Speler-gerichte commando's, met een korte uitleg per commando. Handmatig
# bijgehouden (geen introspectie op de command tree), dus bijwerken als er
# een nieuw commando bijkomt. Gegroepeerd per categorie i.p.v. één platte
# lijst: Discord staat max. 25 velden per embed toe (2026-07-29, /commands
# crashte met "Must be 25 or fewer" toen dit de 26e werd), dus /commands
# stuurt nu één embed per categorie i.p.v. één embed met alle commando's.
TEST_COMMANDOS_PER_CATEGORIE = [
    ("🐾 Vangen & pets", [
        ("/vang <naam>", "Vang de pet die net gespawnd is in dit kanaal (exacte naam, of het stuk vóór de haakjes, bijv. 'Hond')."),
        ("/lijst", "Bekijk al je pets: level+XP, werkstatus en honger/energie. Sorteerbaar via de knoppen."),
        ("/critterdex", "Bekijk alle pet-soorten (gepagineerd), filterbaar op tier en element, met per soort of en hoe vaak je 'm al gevangen hebt."),
        ("/info soort", "Bekijk gevecht/werk-stats (als Laag/Gemiddeld/Hoog/...), tier, element, werkplek-voorkeur en je eigen vangst-aantal van één specifieke pet-soort."),
        ("/critter-stats [speler]", "Bekijk je eigen (of iemand anders z'n) statistieken: pets gevangen, Critterdex-voortgang, shifts voltooid, PvP/PvE-winst en -verlies, en Chaos Coins."),
    ]),
    ("👷 Werken & verzorgen", [
        ("/werk pet_id werkplek cyclus", "Zet een pet aan het werk voor grondstoffen + Chaos Coins + XP. `/werk pet_id` zonder extra opties haalt de opbrengst op zodra de shift klaar is (met eventuele level-up)."),
        ("/verzorg pet_id [item] [aantal]", "Bekijk het level, XP en de stats van een pet, of voer 'm met voeding uit je inventaris om honger aan te vullen (optioneel meerdere stuks in één keer)."),
        ("/slaap pet_id", "Laat een pet direct volledig uitrusten (energie naar 100), kost honger, max 1x per dag per pet."),
        ("/shop [item] [aantal]", "Bekijk de shop, of koop voeding/boosts/extra's met je Chaos Coins."),
        ("/craft [item] [aantal]", "Bekijk of maak een item met een grondstof-recept (bijv. Slimme voerbak) — toont alle kosten (coins + grondstoffen) vooraf, met een Bevestigen-knop."),
        ("/craft-lijst", "Snel overzicht van alle craftbare items en hun kosten, zonder de rest van /craft."),
        ("/items", "Bekijk je inventaris: alles wat je hebt gekocht of via werken hebt verdiend."),
        ("/uitrusten pet_id item [afkoppelen]", "Rust een pet uit met een voerbak of Zelfreinigend systeem uit je inventaris, of koppel 'm weer af (komt terug in je inventaris)."),
    ]),
    ("⚔️ Vechten & ruilen", [
        ("/team", "Stel je team van 3 pets samen voor gevechten."),
        ("/vecht [tegenstander] [modus]", "Vecht tegen een gesimuleerde tegenstander, of daag een speler uit — bij een uitdaging opent een paneel om optioneel een item/Chaos Coins in te zetten. `modus:vriendschappelijk` telt niet mee voor ranked (geen MMR/beloning/blessures, altijd beschikbaar)."),
        ("/trade speler", "Open een paneel om een ruil samen te stellen: dropdowns voor wat je aanbiedt/terugvraagt (items/pets van jou en de ander), knoppen voor aantal + Chaos Coins."),
        ("/release pet_id", "Laat een pet vrij in ruil voor Chaos Coins (schaalt met tier + level) plus een kleine kans op een bonus-grondstof. Onomkeerbaar."),
    ]),
    ("🏰 Clans", [
        ("/clan-aanmaken naam", "Richt een nieuwe clan op — je wordt automatisch lid. Werkplekken delen dan een eigen capaciteit-pool binnen je clan."),
        ("/clan-join naam", "Word lid van een bestaande clan."),
        ("/clan-verlaten", "Verlaat je huidige clan (ontbindt 'm automatisch als je het laatste lid was; draagt het oprichterschap over als jij dat was)."),
        ("/clan-ontbinden", "Ontbindt je clan meteen, alleen mogelijk voor de oprichter."),
        ("/clan-info [naam]", "Bekijk oprichter, ledenaantal, ledenlijst en totale werk-opbrengst van je eigen (of een andere) clan."),
        ("/clan-leaderboard", "Top 10 clans op cumulatieve werk-opbrengst."),
    ]),
    ("ℹ️ Overig", [
        ("/wiki", "Blader door uitleg van hoe de spelmechanieken werken (vangen, elementen, verzorgen, werken, vechten, ranked, PvP, traden, clans, leveling), gegroepeerd per onderwerp."),
    ]),
    ("🔧 Admin", [
        ("/spawn [tier] [naam]", "Forceer direct een spawn in dit kanaal, handig om niet op een natuurlijke spawn te hoeven wachten."),
        ("/give speler item [aantal]", "Geef jezelf of iemand anders een item, handig om spullen te testen zonder eerst Chaos Coins te verdienen."),
        ("/herstel [speler] [pet_id] [scope]", "Herstel honger + energie naar 100: 1 pet, een heel team, of alle pets — handig om niet steeds te hoeven wachten tijdens het testen."),
        ("/changelog [tag-rol]", "Stel een changelog-aankondiging samen voor review; na goedkeuring wordt 'm gepost in het aankondigingskanaal."),
    ]),
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

    @app_commands.command(name="commands", description="Bekijk het volledige commando-overzicht")
    async def commands_overzicht(self, interaction: discord.Interaction) -> None:
        # Eén embed per categorie i.p.v. alles in één: Discord staat max. 25
        # velden per embed toe, en dat platte totaal is die grens al gepasseerd.
        embeds = []
        for i, (categorie, commandos) in enumerate(TEST_COMMANDOS_PER_CATEGORIE):
            embed = discord.Embed(
                title="📋 Volledig commando-overzicht" if i == 0 else None,
                description=categorie,
                color=discord.Color.blurple(),
            )
            for commando, uitleg in commandos:
                embed.add_field(name=commando, value=uitleg, inline=False)
            embeds.append(embed)
        # Max. 10 embeds per bericht (Discord-limiet); ruim voldoende voor de huidige 6 categorieën.
        await interaction.response.send_message(embeds=embeds, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AlgemeenCog(bot))
