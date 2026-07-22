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

import config
from db.models import Huisdier, PetStatus

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

_SLAAP_COOLDOWN_UUR_ECHT = 24  # /slaap: instant volle energie, kost honger, max 1x per dag per pet
SLAAP_COOLDOWN_UUR = (
    _SLAAP_COOLDOWN_UUR_ECHT / _DEV_VERSNELLING if config.ENVIRONMENT == "dev" else _SLAAP_COOLDOWN_UUR_ECHT
)
SLAAP_HONGER_KOST = 20


def _nu() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sync_stats(huisdier: Huisdier, nu: datetime | None = None) -> None:
    """Werkt honger/energie bij op basis van verstreken tijd."""
    nu = nu or _nu()
    verstreken_minuten = (nu - huisdier.laatste_verzorging_op).total_seconds() / 60
    if verstreken_minuten <= 0:
        return

    huisdier.honger = max(0, huisdier.honger - int(verstreken_minuten // HONGER_VERVAL_MINUTEN))
    if huisdier.status == PetStatus.rust:
        huisdier.energie = min(100, huisdier.energie + int(verstreken_minuten // ENERGIE_HERSTEL_MINUTEN))
    huisdier.laatste_verzorging_op = nu


def inzetbaarheid_probleem(huisdier: Huisdier) -> str | None:
    """None als de pet aan het werk gezet/in team geplaatst mag worden, anders de foutmelding."""
    if huisdier.energie < ENERGIE_MINIMUM:
        return f"**{huisdier.naam}** heeft te weinig energie om ingezet te worden (onder {ENERGIE_MINIMUM})."
    if huisdier.honger <= 0:
        return f"**{huisdier.naam}** heeft honger en kan niet ingezet worden. Verzorg de pet eerst met `/verzorg`."
    return None
