import discord
from discord import app_commands
from discord.ext import commands


class VerzorgingCog(commands.Cog):
    """Voeding, stats en shop-items voor huisdieren. Zie projectbrief sectie 5 en 6."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="verzorg", description="Bekijk of verzorg de stats van een pet")
    @app_commands.describe(pet_id="Het ID van je pet")
    async def verzorg(self, interaction: discord.Interaction, pet_id: int) -> None:
        await interaction.response.send_message(
            f"Verzorgingssysteem voor pet #{pet_id} is nog niet geïmplementeerd.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VerzorgingCog(bot))
