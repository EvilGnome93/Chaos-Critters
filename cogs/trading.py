import discord
from discord import app_commands
from discord.ext import commands


class TradingCog(commands.Cog):
    """Ruilen en verkopen tussen spelers. Zie projectbrief sectie 11."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="trade", description="Stel een ruil voor aan een andere speler")
    @app_commands.describe(speler="De speler waarmee je wilt ruilen")
    async def trade(self, interaction: discord.Interaction, speler: discord.Member) -> None:
        await interaction.response.send_message(
            f"Trading met {speler.mention} is nog niet geïmplementeerd.", ephemeral=True
        )

    @app_commands.command(name="verkoop", description="Verkoop een pet op de marktplaats")
    @app_commands.describe(pet_id="Het ID van de pet die je wilt verkopen")
    async def verkoop(self, interaction: discord.Interaction, pet_id: int) -> None:
        await interaction.response.send_message(
            f"Marktplaats-verkoop voor pet #{pet_id} is nog niet geïmplementeerd.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TradingCog(bot))
