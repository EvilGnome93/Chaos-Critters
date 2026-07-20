import discord
from discord import app_commands
from discord.ext import commands


class FokkenCog(commands.Cog):
    """Breeding tussen twee pets. Zie projectbrief sectie 10."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="fok", description="Fok twee van je pets met elkaar")
    @app_commands.describe(pet_id_1="Het ID van de eerste pet", pet_id_2="Het ID van de tweede pet")
    async def fok(self, interaction: discord.Interaction, pet_id_1: int, pet_id_2: int) -> None:
        await interaction.response.send_message(
            f"Fokken van pet #{pet_id_1} en #{pet_id_2} is nog niet geïmplementeerd.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FokkenCog(bot))
