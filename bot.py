import asyncio
import logging

import discord
from discord.ext import commands

import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gamename")

COGS = (
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


class GameNameBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)

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


async def main() -> None:
    bot = GameNameBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
