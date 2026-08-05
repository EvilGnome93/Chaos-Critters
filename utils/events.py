"""Chaos events: tijdelijke, server-brede modifiers (2026-08-05).

Vier types in de eerste lichting, gekozen door de gebruiker:

- **Incense** — de berichten-drempel voor een spawn gaat omlaag, dus er
  verschijnen veel sneller critters. Het oorspronkelijke idee van de
  gebruiker, naar het Pokémon Go-voorbeeld.
- **Sterrenregen** — de spawnkans van Rare en hoger wordt opgeschroefd.
- **Grondstoffenregen** — meer grondstoffen per voltooide shift.
- **Muntregen** — meer Chaos Coins uit werk en gevechten.

**Alleen handmatig te starten vanuit het admin panel.** Bewust geen
willekeurige automatische events: dan zou een incense kunnen lopen terwijl
er niemand online is, en dat is precies verspild.

**Effecten lopen vanzelf af.** "Is dit event actief" is puur `eindigt_op >
nu`, dus er is geen achtergrondtaak nodig om iets uit te zetten en een
herstart midden in een event verandert niets. De taak die er wél is doet
alleen de "voorbij"-aankondiging.

**Waarom een cache.** `is_actief()` wordt aangeroepen bij elke spawn, elke
shift en elk gevecht; een DB-query per keer zou zonde zijn. Zelfde patroon
als utils/balans.py: alles in het geheugen, herladen bij het opstarten en
zodra de portal iets start of stopt (dat draait in hetzelfde proces, dus
een gewone functieaanroep).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.engine import async_session
from db.models import Event
from utils import balans

log = logging.getLogger("chaos_critters")

_cache: list[Event] = []


@dataclass(frozen=True)
class EventType:
    sleutel: str
    naam: str
    emoji: str
    # Wat spelers ervan merken; {sterkte} wordt vervangen door een leesbare
    # weergave van de factor (bijv. "4x sneller", "2x").
    effect: str
    standaard_sterkte: float
    # Hoe de sterkte in de aankondiging getoond wordt. Bij een incense is
    # een factor van 0.25 juist "4x sneller", niet "0.25x".
    omgekeerd: bool = False

    def sterkte(self) -> float:
        return balans.get_float(f"event_{self.sleutel}_sterkte", self.standaard_sterkte)

    def sterkte_tekst(self, sterkte: float) -> str:
        getoond = (1 / sterkte) if self.omgekeerd and sterkte else sterkte
        heel = round(getoond)
        return f"{heel}x" if abs(getoond - heel) < 0.05 else f"{getoond:.1f}x"

    def effect_tekst(self, sterkte: float) -> str:
        return self.effect.format(sterkte=self.sterkte_tekst(sterkte))


TYPES: dict[str, EventType] = {
    t.sleutel: t
    for t in (
        EventType(
            "incense",
            "Incense",
            "🌫️",
            "Critters verschijnen **{sterkte} sneller** in de spawn-kanalen.",
            0.25,
            omgekeerd=True,
        ),
        EventType(
            "sterrenregen",
            "Sterrenregen",
            "🌠",
            "**{sterkte} meer kans** op een critter van Rare of hoger.",
            3.0,
        ),
        EventType(
            "dubbele_grondstoffen",
            "Grondstoffenregen",
            "🌾",
            "Voltooide shifts leveren **{sterkte} zoveel grondstoffen** op.",
            2.0,
        ),
        EventType(
            "dubbele_coins",
            "Muntregen",
            "💰",
            "**{sterkte} zoveel Chaos Coins** uit werk en gevechten.",
            2.0,
        ),
    )
}

# Vanaf welk tier "sterrenregen" de spawnkans opschroeft. Rare is tier 3;
# Uncommon (2) telt bewust niet mee, anders verschuift het event vooral naar
# het middensegment i.p.v. naar echt zeldzame vangsten.
ZELDZAAM_VANAF_TIER = 3


def standaard_duur_minuten() -> int:
    return balans.get_int("event_standaard_duur_minuten", 60)


def _nu() -> datetime:
    """Naïeve UTC, net als de rest van de codebase (utils/stats.py)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def laad() -> None:
    """(Her)laadt de lopende events. Aangeroepen bij het opstarten van de bot
    en door de portal na het starten/stoppen van een event."""
    global _cache
    async with async_session() as session:
        rijen = (
            await session.execute(select(Event).where(Event.eindigt_op > _nu()))
        ).scalars().all()
        session.expunge_all()
    _cache = list(rijen)
    if _cache:
        log.info(
            "Actieve chaos-events geladen: %s", ", ".join(e.sleutel for e in _cache)
        )


