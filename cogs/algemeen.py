import discord
from discord import app_commands
from discord.ext import commands

# Wat er nog op de planning staat, in tester-vriendelijke taal. Handmatig
# bijgehouden naast docs/dev-status.md ("Nog niet gebouwd"), dus bijwerken
# als daar iets bijkomt/wegvalt/klaar is.
TODO_ITEMS = [
    ("⚔️ Team & gevechten", "`/team` en `/vecht` — tactische 3-tegen-3 gevechten tussen teams. Kan ook XP opleveren."),
    ("🐣 Fokken", "Nieuwe pets kweken van je bestaande pets."),
    ("🔄 Trading", "Items en pets ruilen met andere spelers."),
    ("🛠️ Admin panel", "`/instelling` live laten werken, zodat balans aan te passen is zonder code-wijziging."),
    ("👷 Werkplek-capaciteit", "Een limiet op hoeveel pets tegelijk op 1 werkplek kunnen werken."),
    ("🏰 Gilde-systeem", "Gedeelde werkplekken en leaderboards per gilde."),
    ("❓ /help mini-wiki", "Doorbladerbaar overzicht van alle commando's, met een dropdown per onderwerp."),
    ("🏠 Automatisering-items", "Voerbakken en het zelfreinigend systeem krijgen hun beloofde passieve effect."),
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
            description="Dit staat (ruwweg in deze volgorde) nog op de planning:",
            color=discord.Color.blurple(),
        )
        for titel, uitleg in TODO_ITEMS:
            embed.add_field(name=titel, value=uitleg, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AlgemeenCog(bot))
