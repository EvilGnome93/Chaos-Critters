"""Elementen & contra's voor gevechten. Zie projectbrief-backlog en
docs/dev-status.md. Contra-cirkel Vuur > Lucht > Grond > Water > Vuur,
plus Chaos als 5e grillig element zonder vaste contra.
"""

import random

from sqlalchemy import select

from db.models import Element, PetSoort
from utils import balans

EMOJI = {
    Element.grond: "⛰️",
    Element.water: "🌊",
    Element.lucht: "🌪️",
    Element.vuur: "🔥",
    Element.chaos: "🌀",
}

# Elk element hierin is sterker tegen zijn waarde (bijv. Vuur > Lucht).
STERKER_TEGEN = {
    Element.vuur: Element.lucht,
    Element.lucht: Element.grond,
    Element.grond: Element.water,
    Element.water: Element.vuur,
}

# 2026-07-30, admin panel fase 2: bewijs-blok voor de balans-cache
# (utils/balans.py) — was hardcoded BONUS/MALUS, nu instelbaar via de
# portal. Elke matchup leest de actuele waarde i.p.v. een module-constante
# op import-tijd, dus een portal-wijziging werkt meteen op het volgende
# gevecht.
def _bonus() -> float:
    return balans.get_float("elementen_bonus", 1.15)


def _malus() -> float:
    return balans.get_float("elementen_malus", 0.90)


def emoji(element: Element | None) -> str:
    return EMOJI.get(element, "❓")


def elementen_modifier(eigen: Element | None, tegenstander: Element | None) -> float:
    """Multiplier op de macht van 'eigen' in een matchup tegen 'tegenstander'.
    Chaos aan een van beide kanten maakt de uitkomst willekeurig (bonus,
    malus, of neutraal) i.p.v. de vaste contra-cirkel te volgen."""
    if eigen is None or tegenstander is None:
        return 1.0
    if eigen == Element.chaos or tegenstander == Element.chaos:
        return random.choice([_bonus(), _malus(), 1.0])
    if STERKER_TEGEN.get(eigen) == tegenstander:
        return _bonus()
    if STERKER_TEGEN.get(tegenstander) == eigen:
        return _malus()
    return 1.0


def willekeurig_element() -> Element:
    """Voor de gesimuleerde PvE-tegenstander, die geen echte pet-soort (en
    dus geen vast element) heeft: elke matchup een nieuw willekeurig element."""
    return random.choice(list(Element))


async def soort_elementen(session) -> dict[int, Element | None]:
    """soort_id -> element, voor plekken die per pet snel het element van de
    eigen soort willen opzoeken zonder een aparte query per pet."""
    rijen = (await session.execute(select(PetSoort.id, PetSoort.element))).all()
    return dict(rijen)


async def soort_element_emojis(session) -> dict[int, str]:
    """soort_id -> element-emoji, voor weergave (/lijst, /team)."""
    return {soort_id: emoji(element) for soort_id, element in (await soort_elementen(session)).items()}