def actieve() -> list[Event]:
    """Alle events die nu lopen. Filtert op tijd i.p.v. te vertrouwen op een
    herlaadmoment, zodat een event vanzelf afloopt zonder dat er iets hoeft
    te draaien."""
    nu = _nu()
    return [e for e in _cache if e.eindigt_op > nu]


def actief(sleutel: str) -> Event | None:
    """Het lopende event van dit type, of None. Bij meerdere (kan niet via de
    portal, maar wel handmatig in de database) wint de laatste."""
    passend = [e for e in actieve() if e.sleutel == sleutel]
    return passend[-1] if passend else None


def is_actief(sleutel: str) -> bool:
    return actief(sleutel) is not None


def factor(sleutel: str, standaard: float = 1.0) -> float:
    """De sterkte van dit event als het loopt, anders `standaard` (1.0 =
    geen effect). Elke aanroeper kan dus onvoorwaardelijk vermenigvuldigen."""
    event = actief(sleutel)
    return float(event.sterkte) if event is not None else standaard


async def start(
    session,
    sleutel: str,
    *,
    duur_minuten: int | None = None,
    aankondiging_kanaal_id: int | None = None,
    gestart_door: int | None = None,
) -> Event:
    """Start een event. Commit niet zelf; de aanroeper (de portal) doet dat,
    en roept daarna laad() aan om de cache bij te werken."""
    if sleutel not in TYPES:
        raise ValueError(f"Onbekend event-type: {sleutel!r}")
    duur = duur_minuten or standaard_duur_minuten()
    event = Event(
        sleutel=sleutel,
        # Momentopname: een balanswijziging halverwege verandert zo niet de
        # spelregels van een event dat al loopt.
        sterkte=TYPES[sleutel].sterkte(),
        eindigt_op=_nu() + timedelta(minutes=duur),
        aankondiging_kanaal_id=aankondiging_kanaal_id,
        gestart_door=gestart_door,
    )
    session.add(event)
    await session.flush()
    return event


async def stop(session, event_id: int) -> Event | None:
    """Beëindigt een lopend event meteen. Zet eindigt_op op nu i.p.v. de rij
    te verwijderen, zodat de geschiedenis bewaard blijft en de
    einde-aankondiging nog gedaan wordt."""
    event = await session.get(Event, event_id)
    if event is None:
        return None
    event.eindigt_op = _nu()
    return event


def start_tekst(event: Event) -> str:
    type_ = TYPES.get(event.sleutel)
    if type_ is None:
        return "Er is een chaos-event begonnen!"
    # Relatieve Discord-timestamp: telt vanzelf af en staat voor iedereen in
    # de eigen tijdzone.
    einde = int(event.eindigt_op.replace(tzinfo=timezone.utc).timestamp())
    return (
        f"{type_.emoji} **{type_.naam} is begonnen!**\n"
        f"{type_.effect_tekst(float(event.sterkte))}\n"
        f"Loopt af <t:{einde}:R>."
    )


def einde_tekst(event: Event) -> str:
    type_ = TYPES.get(event.sleutel)
    naam = type_.naam if type_ else "Het chaos-event"
    emoji = type_.emoji if type_ else "🏁"
    return f"{emoji} **{naam} is afgelopen.** Alles is weer normaal."
