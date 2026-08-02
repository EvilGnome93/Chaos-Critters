import asyncio
import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

import config
from db.engine import async_session
from db.models import ActieveSpawn, Huisdier, Instelling, PetSoort, Speler, SpawnKanaal, Tier
from utils.checks import is_admin
from utils.discord_log import fmt_log, send_log

log = logging.getLogger("chaos_critters")

GENEN_VARIANTIE = 0.10  # +/- 10% rond de soort-basiswaarde

if config.ENVIRONMENT == "dev":
    TIJD_TRIGGER_MIN_SECONDEN = TIJD_TRIGGER_MAX_SECONDEN = 30 * 60
else:
    # 2026-07-29, verzoek van de gebruiker: was 2-4 uur, verlaagd naar 1-2 uur.
    TIJD_TRIGGER_MIN_SECONDEN = 1 * 3600
    TIJD_TRIGGER_MAX_SECONDEN = 2 * 3600

# 2026-07-29, verzoek van de gebruiker: geen tijd-gebaseerde spawns tussen
# 23:00 en 07:00 Amsterdamse tijd (zomer-/wintertijd via ZoneInfo, dus geen
# handmatige UTC-offset-correctie nodig). Geldt bewust alleen in productie —
# in dev zou dit 's nachts gewoon kunnen blijven testen hinderen. De
# activiteit-gebaseerde trigger (on_message) blijft te allen tijde actief,
# op expliciet verzoek: "spawnen door chats is prima".
STILLE_PERIODE_START_UUR = 23
STILLE_PERIODE_EIND_UUR = 7
AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")


def _in_stille_periode() -> bool:
    if config.ENVIRONMENT == "dev":
        return False
    uur = datetime.now(AMSTERDAM_TZ).hour
    return uur >= STILLE_PERIODE_START_UUR or uur < STILLE_PERIODE_EIND_UUR

TIER_KLEUREN = {
    1: 0x95A5A6,  # Common grijs
    2: 0x2ECC71,  # Uncommon groen
    3: 0x3498DB,  # Rare blauw
    4: 0x9B59B6,  # Epic paars
    5: 0xF1C40F,  # Legendary goud
}
PLACEHOLDER_AFBEELDING = "https://placehold.co/400x400/2c2f33/ffffff/png?text=%3F"  # tot er echte pet-art is

# Tier-emoji, ook gebruikt in cogs/verzorging.py:/lijst. Was eerder alleen
# {1, 3, 5} — Uncommon/Epic vielen dan terug op het Common-icoontje
# (2026-07-27, gevonden terwijl aan /info gewerkt werd, los meegenomen).
TIER_EMOJI = {1: "⚪", 2: "🟢", 3: "🔵", 4: "🟣", 5: "🟡"}


def _met_variantie(basis: float) -> float:
    factor = 1 + random.uniform(-GENEN_VARIANTIE, GENEN_VARIANTIE)
    return round(max(1.0, float(basis) * factor), 2)


def _primaire_naam(naam: str) -> str:
    """'Hond (Zwerfhond)' -> 'Hond'; namen zonder haakjes blijven ongewijzigd."""
    return naam.split(" (")[0]


def _spawn_embed(soort: PetSoort, tier: Tier) -> discord.Embed:
    embed = discord.Embed(
        title=f"🐾 Een wilde {soort.naam} verschijnt!",
        description=f"Typ `/vang {_primaire_naam(soort.naam)}` om 'm te vangen.",
        color=TIER_KLEUREN.get(tier.id, discord.Color.default().value),
    )
    embed.set_footer(text=f"Tier: {tier.naam} - critters.casualchaos.nl")
    embed.set_image(url=soort.afbeelding_url or PLACEHOLDER_AFBEELDING)
    return embed


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
    if not soorten:
        # Kan alleen als er een tier bestaat zonder pet-soorten (bijv. net
        # toegevoegd, nog niet geseed). Zonder deze check zou random.choice
        # met een IndexError crashen i.p.v. een leesbare melding te geven.
        raise ValueError(f"Tier '{tier.naam}' heeft nog geen pet-soorten om te spawnen.")
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
        # Een niet meer bestaand spawn-kanaal hoort ook geen actieve spawn
        # meer te hebben; anders blijft die rij eeuwig staan.
        await session.execute(delete(ActieveSpawn).where(ActieveSpawn.channel_id == channel_id))
        await session.commit()


