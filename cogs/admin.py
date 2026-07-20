import discord
from discord import app_commands
from discord.ext import commands

from utils.discord_log import fmt_log, send_log, set_log_channel


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

    @app_commands.command(name="setlog", description="Stel het logkanaal voor een categorie in")
    @app_commands.describe(
        categorie="Vrije naam voor de logcategorie, bijv. 'main' of 'vangst'",
        kanaal="Het tekstkanaal waar logs van deze categorie naartoe gestuurd worden",
    )
    @app_commands.default_permissions(administrator=True)
    async def setlog(
        self, interaction: discord.Interaction, categorie: str, kanaal: discord.TextChannel
    ) -> None:
        categorie = categorie.strip().lower()
        await set_log_channel(interaction.guild_id, categorie, kanaal.id)
        await interaction.response.send_message(
            f"Logkanaal voor categorie **{categorie}** ingesteld op {kanaal.mention}.", ephemeral=True
        )
        await send_log(
            self.bot,
            interaction.guild_id,
            categorie,
            fmt_log("🟢", "setlog", f"Logcategorie **{categorie}** gekoppeld aan {kanaal.mention} door {interaction.user.mention}"),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
