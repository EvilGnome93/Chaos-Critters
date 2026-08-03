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
from utils import balans

# 2026-07-30, admin panel fase 2, blok 2: was hardcoded module-constanten
# (sommige afgeleid op import-tijd met de dev-versnelling erin verwerkt),
# nu functies die de actuele waarde uit de balans-cache lezen. Belangrijke
# valkuil die dit oploste: een afgeleide constante op import-tijd bevriest
# de waarde van vóór de eerste balans.laad()-aanroep bij bot-opstart, dus
# dit moesten functies worden, geen module-constanten.


def _dev_versnelling() -> float:
    """Zelfde sleutel als utils/gevechten.py:ranked_reset_uur() — beide
    moeten in dev even hard versneld worden, dus delen ze één instelling."""
    return balans.get_float("dev_versnelling", 120)


def honger_verval_minuten() -> float:
    echt = balans.get_float("honger_verval_minuten_echt", 20)  # -1 honger per 20 min
    return echt / _dev_versnelling() if config.ENVIRONMENT == "dev" else echt


def energie_herstel_minuten() -> float:
    echt = balans.get_float("energie_herstel_minuten_echt", 10)  # +1 energie per 10 min in rust (brief sectie 6)
    return echt / _dev_versnelling() if config.ENVIRONMENT == "dev" else echt


def energie_minimum() -> int:
    return balans.get_int("energie_minimum", 20)  # onder dit niveau kan een pet niet ingezet worden (brief sectie 6)

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
# regen).
#
# Welk item hoeveel honger herstelt en welke voerbak het mag pakken, stond
# hier tot 2026-07-30 als HONGER_HERSTEL_WAARDEN / VOLLEDIG_HERSTEL_ITEMS /
# VOERBAK_ITEMS_PER_NIVEAU. Dat zijn nu de kolommen items.honger_herstel en
# items.voerbak_vanaf (admin panel fase 2, blok 5): het waren drie dicts op
# itemnaam, dus die data hoort gewoon bij het item. Zie
# balans.voer_effecten() en balans.voerbak_voer(). Simpele voerbak mag
# alleen het goedkoopste voer gebruiken, Slimme voerbak alle "echte"
# voedingsitems (niet de Mysterie voedselzak, die blijft een bewuste,
# handmatige gok).

def slaap_cooldown_uur() -> float:
    """/slaap: instant volle energie, kost honger, max 1x per dag per pet."""
    echt = balans.get_float("slaap_cooldown_uur_echt", 24)
    return echt / _dev_versnelling() if config.ENVIRONMENT == "dev" else echt


def slaap_honger_kost() -> int:
    return balans.get_int("slaap_honger_kost", 20)


def blessure_duur_uur() -> float:
    """Tijdelijk niet inzetbaar na een verloren gevecht-matchup."""
    echt = balans.get_float("blessure_duur_uur_echt", 2)
    return echt / _dev_versnelling() if config.ENVIRONMENT == "dev" else echt


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

    huisdier.honger = max(0, huisdier.honger - int(verstreken_minuten // honger_verval_minuten()))

    if huisdier.status == PetStatus.rust or huisdier.zelfreinigend_actief:
        huisdier.energie = min(100, huisdier.energie + int(verstreken_minuten // energie_herstel_minuten()))
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

    herstel_per_item = balans.voer_effecten()
    for item_naam in balans.voerbak_voer(huisdier.voerbak_niveau):
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
            huisdier.honger = min(100, huisdier.honger + herstel_per_item[item_naam])


def inzetbaarheid_probleem(huisdier: Huisdier) -> str | None:
    """None als de pet aan het werk gezet/in team geplaatst mag worden, anders de foutmelding."""
    if huisdier.geblesseerd_tot is not None and huisdier.geblesseerd_tot > _nu():
        resterend = (huisdier.geblesseerd_tot - _nu()).total_seconds() / 3600
        return f"**{huisdier.naam}** is geblesseerd na een gevecht en kan nog niet ingezet worden (nog {resterend:.1f} uur)."
    minimum = energie_minimum()
    if huisdier.energie < minimum:
        return f"**{huisdier.naam}** heeft te weinig energie om ingezet te worden (onder {minimum})."
    if huisdier.honger <= 0:
        return f"**{huisdier.naam}** heeft honger en kan niet ingezet worden. Verzorg de pet eerst met `/verzorg`."
    return None