# ── Actieve spawn bewaren (2026-07-30, verzoek van de gebruiker) ────────────
# De actieve spawn per kanaal stond alleen in het geheugen, dus een redeploy
# maakte elke lopende spawn onvangbaar: de embed bleef staan maar /vang zei
# "geen spawn actief". Nu spiegelt de database de in-memory dict, zodat een
# herstart 'm gewoon weer oppakt.


async def _bewaar_actieve_spawn(channel_id: int, guild_id: int, soort_id: int, message_id: int) -> None:
    async with async_session() as session:
        stmt = insert(ActieveSpawn).values(
            channel_id=channel_id, guild_id=guild_id, soort_id=soort_id, message_id=message_id
        )
        # Eén actieve spawn per kanaal: een nieuwe vervangt de oude.
        stmt = stmt.on_conflict_do_update(
            index_elements=["channel_id"],
            set_={"soort_id": soort_id, "message_id": message_id, "guild_id": guild_id},
        )
        await session.execute(stmt)
        await session.commit()


async def _wis_actieve_spawn(channel_id: int) -> None:
    async with async_session() as session:
        await session.execute(delete(ActieveSpawn).where(ActieveSpawn.channel_id == channel_id))
        await session.commit()


async def _laad_actieve_spawns() -> dict[int, tuple[PetSoort, int]]:
    """channel_id -> (soort, message_id), voor het herstellen na een herstart."""
    async with async_session() as session:
        rijen = (
            await session.execute(select(ActieveSpawn, PetSoort).join(PetSoort, ActieveSpawn.soort_id == PetSoort.id))
        ).all()
        session.expunge_all()
    return {spawn.channel_id: (soort, spawn.message_id) for spawn, soort in rijen}


