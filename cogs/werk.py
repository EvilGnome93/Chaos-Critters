import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, PetStatus, Speler, Werkplek
from utils.discord_log import fmt_log, send_log

log = logging.getLogger("gamename")

CURRENCY_PER_GRONDSTOF = 2  # placeholder balans-waarde, later bij te stellen
NOTIFICATIE_CHECK_INTERVAL_SECONDEN = 120


@dataclass(frozen=True)
class Cyclus:
    label: str
    duur_uren: float
    energie_kost: int
    output_multiplier: float


WERK_CYCLI = {
    "korte": Cyclus("Korte shift", 2, 20, 1.0),
    "lange": Cyclus("Lange shift", 6, 50, 2.8),
    "overnacht": Cyclus("Overnacht", 10, 70, 4.5),
}


def _nu() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _voeg_toe_aan_inventaris(session, speler_id: int, item_id: int, aantal: int) -> None:
    stmt = insert(InventarisItem).values(speler_id=speler_id, item_id=item_id, aantal=aantal)
    stmt = stmt.on_conflict_do_update(
        index_elements=["speler_id", "item_id"],
        set_={"aantal": InventarisItem.aantal + aantal},
    )
    await session.execute(stmt)


class WerkCog(commands.Cog):
    """De passieve werk-laag op werkplekken. Zie projectbrief sectie 4 en 6.

    Werkplek-capaciteit wordt nog niet afgedwongen (staat als TODO voor
    zodra werkplekken gedeeld worden, sectie 16). Energie wordt volledig
    afgetrokken bij start van de shift, niet geleidelijk.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.notificatie_taak: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self.notificatie_taak = asyncio.create_task(self._notificatie_loop())

    async def cog_unload(self) -> None:
        if self.notificatie_taak:
            self.notificatie_taak.cancel()

    async def _notificatie_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(NOTIFICATIE_CHECK_INTERVAL_SECONDEN)
                await self._stuur_klaar_notificaties()
        except asyncio.CancelledError:
            pass

    async def _stuur_klaar_notificaties(self) -> None:
        async with async_session() as session:
            kandidaten = (
                await session.execute(
                    select(Huisdier).where(
                        Huisdier.status == PetStatus.werkplek,
                        Huisdier.werk_notificatie_verstuurd.is_(False),
                    )
                )
            ).scalars().all()

            for huisdier in kandidaten:
                cyclus_info = WERK_CYCLI[huisdier.werk_cyclus]
                if _nu() - huisdier.werk_gestart_op < timedelta(hours=cyclus_info.duur_uren):
                    continue

                huisdier.werk_notificatie_verstuurd = True
                if huisdier.werk_kanaal_id is None:
                    continue
                try:
                    kanaal = self.bot.get_channel(huisdier.werk_kanaal_id) or await self.bot.fetch_channel(
                        huisdier.werk_kanaal_id
                    )
                    await kanaal.send(
                        f"🧺 <@{huisdier.eigenaar_id}> **{huisdier.naam}** is klaar met werken! "
                        f"Gebruik `/werk pet_id:{huisdier.id}` om de opbrengst op te halen."
                    )
                except discord.HTTPException as e:
                    log.warning(
                        "Kon werk-notificatie niet sturen naar kanaal %s: %s", huisdier.werk_kanaal_id, e
                    )

            await session.commit()

    @app_commands.command(
        name="werk", description="Zet een pet aan het werk, of haal de opbrengst op als de shift klaar is"
    )
    @app_commands.describe(
        pet_id="Het ID van je pet",
        werkplek="De werkplek (alleen nodig om een nieuwe shift te starten)",
        cyclus="De shift-duur (alleen nodig om een nieuwe shift te starten)",
    )
    @app_commands.choices(
        werkplek=[
            app_commands.Choice(name="Moestuin", value="Moestuin"),
            app_commands.Choice(name="Vijver", value="Vijver"),
            app_commands.Choice(name="Werkbank", value="Werkbank"),
            app_commands.Choice(name="Bos", value="Bos"),
            app_commands.Choice(name="Nachtwacht", value="Nachtwacht"),
        ],
        cyclus=[
            app_commands.Choice(name="Korte shift (2 uur)", value="korte"),
            app_commands.Choice(name="Lange shift (6 uur)", value="lange"),
            app_commands.Choice(name="Overnacht (10 uur)", value="overnacht"),
        ],
    )
    async def werk(
        self,
        interaction: discord.Interaction,
        pet_id: int,
        werkplek: app_commands.Choice[str] | None = None,
        cyclus: app_commands.Choice[str] | None = None,
    ) -> None:
        async with async_session() as session:
            huisdier = await session.get(Huisdier, pet_id)
            if huisdier is None or huisdier.eigenaar_id != interaction.user.id:
                await interaction.response.send_message(
                    "Je hebt geen pet met dat ID.", ephemeral=True
                )
                return

            if huisdier.status == PetStatus.werkplek:
                await self._verwerk_lopende_shift(session, interaction, huisdier)
                return

            if huisdier.status == PetStatus.team:
                await interaction.response.send_message(
                    f"**{huisdier.naam}** zit in je team en kan niet ook werken.", ephemeral=True
                )
                return

            if werkplek is None or cyclus is None:
                await interaction.response.send_message(
                    "Geef zowel `werkplek` als `cyclus` op om een nieuwe shift te starten.",
                    ephemeral=True,
                )
                return

            if huisdier.energie < 20:
                await interaction.response.send_message(
                    f"**{huisdier.naam}** heeft te weinig energie om te werken (onder 20).",
                    ephemeral=True,
                )
                return

            werkplek_obj = await session.scalar(select(Werkplek).where(Werkplek.type == werkplek.value))
            cyclus_info = WERK_CYCLI[cyclus.value]

            huisdier.status = PetStatus.werkplek
            huisdier.werkplek_type_id = werkplek_obj.id
            huisdier.werk_cyclus = cyclus.value
            huisdier.werk_gestart_op = _nu()
            huisdier.werk_notificatie_verstuurd = False
            huisdier.werk_kanaal_id = interaction.channel_id
            huisdier.energie = max(0, huisdier.energie - cyclus_info.energie_kost)
            await session.commit()

            await interaction.response.send_message(
                f"👷 **{huisdier.naam}** is aan het werk gezet in **{werkplek_obj.type}** "
                f"({cyclus_info.label}, klaar over {cyclus_info.duur_uren:g} uur).",
                ephemeral=True,
            )
            await send_log(
                self.bot,
                interaction.guild_id,
                "werk",
                fmt_log(
                    "🟡",
                    "werk",
                    f"{interaction.user.mention} zette **{huisdier.naam}** aan het werk "
                    f"in {werkplek_obj.type} ({cyclus_info.label})",
                ),
            )

    async def _verwerk_lopende_shift(self, session, interaction: discord.Interaction, huisdier: Huisdier) -> None:
        cyclus_info = WERK_CYCLI[huisdier.werk_cyclus]
        verstreken = _nu() - huisdier.werk_gestart_op
        resterend = timedelta(hours=cyclus_info.duur_uren) - verstreken

        if resterend > timedelta(0):
            uren = resterend.total_seconds() / 3600
            await interaction.response.send_message(
                f"**{huisdier.naam}** is nog aan het werk. Nog ongeveer {uren:.1f} uur te gaan.",
                ephemeral=True,
            )
            return

        werkplek_obj = await session.get(Werkplek, huisdier.werkplek_type_id)
        item = await session.get(Item, werkplek_obj.opbrengst_item_id)

        effectieve_uren = cyclus_info.duur_uren * cyclus_info.output_multiplier
        grondstof_aantal = max(
            1, round(float(werkplek_obj.output_per_uur) * effectieve_uren * (float(huisdier.werk_genen) / 100))
        )
        currency_aantal = round(grondstof_aantal * CURRENCY_PER_GRONDSTOF)

        speler = await session.get(Speler, interaction.user.id)
        speler.currency += currency_aantal
        await _voeg_toe_aan_inventaris(session, interaction.user.id, item.id, grondstof_aantal)

        huisdier.status = PetStatus.rust
        huisdier.werkplek_type_id = None
        huisdier.werk_cyclus = None
        huisdier.werk_gestart_op = None
        huisdier.werk_kanaal_id = None
        await session.commit()

        await interaction.response.send_message(
            f"🧺 **{huisdier.naam}** is klaar met werken in {werkplek_obj.type}! "
            f"Opbrengst: {grondstof_aantal}x {item.naam}, {currency_aantal} currency."
        )
        await send_log(
            self.bot,
            interaction.guild_id,
            "werk",
            fmt_log(
                "🟢",
                "werk",
                f"{interaction.user.mention} haalde opbrengst op van **{huisdier.naam}** "
                f"({werkplek_obj.type}): {grondstof_aantal}x {item.naam}, {currency_aantal} currency",
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WerkCog(bot))
