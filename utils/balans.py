"""Cache voor balanswaarden die via het admin panel aanpasbaar zijn.

Fase 2 van het admin panel (2026-07-30): balansconstanten die tot nu toe
hardcoded Python-waarden waren, verhuizen stuk voor stuk naar de
`Instelling`-tabel zodat de portal ze kan aanpassen zonder code-wijziging.

Bewust geen async DB-read per call-site: sommige van deze waarden worden
in loops gelezen (bijv. per gevechtsronde), dat zou traag en invasief
worden. In plaats daarvan: bij het opstarten van de bot alles in het
geheugen laden (`laad()`), synchrone getters met een default als de
sleutel nog niet bestaat, en een herlaad-aanroep vanuit de portal zodra
daar iets opgeslagen wordt (portal draait in hetzelfde proces als de bot,
dus dat is een gewone functieaanroep, geen polling of events nodig).

De default in elke `get_*`-aanroep is bewust de oude hardcoded waarde:
als de sleutel nog niet in de database staat (bijv. een deploy vóórdat de
seed opnieuw gedraaid is), verandert er dus niets aan het gedrag.
"""

import logging

from sqlalchemy import select

from db.engine import async_session
from db.models import Instelling

log = logging.getLogger("chaos_critters")

_cache: dict[str, str] = {}


async def laad() -> None:
    """(Her)laadt alle Instelling-rijen in het geheugen. Aangeroepen bij het
    opstarten van de bot, en door de portal na elke wijziging."""
    global _cache
    async with async_session() as session:
        rijen = (await session.execute(select(Instelling))).scalars().all()
    _cache = {rij.sleutel: rij.waarde for rij in rijen}
    log.info("Balans-cache geladen: %d waarden", len(_cache))


def get_float(sleutel: str, default: float) -> float:
    ruw = _cache.get(sleutel)
    if ruw is None:
        return default
    try:
        return float(ruw)
    except ValueError:
        log.warning("Balans-sleutel '%s' heeft een ongeldige waarde '%s', gebruik default %s", sleutel, ruw, default)
        return default


def get_int(sleutel: str, default: int) -> int:
    ruw = _cache.get(sleutel)
    if ruw is None:
        return default
    try:
        # float() eerst: voorkomt een crash als iemand in de portal per
        # ongeluk "3.0" i.p.v. "3" invult voor een geheel getal.
        return int(float(ruw))
    except ValueError:
        log.warning("Balans-sleutel '%s' heeft een ongeldige waarde '%s', gebruik default %s", sleutel, ruw, default)
        return default
