import asyncio
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from db.engine import async_session
from db.models import Huisdier, Instelling, PetSoort, Speler, SpawnKanaal, Tier
from utils.discord_log import fmt_log, send_log

log = logging.getLogger("gamename")

GENEN_VARIANTIE = 0.10  # +/- 10% rond de soort-basiswaarde
TIJD_TRIGGER_MIN_SECONDEN = 2 * 3600
TIJD_TRIGGER_MAX_SECONDEN = 4 * 3600

TIER_KLEUREN = {1: 0x95A5A6, 3: 0x3498DB, 5: 0xF1C40F}  # Common grijs, Rare blauw, Legendary goud
PLACEHOLDER_AFBEELDING = "https://placehold.co/400x400/2c2f33/ffffff/png?text=%3F"  # tot er echte pet-art is


def _met_variantie(basis: float) -> float:
    factor = 1 + random.uniform(-GENEN_VARIANTIE, GENEN_VARIANTIE)
    return round(max(1.0, float(basis) * factor), 2)


def _primaire_naam(naam: str) -> str:
    """'Hond (Zwerfhond)' -> 'Hond'; namen zonder haakjes blijven ongewijzigd."""
    return naam.split(" (")[0]


def _matcht(naam: str, soort: PetSoort) -> bool:
    naam = naam.strip().lower()
    return naam == soort.naam.lower() or naam == _primaire_naam(soort.naam).lower()


async def _kies_random_soort(
    session, *, tier_id: int | None = None, naam: str | None = None
) -> tuple[PetSoort, Tier]:
    if naam:
        soort = await session.scalar(select(PetSoort).where(PetSoort.naam.ilike(naam.strip())))
        if soort is None:
            alle = (await session.execute(select(PetSoort))).scalars().all()
            soort = next(
                (s for s in alle if _primaire_naam(s.naam).lower() == naam.strip().lower()), None
            )
        if soort is None:
            raise ValueError(f"Onbekende pet-soort: '{naam}'.")
        tier = await session.get(Tier, soort.tier_id)
        return soort, tier

    tiers_query = select(Tier)
    if tier_id is not None:
        tiers_query = tiers_query.where(Tier.id == tier_id)
    tiers = (await session.execute(tiers_query)).scalars().all()
    if not tiers:
        raise ValueError(f"Onbekend tier: {tier_id}.")

    tier = random.choices(tiers, weights=[float(t.spawnkans) for t in tiers], k=1)[0]
    soorten = (
        (await session.execute(select(PetSoort).where(PetSoort.tier_id == tier.id))).scalars().all()
    )
    return random.choice(soorten), tier


async def _nieuwe_drempel() -> int:
    async with async_session() as session:
        minimum = await session.scalar(
            select(Instelling.waarde).where(Instelling.sleutel == "spawn_interval_min_berichten")
        )
        maximum = await session.scalar(
            select(Instelling.waarde).where(Instelling.sleutel == "spawn_interval_max_berichten")
        )
    return random.randint(int(minimum or 25), int(maximum or 40))


async def _laad_spawn_kanaal_ids() -> list[int]:
    async with async_session() as session:
        return list((await session.execute(select(SpawnKanaal.channel_id))).scalars().all())


async def _voeg_spawn_kanaal_toe(guild_id: int, channel_id: int) -> None:
    async with async_session() as session:
        stmt = insert(SpawnKanaal).values(guild_id=guild_id, channel_id=channel_id)
        stmt = stmt.on_conflict_do_nothing(index_elements=["guild_id", "channel_id"])
        await session.execute(stmt)
        await session.commit()


async def _verwijder_spawn_kanaal(channel_id: int) -> None:
    async with async_session() as session:
        await session.execute(delete(SpawnKanaal).where(SpawnKanaal.channel_id == channel_id))
        await session.commit()


