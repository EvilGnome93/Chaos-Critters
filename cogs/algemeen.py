import discord
from discord import app_commands
from discord.ext import commands

# Wat er nog op de planning staat, in tester-vriendelijke taal. Handmatig
# bijgehouden naast docs/dev-status.md ("Nog niet gebouwd"), dus bijwerken
# als daar iets bijkomt/wegvalt/klaar is.
TODO_ITEMS = [
    ("🔄 Trading", "Items en pets ruilen met andere spelers."),
    ("🕊️ /release", "Pets vrijlaten in ruil voor items of Chaos Coins."),
    ("🌪️ Elementen & contra's", "Elk pet-soort krijgt een element (Grond/Water/Lucht/Vuur/Chaos) met contra's, zodat een Common met het juiste element een Rare kan verslaan."),
    ("👷 Werkplekken uitbreiden", "Gedeelde capaciteit-limiet per werkplek (over alle spelers heen) + een tweede grondstof per werkplek."),
    ("🏠 Automatisering-items", "Voerbakken en het zelfreinigend systeem krijgen hun beloofde passieve effect."),
    ("🐣 Fokken", "Nieuwe pets kweken van je bestaande pets."),
    ("⚖️ Herbalanceren", "Item-prijzen, XP-snelheden, werk-opbrengsten — alle placeholder-balanswaarden tegen het licht houden."),
    ("🏰 Gilde-systeem", "Gedeelde werkplekken en leaderboards per gilde."),
    ("📖 Critterdex", "Overzicht van alle pet-soorten met tier en element, en welke je al gevangen hebt. Max 10 per pagina, filterbaar op tier, standaard gesorteerd op tier + alfabet."),
    ("❓ Mini-wiki", "Doorbladerbaar overzicht van alle commando's, met een dropdown per onderwerp."),
    ("🛠️ Admin panel", "Web-based paneel op casualchaos.nl om balans aan te passen zonder code-wijziging (geen Discord-commando)."),
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AlgemeenCog(bot))