class VangenCog(commands.Cog):
    """Spawns en het vangen van pets. Zie projectbrief sectie 7 en 8.

    Per kanaal is er hooguit één actieve spawn tegelijk: een nieuwe spawn
    (activiteit- of tijd-trigger) vervangt een niet-gevangen oude spawn.
    Er is geen timeout, alleen vervanging.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # channel_id -> (soort, message_id). Bewust het message-ID i.p.v. een
        # discord.Message: na een herstart hebben we alleen het ID uit de
        # database, en om de embed bij te werken is een PartialMessage genoeg.
        self.actieve_spawns: dict[int, tuple[PetSoort, int]] = {}
        self.berichten_tellers: dict[int, int] = {}
        self.drempels: dict[int, int] = {}
        self.spawn_kanaal_ids: set[int] = set()
        self.tijd_taken: dict[int, asyncio.Task] = {}
        self.spawn_locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self) -> None:
        for channel_id in await _laad_spawn_kanaal_ids():
            self.spawn_kanaal_ids.add(channel_id)
            self._start_tijd_trigger(channel_id)

        # Spawns van vóór de herstart weer oppakken, zodat een redeploy geen
        # onvangbare pet achterlaat (2026-07-30, verzoek van de gebruiker).
        self.actieve_spawns = await _laad_actieve_spawns()
        if self.actieve_spawns:
            log.info("%d actieve spawn(s) hersteld na herstart", len(self.actieve_spawns))

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
                if _in_stille_periode():
                    continue
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

    def _lock_voor(self, channel_id: int) -> asyncio.Lock:
        lock = self.spawn_locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self.spawn_locks[channel_id] = lock
        return lock

    async def _stuur_spawn_embed(self, channel: discord.abc.Messageable, soort: PetSoort, tier: Tier) -> None:
        async with self._lock_voor(channel.id):
            vorige = self.actieve_spawns.get(channel.id)
            if vorige is not None:
                oude_soort, oud_message_id = vorige
                await self._markeer_verlopen(channel.id, oud_message_id, oude_soort)

            embed = _spawn_embed(soort, tier)
            bericht = await channel.send(embed=embed)
            self.actieve_spawns[channel.id] = (soort, bericht.id)
            guild_id = getattr(getattr(channel, "guild", None), "id", 0)
            await _bewaar_actieve_spawn(channel.id, guild_id, soort.id, bericht.id)

    def _partial_bericht(self, channel_id: int, message_id: int) -> discord.PartialMessage | None:
        """Genoeg om een bestaand spawn-bericht bij te werken, zonder het
        eerst op te halen. Na een herstart hebben we alleen het ID, dus dit
        is ook het enige wat dan werkt."""
        kanaal = self.bot.get_channel(channel_id)
        if kanaal is None or not hasattr(kanaal, "get_partial_message"):
            return None
        return kanaal.get_partial_message(message_id)

    async def _werk_spawn_embed_bij(
        self, channel_id: int, message_id: int, soort: PetSoort, titel: str, beschrijving: str, wat: str
    ) -> None:
        """Bouwt de embed opnieuw op i.p.v. de bestaande aan te passen: na een
        herstart hebben we geen `discord.Message` meer met `.embeds`, alleen
        een ID. Alles wat we nodig hebben (naam, tier-kleur, afbeelding) staat
        toch al op de soort."""
        bericht = self._partial_bericht(channel_id, message_id)
        if bericht is None:
            log.warning("Kon kanaal %s niet vinden om spawn-bericht bij te werken (%s)", channel_id, wat)
            return

        embed = discord.Embed(
            title=titel,
            description=beschrijving,
            color=TIER_KLEUREN.get(soort.tier_id, discord.Color.default().value),
        )
        embed.set_image(url=soort.afbeelding_url or PLACEHOLDER_AFBEELDING)
        try:
            await bericht.edit(embed=embed)
        except discord.HTTPException as e:
            log.warning("Kon spawn-bericht niet bijwerken (%s): %s", wat, e)

    async def _markeer_verlopen(self, channel_id: int, message_id: int, soort: PetSoort) -> None:
        await self._werk_spawn_embed_bij(
            channel_id, message_id, soort,
            f"💨 {soort.naam} is ontsnapt!",
            "Niemand ving deze op tijd, er is een nieuwe spawn verschenen.",
            "verlopen",
        )

    async def _markeer_gevangen(
        self, channel_id: int, message_id: int, soort: PetSoort, vanger: discord.abc.User, pet_id: int
    ) -> None:
        await self._werk_spawn_embed_bij(
            channel_id, message_id, soort,
            f"✅ {soort.naam} gevangen!",
            f"Gevangen door {vanger.mention} (pet #{pet_id})",
            "gevangen",
        )

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
        actief = self.actieve_spawns.pop(interaction.channel_id, None)
        if actief is None:
            await interaction.response.send_message(
                "Er is nu niets te vangen in dit kanaal.", ephemeral=True
            )
            return
        soort, message_id = actief

        if not _matcht(naam, soort):
            self.actieve_spawns[interaction.channel_id] = actief
            await interaction.response.send_message(
                "Dat is niet de juiste naam voor de huidige spawn in dit kanaal.", ephemeral=True
            )
            return

        async with async_session() as session:
            speler = await session.get(Speler, interaction.user.id)
            if speler is None:
                speler = Speler(discord_id=interaction.user.id, volgend_pet_nummer=1)
                session.add(speler)

            volgnummer = speler.volgend_pet_nummer
            speler.volgend_pet_nummer = volgnummer + 1

            huisdier = Huisdier(
                volgnummer=volgnummer,
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

        await _wis_actieve_spawn(interaction.channel_id)
        await self._markeer_gevangen(
            interaction.channel_id, message_id, soort, interaction.user, huisdier.volgnummer
        )
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()
        await send_log(
            self.bot,
            interaction.guild_id,
            "vangst",
            fmt_log("🟢", "vangst", f"{interaction.user.mention} ving **{soort.naam}** (pet #{huisdier.volgnummer})"),
        )

    @app_commands.command(
        name="setspawnkanaal", description="Voeg een kanaal toe waar pets automatisch kunnen spawnen"
    )
    @app_commands.describe(kanaal="Het kanaal (standaard: dit kanaal)")
    @app_commands.check(is_admin)
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
    @app_commands.check(is_admin)
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
            app_commands.Choice(name="Uncommon", value=2),
            app_commands.Choice(name="Rare", value=3),
            app_commands.Choice(name="Epic", value=4),
            app_commands.Choice(name="Legendary", value=5),
        ]
    )
    @app_commands.autocomplete(naam=_naam_autocomplete)
    @app_commands.check(is_admin)
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
