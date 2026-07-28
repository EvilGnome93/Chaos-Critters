"""Honger/energie-verval en -herstel. Zie projectbrief sectie 5 en 6.

Blijdschap is bewust geparkeerd (2026-07-22): het veld blijft in het
schema staan, maar niets in de bot leest/schrijft het nog, tot er een
zinvolle manier is om het zowel te laten dalen als te herstellen.

Verval wordt lazy berekend, net als de werk-cyclus in cogs/werk.py: geen
achtergrondtaak, alleen bijgewerkt zodra een pet ergens aangeraakt wordt
(/lijst, /verzorg, /werk). sync_stats() moet daarom aangeroepen worden vóór
elke keer dat honger/energie gelezen of gecontroleerd wordt.
"""

from datetime import datetime, timezone

from sqlalchemy import select

import config
from db.models import Huisdier, InventarisItem, Item, PetStatus

# Placeholder balans-waarden (echte tijd), later bij te stellen.
_HONGER_VERVAL_MINUTEN_ECHT = 20  # -1 honger per 20 min
_ENERGIE_HERSTEL_MINUTEN_ECHT = 10  # +1 energie per 10 min in rust (brief sectie 6)

# Zelfde compressie-factor als de werk-cycli in dev (2u shift -> 1 testminuut).
_DEV_VERSNELLING = 120

HONGER_VERVAL_MINUTEN = (
    _HONGER_VERVAL_MINUTEN_ECHT / _DEV_VERSNELLING if config.ENVIRONMENT == "dev" else _HONGER_VERVAL_MINUTEN_ECHT
)
ENERGIE_HERSTEL_MINUTEN = (
    _ENERGIE_HERSTEL_MINUTEN_ECHT / _DEV_VERSNELLING if config.ENVIRONMENT == "dev" else _ENERGIE_HERSTEL_MINUTEN_ECHT
)

ENERGIE_MINIMUM = 20  # onder dit niveau kan een pet niet ingezet worden (brief sectie 6)

# Passieve uitrustings-effecten (2026-07-27, verzoek van de gebruiker:
# Item-overhaul deel 1 — voerbakken/zelfreinigend systeem krijgen hun
# beloofde effect).
#
# Zelfreinigend systeem beloofde origineel "verhoogt blijdschap automatisch",
# maar blijdschap is bewust gepauzeerd (zie docstring hierboven) — effect
# herdefinieerd naar energie: laat energie ook buiten rust (bijv. tijdens
# werk) passief herstellen, alsof het systeem de pet automatisch onderhoudt
# zonder dat 'ie hoeft uit te rusten. Eén item, geen tiers, dus geen factor
# nodig — vol tempo zodra actief.
#
# Voerbak-effect herzien (2026-07-28, verzoek van de gebruiker: "hij gebruikt
# het voer dat je hebt in je inventaris, i.p.v. het huidige idee"). Eerste
# versie gaf een abstracte honger-regen los van je inventaris; nu verbruikt
# de voerbak echt voedingsitems (zie sync_stats_met_voerbak hieronder) —
# goedkoopste eerst, en niks doen als er geen voer meer is (geen fallback-
# regen). Dezelfde waarden als _HONGER_HERSTEL/_VOLLEDIG_HERSTEL in
# cogs/verzorging.py — hier de bron van waarheid, daar hergebruikt, om
# duplicatie te voorkomen (cogs/werk.py mag dit niet importeren uit
# cogs/verzorging.py, dat zou een circulaire import geven).
HONGER_HERSTEL_WAARDEN = {"Basis brokjes": 15, "Graanvrije premium voeding": 40}
VOLLEDIG_HERSTEL_ITEMS = {"Vers vlees/vis"}
# Simpele voerbak mag alleen het goedkoopste voer gebruiken; Slimme voerbak
# mag alle "echte" voedingsitems gebruiken (niet de Mysterie voedselzak, die
# blijft een bewuste, handmatige gok). Volgorde is goedkoopste eerst.
VOERBAK_ITEMS_PER_NIVEAU = {
    "simpel": ["Basis brokjes"],
    "slim": ["Basis brokjes", "Graanvrije premium voeding", "Vers vlees/vis"],
}

