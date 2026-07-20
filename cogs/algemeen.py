import discord
from discord import app_commands
from discord.ext import commands


class AlgemeenCog(commands.Cog):
    """Algemene commando's die niet bij een specifiek spelsysteem horen."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check of de bot online is en meet de latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Pong! Latency: {round(self.bot.latency * 1000)}ms", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AlgemeenCog(bot))