class VangenCog(commands.Cog):
    """Spawns en het vangen van pets. Zie projectbrief sectie 7 en 8.

    Per kanaal is er hooguit één actieve spawn tegelijk: een nieuwe spawn
    (activiteit- of tijd-trigger) vervangt een niet-gevangen oude spawn.
    Er is geen timeout, alleen vervanging.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.actieve_spawns: dict[int, PetSoort] = {}
        self.berichten_tellers: dict[int, int] = {}
        self.drempels: dict[int, int] = {}
        self.spawn_kanaal_ids: set[int] = set()
        self.tijd_taken: dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        for channel_id in await _laad_spawn_kanaal_ids():
            self.spawn_kanaal_ids.add(channel_id)
            self._start_tijd_trigger(channel_id)

    async def cog_unload(self) -> None:
        for taak in self.tijd_taken.values():
            taak.cancel()

    def _start_tijd_trigger(self, channel_id: int) -> None:
        if channel_id in self.tijd_taken:
            return
        self.tijd_taken[channel_id] = asyncio.create_task(self._tijd_trigger_loop(channel_id))

    def _stop_tijd_trigger(self, channel_id: int) -> None:
        taak = self.tijd_taken.pop(channel_id, None)
        if taak:
            taak.cancel()

    async def _tijd_trigger_loop(self, channel_id: int) -> None:
        try:
            while True:
                await asyncio.sleep(random.uniform(TIJD_TRIGGER_MIN_SECONDEN, TIJD_TRIGGER_MAX_SECONDEN))
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(channel_id)
                    except discord.HTTPException:
                        log.warning("Kon spawn-kanaal %s niet vinden voor tijd-trigger", channel_id)
                        continue
                await self._spawn(channel)
        except asyncio.CancelledError:
            pass

    async def _spawn(
        self, channel: discord.abc.Messageable, *, tier_id: int | None = None, naam: str | None = None
    ) -> None:
        async with async_session() as session:
            soort, tier = await _kies_random_soort(session, tier_id=tier_id, naam=naam)
        await self._stuur_spawn_embed(channel, soort, tier)

    async def _stuur_spawn_embed(self, channel: discord.abc.Messageable, soort: PetSoort, tier: Tier) -> None:
        self.actieve_spawns[channel.id] = soort

        embed = discord.Embed(
            title=f"🐾 Een wilde {soort.naam} verschijnt!",
            description=f"Typ `/vang {_primaire_naam(soort.naam)}` om 'm te vangen.",
            color=TIER_KLEUREN.get(tier.id, discord.Color.default().value),
        )
        embed.set_footer(text=f"Tier: {tier.naam}")
        embed.set_image(url=soort.afbeelding_url or PLACEHOLDER_AFBEELDING)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.channel.id not in self.spawn_kanaal_ids:
            return

        aantal = self.berichten_tellers.get(message.channel.id, 0) + 1
        drempel = self.drempels.get(message.channel.id)
        if drempel is None:
            drempel = await _nieuwe_drempel()
            self.drempels[message.channel.id] = drempel

        if aantal >= drempel:
            self.berichten_tellers[message.channel.id] = 0
            self.drempels[message.channel.id] = await _nieuwe_drempel()
            await self._spawn(message.channel)
        else:
            self.berichten_tellers[message.channel.id] = aantal

    @app_commands.command(name="vang", description="Vang de pet die nu gespawnd is in dit kanaal")
    @app_commands.describe(naam="De naam van de gespawnde pet-soort")
    async def vang(self, interaction: discord.Interaction, naam: str) -> None:
        soort = self.actieve_spawns.pop(interaction.channel_id, None)
        if soort is None:
            await interaction.response.send_message(
                "Er is nu niets te vangen in dit kanaal.", ephemeral=True
            )
            return

        if not _matcht(naam, soort):
            self.actieve_spawns[interaction.channel_id] = soort
            await interaction.response.send_message(
                "Dat is niet de juiste naam voor de huidige spawn in dit kanaal.", ephemeral=True
            )
            return

        async with async_session() as session:
            speler = await session.get(Speler, interaction.user.id)
            if speler is None:
                speler = Speler(discord_id=interaction.user.id)
                session.add(speler)

            huisdier = Huisdier(
                eigenaar_id=interaction.user.id,
                soort_id=soort.id,
                tier_id=soort.tier_id,
                naam=soort.naam,
                gevecht_genen=_met_variantie(soort.gevecht_basis),
                werk_genen=_met_variantie(soort.werk_basis),
            )
            session.add(huisdier)
            await session.commit()
            await session.refresh(huisdier)

        await interaction.response.send_message(
            f"{interaction.user.mention} heeft **{soort.naam}** gevangen! (pet #{huisdier.id})"
        )
        await send_log(
            self.bot,
            interaction.guild_id,
            "vangst",
            fmt_log("🟢", "vangst", f"{interaction.user.mention} ving **{soort.naam}** (pet #{huisdier.id})"),
        )

    @app_commands.command(
        name="setspawnkanaal", description="Voeg een kanaal toe waar pets automatisch kunnen spawnen"
    )
    @app_commands.describe(kanaal="Het kanaal (standaard: dit kanaal)")
    @app_commands.default_permissions(administrator=True)
    async def setspawnkanaal(
        self, interaction: discord.Interaction, kanaal: discord.TextChannel | None = None
    ) -> None:
        kanaal = kanaal or interaction.channel
        await _voeg_spawn_kanaal_toe(interaction.guild_id, kanaal.id)
        self.spawn_kanaal_ids.add(kanaal.id)
        self._start_tijd_trigger(kanaal.id)
        await interaction.response.send_message(f"{kanaal.mention} is nu een spawn-kanaal.", ephemeral=True)

    @app_commands.command(name="verwijderspawnkanaal", description="Verwijder een kanaal als spawn-kanaal")
    @app_commands.describe(kanaal="Het kanaal (standaard: dit kanaal)")
    @app_commands.default_permissions(administrator=True)
    async def verwijderspawnkanaal(
        self, interaction: discord.Interaction, kanaal: discord.TextChannel | None = None
    ) -> None:
        kanaal = kanaal or interaction.channel
        await _verwijder_spawn_kanaal(kanaal.id)
        self.spawn_kanaal_ids.discard(kanaal.id)
        self._stop_tijd_trigger(kanaal.id)
        self.actieve_spawns.pop(kanaal.id, None)
        await interaction.response.send_message(
            f"{kanaal.mention} is geen spawn-kanaal meer.", ephemeral=True
        )

    async def _naam_autocomplete(
        self, interaction: discord.Interaction, huidig: str
    ) -> list[app_commands.Choice[str]]:
        async with async_session() as session:
            namen = (await session.execute(select(PetSoort.naam))).scalars().all()
        huidig = huidig.lower()
        return [
            app_commands.Choice(name=naam, value=naam) for naam in namen if huidig in naam.lower()
        ][:25]

    @app_commands.command(name="spawn", description="Forceer direct een spawn in dit kanaal (admin/test)")
    @app_commands.describe(
        tier="Beperk de spawn tot dit tier (optioneel, genegeerd als naam is ingevuld)",
        naam="Forceer een specifieke pet-soort (optioneel)",
    )
    @app_commands.choices(
        tier=[
            app_commands.Choice(name="Common", value=1),
            app_commands.Choice(name="Rare", value=3),
            app_commands.Choice(name="Legendary", value=5),
        ]
    )
    @app_commands.autocomplete(naam=_naam_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def spawn(
        self,
        interaction: discord.Interaction,
        tier: app_commands.Choice[int] | None = None,
        naam: str | None = None,
    ) -> None:
        try:
            async with async_session() as session:
                soort, gekozen_tier = await _kies_random_soort(
                    session, tier_id=tier.value if tier else None, naam=naam
                )
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        await interaction.response.send_message("Spawn geforceerd.", ephemeral=True)
        await self._stuur_spawn_embed(interaction.channel, soort, gekozen_tier)
        await send_log(
            self.bot,
            interaction.guild_id,
            "vangst",
            fmt_log(
                "🟡",
                "spawn",
                f"{interaction.user.mention} forceerde handmatig een spawn ({soort.naam}) in {interaction.channel.mention}",
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VangenCog(bot))
