import discord
from discord import app_commands
from discord.ext import commands


class AdminCog(commands.Cog):
    """Admin-commando's voor balans en instellingen. Zie projectbrief sectie 14."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="instelling", description="Bekijk of wijzig een balans-instelling")
    @app_commands.describe(sleutel="De naam van de instelling", waarde="De nieuwe waarde (optioneel)")
    @app_commands.default_permissions(administrator=True)
    async def instelling(
        self, interaction: discord.Interaction, sleutel: str, waarde: str | None = None
    ) -> None:
        await interaction.response.send_message(
            f"Instellingenbeheer voor '{sleutel}' is nog niet geïmplementeerd.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
