"""Generiek logsysteem naar Discord-kanalen, per server en categorie.

Patroon overgenomen van Botv3: een kanaal wordt per (guild, categorie)
ingesteld via /setlog en opgeslagen in de database. send_log() zoekt dat
kanaal op en stuurt een embed, met de kleur afgeleid van de eerste emoji
in de content (🟢 succes, 🔴 fout, anders geel).
"""

import logging

import discord
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.engine import async_session
from db.models import LogChannel

log = logging.getLogger("gamename")

KLEUR_SUCCES = 0x57F287
KLEUR_FOUT = 0xED4245
KLEUR_OVERIG = 0xFEE75C


def fmt_log(dot: str, module: str, message: str) -> str:
    return f"{dot} `[{module}]` {message}"


async def set_log_channel(guild_id: int, categorie: str, channel_id: int) -> None:
    async with async_session() as session:
        stmt = insert(LogChannel).values(guild_id=guild_id, categorie=categorie, channel_id=channel_id)
        stmt = stmt.on_conflict_do_update(
            index_elements=["guild_id", "categorie"], set_={"channel_id": channel_id}
        )
        await session.execute(stmt)
        await session.commit()


async def get_log_channel(guild_id: int, categorie: str) -> int | None:
    async with async_session() as session:
        return await session.scalar(
            select(LogChannel.channel_id).where(
                LogChannel.guild_id == guild_id, LogChannel.categorie == categorie
            )
        )


async def send_log(
    client: discord.Client,
    guild_id: int | None,
    categorie: str,
    content: str,
    *,
    author: dict | None = None,
    plain: bool = False,
) -> None:
    if guild_id is None:
        return

    channel_id = await get_log_channel(guild_id, categorie)
    if channel_id is None:
        return

    try:
        channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    except discord.HTTPException as e:
        log.warning("Kon logkanaal %s niet vinden (categorie %s): %s", channel_id, categorie, e)
        return

    try:
        if plain:
            await channel.send(content)
            return

        if content.startswith("🟢"):
            kleur = KLEUR_SUCCES
        elif content.startswith("🔴"):
            kleur = KLEUR_FOUT
        else:
            kleur = KLEUR_OVERIG

        embed = discord.Embed(description=content, color=kleur, timestamp=discord.utils.utcnow())
        if author:
            embed.set_author(**author)
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.warning("Kon logbericht niet versturen naar kanaal %s (categorie %s): %s", channel_id, categorie, e)
