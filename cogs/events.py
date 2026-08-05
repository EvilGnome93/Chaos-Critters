"""Aankondigingen van chaos-events (2026-08-05).

Starten gebeurt in de portal (portal/api_content.py); deze cog doet alleen
de zichtbare kant: het bericht bij de start, en een achtergrondtaak die
meldt wanneer een event afgelopen is.

**De taak zet niets uit.** Effecten lopen vanzelf af omdat `eindigt_op` in
het verleden komt te liggen (utils/events.py), dus als deze taak zou
sneuvelen blijft het spel gewoon kloppen — je mist dan hooguit de
"voorbij"-melding. Daarom mag deze taak ook rustig grof falen zonder dat er
iets stukgaat, maar hij vangt alsnog alles af: een uitzondering zou de loop
permanent stilleggen, zelfde valkuil als bij de werk-notificaties.

Aankondigen gebeurt in alle spawn-kanalen (daar zijn de spelers, en bij een
incense zie je de spawns er meteen daarna verschijnen) plus het kanaal dat
bij het starten gekozen is. Beide op verzoek van de gebruiker.
"""

import asyncio
import logging

import discord
from discord.ext import commands
from sqlalchemy import select

import config
from db.engine import async_session
from db.models import Event, SpawnKanaal
from utils import events

log = logging.getLogger("chaos_critters")

# Even vaak kijken als de werk-notificaties: een event van een uur hoeft niet
# op de seconde nauwkeurig afgemeld te worden.
EINDE_CHECK_INTERVAL_SECONDEN = 15 if config.ENVIRONMENT == "dev" else 120


async def _doelkanalen(bot: commands.Bot, extra_kanaal_id: int | None) -> list[discord.abc.Messageable]:
    """Alle spawn-kanalen plus het bij dit event gekozen kanaal, zonder
    dubbelen (het gekozen kanaal kan zelf ook een spawn-kanaal zijn)."""
    async with async_session() as session:
        ids = list((await session.execute(select(SpawnKanaal.channel_id))).scalars().all())
    if extra_kanaal_id is not None and extra_kanaal_id not in ids:
        ids.append(extra_kanaal_id)

    kanalen = []
    for kanaal_id in ids:
        kanaal = bot.get_channel(kanaal_id)
        if kanaal is None:
            log.warning("Kan kanaal %s niet vinden voor een event-aankondiging", kanaal_id)
            continue
        kanalen.append(kanaal)
    return kanalen


async def kondig_aan(bot: commands.Bot, event: Event, tekst: str) -> None:
    """Stuurt één bericht naar elk doelkanaal. Fouten per kanaal worden
    gelogd maar stoppen de rest niet: één kanaal zonder schrijfrechten mag
    de aankondiging niet voor iedereen blokkeren."""
    type_ = events.TYPES.get(event.sleutel)
    embed = discord.Embed(
        title=f"{type_.emoji if type_ else '🎉'} Chaos-event",
        description=tekst,
        color=discord.Color.purple(),
    )
    for kanaal in await _doelkanalen(bot, event.aankondiging_kanaal_id):
        try:
            await kanaal.send(embed=embed)
        except discord.HTTPException as e:
            log.warning("Kon event-aankondiging niet sturen in kanaal %s: %s", kanaal.id, e)


class EventsCog(commands.Cog):
    """Achtergrondtaak die afgelopen events afmeldt."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.einde_taak: asyncio.Task | None = None

    async def cog_load(self) -> None:
        await events.laad()
        self.einde_taak = asyncio.create_task(self._einde_loop())

    async def cog_unload(self) -> None:
        if self.einde_taak:
            self.einde_taak.cancel()

    async def _einde_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(EINDE_CHECK_INTERVAL_SECONDEN)
                try:
                    await self._meld_afgelopen_events()
                except Exception:
                    # Breed vangen: deze taak is puur cosmetisch, maar zou bij
                    # een uitzondering wél permanent stoppen en dan zou nooit
                    # meer een event afgemeld worden.
                    log.exception("Fout bij het afmelden van events")
        except asyncio.CancelledError:
            pass

    async def _meld_afgelopen_events(self) -> None:
        async with async_session() as session:
            afgelopen = (
                await session.execute(
                    select(Event).where(
                        Event.eindigt_op <= events._nu(), Event.einde_gemeld.is_(False)
                    )
                )
            ).scalars().all()
            if not afgelopen:
                return
            # Vlag zetten en committen vóór het versturen: als Discord traag
            # is en de volgende ronde begint, zou hetzelfde event anders
            # tweemaal afgemeld worden.
            for event in afgelopen:
                event.einde_gemeld = True
            await session.commit()
            session.expunge_all()

        for event in afgelopen:
            await kondig_aan(self.bot, event, events.einde_tekst(event))
            log.info("Event '%s' afgelopen en afgemeld", event.sleutel)
        # De cache kan nu opgeruimd worden; actieve() filtert al op tijd, maar
        # zo blijft er niets onnodig in het geheugen hangen.
        await events.laad()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventsCog(bot))
