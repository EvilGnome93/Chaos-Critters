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
from db.models import Instelling, Item, Recept, WerkCyclus

log = logging.getLogger("chaos_critters")

_cache: dict[str, str] = {}
_werk_cycli_cache: list[WerkCyclus] = []
_recepten_cache: dict[str, list[tuple[str, int]]] = {}
# itemnaam -> (honger_herstel, voerbak_vanaf), gesorteerd op prijs (een
# voerbak eet goedkoopste eerst).
_voer_cache: dict[str, tuple[int, str | None]] = {}


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
    global _cache, _werk_cycli_cache, _recepten_cache, _voer_cache
    async with async_session() as session:
        rijen = (await session.execute(select(Instelling))).scalars().all()
        cycli = (
            await session.execute(select(WerkCyclus).order_by(WerkCyclus.volgorde))
        ).scalars().all()
        # Recepten meteen platslaan naar itemnaam -> [(grondstofnaam, aantal)],
        # zodat aanroepers geen extra queries of joins nodig hebben (de
        # aanroepende code werkt van oudsher met namen, niet met item-ID's).
        item_naam = Item.__table__.alias("item_naam")
        grondstof_naam = Item.__table__.alias("grondstof_naam")
        recept_rijen = (
            await session.execute(
                select(item_naam.c.naam, grondstof_naam.c.naam, Recept.aantal)
                .join(item_naam, Recept.item_id == item_naam.c.id)
                .join(grondstof_naam, Recept.grondstof_id == grondstof_naam.c.id)
                .order_by(item_naam.c.naam, Recept.id)
            )
        ).all()
        # Voedingsitems op prijs: dat is precies de volgorde waarin een
        # voerbak z'n voorraad opeet (goedkoopste eerst).
        voer_rijen = (
            await session.execute(
                select(Item.naam, Item.honger_herstel, Item.voerbak_vanaf)
                .where(Item.honger_herstel.is_not(None))
                .order_by(Item.prijs)
            )
        ).all()
        session.expunge_all()

    _cache = {rij.sleutel: rij.waarde for rij in rijen}
    _werk_cycli_cache = list(cycli)

    recepten: dict[str, list[tuple[str, int]]] = {}
    for item, grondstof, aantal in recept_rijen:
        recepten.setdefault(item, []).append((grondstof, aantal))
    _recepten_cache = recepten

    # Op prijs sorteren: een voerbak eet goedkoopste eerst, en dict-volgorde
    # blijft in Python behouden — dus voerbak_voer() hoeft niet nog eens te
    # sorteren.
    _voer_cache = {
        naam: (herstel, vanaf) for naam, herstel, vanaf in voer_rijen
    }

    log.info(
        "Balans-cache geladen: %d waarden, %d werk-cycli, %d recepten, %d voedingsitems",
        len(_cache), len(_werk_cycli_cache), len(_recepten_cache), len(_voer_cache),
    )


def recepten() -> dict[str, list[tuple[str, int]]]:
    """itemnaam -> [(grondstofnaam, aantal per stuk)]. Was tot 2026-07-30 de
    hardcoded `RECEPT_KOSTEN`-dict in cogs/verzorging.py.

    Geen fallback naar hardcoded waarden zoals bij de werk-cycli: een lege
    recepten-tabel betekent hier "geen enkel item kost grondstoffen", wat
    zichtbaar is (items worden gratis buiten hun Chaos Coins-prijs) en
    herstelbaar via de portal. Stilletjes terugvallen op oude waarden zou
    juist verwarrend zijn als iemand bewust een recept weghaalt."""
    return _recepten_cache


def voer_effecten() -> dict[str, int]:
    """itemnaam -> honger dat het item herstelt, goedkoopste eerst. Was tot
    2026-07-30 HONGER_HERSTEL_WAARDEN + VOLLEDIG_HERSTEL_ITEMS in
    utils/stats.py; die tweede is opgegaan in de waarde 100, omdat honger
    toch op 100 geklemd wordt en het resultaat dus identiek is.

    Net als bij recepten() bewust geen fallback: een item zonder
    honger_herstel is simpelweg geen voer, en dat is zichtbaar in /voer."""
    return {naam: herstel for naam, (herstel, _) in _voer_cache.items()}


def voerbak_voer(niveau: str) -> list[str]:
    """Itemnamen die een voerbak van dit niveau automatisch mag gebruiken,
    in de volgorde waarin ze opgegeten worden (goedkoopste eerst). Was tot
    2026-07-30 VOERBAK_ITEMS_PER_NIVEAU in utils/stats.py.

    "simpel" pakt alleen items met voerbak_vanaf == "simpel"; "slim" pakt
    alles wat een voerbak überhaupt mag gebruiken."""
    return [
        naam
        for naam, (_, vanaf) in _voer_cache.items()
        if vanaf is not None and (niveau == "slim" or vanaf == niveau)
    ]


# Ondergrens/bovengrens van de willekeurige machtsvariatie per tactiek: een
# aggressieve pet gokt harder (breder bereik), een voorzichtige speelt op
# safe. Als een sleutel ontbreekt geldt de oude hardcoded waarde.
_TACTIEK_DEFAULTS = {
    "aggressief": (-0.25, 0.35),
    "gebalanceerd": (-0.15, 0.15),
    "voorzichtig": (-0.10, 0.10),
}


def tactiek_variantie(tactiek: str) -> tuple[float, float]:
    """(min, max) machtsvariatie voor een tactiek. Onbekende tactieken
    vallen terug op 'gebalanceerd', net als de oude dict-lookup deed."""
    standaard_min, standaard_max = _TACTIEK_DEFAULTS.get(
        tactiek, _TACTIEK_DEFAULTS["gebalanceerd"]
    )
    return (
        get_float(f"tactiek_{tactiek}_variantie_min", standaard_min),
        get_float(f"tactiek_{tactiek}_variantie_max", standaard_max),
    )


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