_SLAAP_COOLDOWN_UUR_ECHT = 24  # /slaap: instant volle energie, kost honger, max 1x per dag per pet
SLAAP_COOLDOWN_UUR = (
    _SLAAP_COOLDOWN_UUR_ECHT / _DEV_VERSNELLING if config.ENVIRONMENT == "dev" else _SLAAP_COOLDOWN_UUR_ECHT
)
SLAAP_HONGER_KOST = 20

_BLESSURE_DUUR_UUR_ECHT = 2  # tijdelijk niet inzetbaar na een verloren gevecht-matchup
BLESSURE_DUUR_UUR = (
    _BLESSURE_DUUR_UUR_ECHT / _DEV_VERSNELLING if config.ENVIRONMENT == "dev" else _BLESSURE_DUUR_UUR_ECHT
)


def _nu() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sync_stats(huisdier: Huisdier, nu: datetime | None = None) -> None:
    """Werkt honger/energie bij op basis van verstreken tijd. Puur synchroon,
    geen DB-toegang — raakt dus niet aan het voerbak-effect (zie
    sync_stats_met_voerbak), dat een inventaris-write nodig heeft."""
    nu = nu or _nu()
    verstreken_minuten = (nu - huisdier.laatste_verzorging_op).total_seconds() / 60
    if verstreken_minuten <= 0:
        return

    huisdier.honger = max(0, huisdier.honger - int(verstreken_minuten // HONGER_VERVAL_MINUTEN))

    if huisdier.status == PetStatus.rust or huisdier.zelfreinigend_actief:
        huisdier.energie = min(100, huisdier.energie + int(verstreken_minuten // ENERGIE_HERSTEL_MINUTEN))
    huisdier.laatste_verzorging_op = nu


async def sync_stats_met_voerbak(session, huisdier: Huisdier, nu: datetime | None = None) -> None:
    """sync_stats() plus het voerbak-effect: verbruikt automatisch echt voer
    uit de inventaris van de eigenaar om honger tot 100 aan te vullen,
    goedkoopste toegestane item eerst (Simpele voerbak: alleen Basis
    brokjes; Slimme voerbak: alle 3 voedingsitems). Geen voer meer over?
    Dan gebeurt er niets — gewoon het normale verval, bewust geen
    fallback-regen (2026-07-28, verzoek van de gebruiker).

    Async omdat dit een DB-write is; aanroepers hebben dus al een sessie
    open (net als voor sync_stats() al gold — deze commit't zelf niet)."""
    sync_stats(huisdier, nu)
    if huisdier.voerbak_niveau is None:
        return

    for item_naam in VOERBAK_ITEMS_PER_NIVEAU[huisdier.voerbak_niveau]:
        if huisdier.honger >= 100:
            break
        item_obj = await session.scalar(select(Item).where(Item.naam == item_naam))
        inventaris_item = await session.scalar(
            select(InventarisItem).where(
                InventarisItem.speler_id == huisdier.eigenaar_id, InventarisItem.item_id == item_obj.id
            )
        )
        while inventaris_item and inventaris_item.aantal > 0 and huisdier.honger < 100:
            inventaris_item.aantal -= 1
            if item_naam in VOLLEDIG_HERSTEL_ITEMS:
                huisdier.honger = 100
            else:
                huisdier.honger = min(100, huisdier.honger + HONGER_HERSTEL_WAARDEN[item_naam])


def inzetbaarheid_probleem(huisdier: Huisdier) -> str | None:
    """None als de pet aan het werk gezet/in team geplaatst mag worden, anders de foutmelding."""
    if huisdier.geblesseerd_tot is not None and huisdier.geblesseerd_tot > _nu():
        resterend = (huisdier.geblesseerd_tot - _nu()).total_seconds() / 3600
        return f"**{huisdier.naam}** is geblesseerd na een gevecht en kan nog niet ingezet worden (nog {resterend:.1f} uur)."
    if huisdier.energie < ENERGIE_MINIMUM:
        return f"**{huisdier.naam}** heeft te weinig energie om ingezet te worden (onder {ENERGIE_MINIMUM})."
    if huisdier.honger <= 0:
        return f"**{huisdier.naam}** heeft honger en kan niet ingezet worden. Verzorg de pet eerst met `/verzorg`."
    return None
