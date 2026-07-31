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
from dataclasses import dataclass

from sqlalchemy import select

import config
from db.engine import async_session
from db.models import Instelling, WerkCyclus

log = logging.getLogger("chaos_critters")

_cache: dict[str, str] = {}
_werk_cycli_cache: list[WerkCyclus] = []


@dataclass(frozen=True)
class Cyclus:
    """Eén shift-variant van /werk, opgebouwd uit een `WerkCyclus`-rij.

    Stond tot 2026-07-30 in cogs/werk.py, maar is hierheen verhuisd omdat
    werk_cycli() 'm moet kunnen opbouwen: andersom zou een circulaire
    import ontstaan (cogs/werk.py importeert al utils.balans)."""

    label: str
    duur_uren: float  # werkelijke wachttijd (kort in dev, om te testen)
    reward_duur_uren: float  # altijd de echte waarde, voor de opbrengst-berekening
    energie_kost: int
    output_multiplier: float


# In dev duurt elke shift 1 testminuut i.p.v. uren, maar de opbrengst blijft
# hetzelfde alsof de volledige (echte) cyclus is verstreken.
_TEST_DUUR_UREN = 1 / 60

# Fallback als de werk_cycli-tabel (nog) leeg is, bijv. bij een deploy vóór
# de migratie. Exact de waarden die tot 2026-07-30 hardcoded in cogs/werk.py
# stonden, dus het gedrag verandert dan niet.
#   (sleutel, label, duur_uren, energie_kost, output_multiplier)
_STANDAARD_CYCLI = [
    ("korte", "Korte shift", 2.0, 20, 2.0),
    ("lange", "Lange shift", 6.0, 50, 2.3),
    ("overnacht", "Overnacht", 10.0, 70, 2.6),
]


async def laad() -> None:
    """(Her)laadt alle balansdata in het geheugen. Aangeroepen bij het
    opstarten van de bot, en door de portal na elke wijziging."""
    global _cache, _werk_cycli_cache
    async with async_session() as session:
        rijen = (await session.execute(select(Instelling))).scalars().all()
        cycli = (
            await session.execute(select(WerkCyclus).order_by(WerkCyclus.volgorde))
        ).scalars().all()
        session.expunge_all()
    _cache = {rij.sleutel: rij.waarde for rij in rijen}
    _werk_cycli_cache = list(cycli)
    log.info("Balans-cache geladen: %d waarden, %d werk-cycli", len(_cache), len(_werk_cycli_cache))


def _bouw_cyclus(label: str, echte_duur: float, energie_kost: int, output_multiplier: float) -> Cyclus:
    return Cyclus(
        label=label,
        duur_uren=_TEST_DUUR_UREN if config.ENVIRONMENT == "dev" else echte_duur,
        reward_duur_uren=echte_duur,
        energie_kost=energie_kost,
        output_multiplier=output_multiplier,
    )


def werk_cycli() -> dict[str, Cyclus]:
    """sleutel -> Cyclus, opgebouwd uit de cache. Was tot 2026-07-30 een
    module-constante `WERK_CYCLI` in cogs/werk.py die op import-tijd werd
    opgebouwd; als functie leest elke aanroep de actuele waarden, dus een
    portal-wijziging werkt meteen op de volgende shift."""
    if not _werk_cycli_cache:
        return {
            sleutel: _bouw_cyclus(label, duur, energie, multiplier)
            for sleutel, label, duur, energie, multiplier in _STANDAARD_CYCLI
        }
    return {
        rij.sleutel: _bouw_cyclus(
            rij.label, float(rij.duur_uren), rij.energie_kost, float(rij.output_multiplier)
        )
        for rij in _werk_cycli_cache
    }


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
