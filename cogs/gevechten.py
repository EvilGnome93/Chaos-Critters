import discord
from discord import app_commands
from discord.ext import commands


class GevechtenCog(commands.Cog):
    """Teams samenstellen en ranked matches. Zie projectbrief sectie 12."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="team", description="Bekijk of stel je team van 3 pets samen")
    async def team(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Teamsamenstelling is nog niet geïmplementeerd.", ephemeral=True
        )

    @app_commands.command(name="vecht", description="Start een ranked match met je huidige team")
    async def vecht(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Ranked matches zijn nog niet geïmplementeerd.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GevechtenCog(bot))
