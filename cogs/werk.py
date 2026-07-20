import discord
from discord import app_commands
from discord.ext import commands


class WerkCog(commands.Cog):
    """De passieve werk-laag op werkplekken. Zie projectbrief sectie 4 en 6."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="werk", description="Wijs een pet toe aan een werkplek of haal opbrengst op")
    @app_commands.describe(pet_id="Het ID van je pet")
    async def werk(self, interaction: discord.Interaction, pet_id: int) -> None:
        await interaction.response.send_message(
            f"Werk-laag voor pet #{pet_id} is nog niet geïmplementeerd.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WerkCog(bot))
