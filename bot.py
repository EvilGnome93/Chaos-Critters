import asyncio
import logging
import subprocess
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils.discord_log import fmt_log, send_log

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chaos_critters")
log.setLevel(logging.DEBUG if config.ENVIRONMENT == "dev" else logging.INFO)

COGS = (
    "cogs.algemeen",
    "cogs.vangen",
    "cogs.verzorging",
    "cogs.werk",
    "cogs.gevechten",
    "cogs.trading",
    "cogs.fokken",
    "cogs.admin",
)

intents = discord.Intents.default()
intents.message_content = True


class LoggingCommandTree(app_commands.CommandTree):
    """Logt elke command-fout met volledige traceback. Alleen bedoeld voor
    dev-debugging; productie-events (catches, mijlpalen, ...) krijgen later
    een eigen, curated logsysteem zoals beschreven in sectie 15 van de brief."""

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        naam = interaction.command.qualified_name if interaction.command else "onbekend"
        log.exception("Fout bij /%s door %s", naam, interaction.user, exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Er ging iets mis bij het uitvoeren van dit commando.", ephemeral=True
            )
        await send_log(
            self.client,
            interaction.guild_id,
            "main",
            fmt_log("🔴", "error", f"/{naam} door {interaction.user.mention} gaf een fout: `{error}`"),
        )


class GameNameBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents, tree_cls=LoggingCommandTree)

    async def setup_hook(self) -> None:
        for cog in COGS:
            await self.load_extension(cog)
            log.info("Cog geladen: %s", cog)

        if config.ENVIRONMENT == "dev":
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("%d command(s) gesynct naar dev-guild %s", len(synced), config.DEV_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("%d command(s) globaal gesynct", len(synced))

    async def on_ready(self) -> None:
        log.info("Ingelogd als %s (id: %s)", self.user, self.user.id)
        for guild in self.guilds:
            await send_log(self, guild.id, "main", fmt_log("🟢", "bot", f"{self.user} is online ({config.ENVIRONMENT})"))

    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command
    ) -> None:
        if config.ENVIRONMENT != "dev":
            return
        guild = interaction.guild.name if interaction.guild else "DM"
        kanaal = getattr(interaction.channel, "name", interaction.channel_id)
        log.info("/%s uitgevoerd door %s in %s/#%s", command.qualified_name, interaction.user, guild, kanaal)


def _draai_migraties() -> None:
    """Voert pending Alembic-migraties uit tegen de huidige database, vóór de bot
    start. Draait als apart subprocess (niet via de alembic Python-API) omdat
    migrations/env.py zelf al asyncio.run() aanroept, wat niet kan vanuit een
    al draaiende event loop. Voorkomt dat een deploy start met een schema dat
    achterloopt op de code (zie het laatste_verzorging_op-incident)."""
    alembic_ini = Path(__file__).resolve().parent / "alembic.ini"
    log.info("Migraties uitvoeren (alembic upgrade head)...")
    resultaat = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if resultaat.returncode != 0:
        log.error("Migraties mislukt:\n%s", resultaat.stdout + resultaat.stderr)
        raise RuntimeError("Alembic-migratie mislukt, bot start niet op met een verouderd schema.")
    log.info("Migraties op orde.\n%s", resultaat.stdout.strip())


async def main() -> None:
    bot = GameNameBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    _draai_migraties()
    asyncio.run(main())
