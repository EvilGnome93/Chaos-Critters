"""Elementen & contra's voor gevechten. Zie projectbrief-backlog en
docs/dev-status.md. Contra-cirkel Vuur > Lucht > Grond > Water > Vuur,
plus Chaos als 5e grillig element zonder vaste contra.
"""

import random

from sqlalchemy import select

from db.models import Element, PetSoort

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

BONUS = 1.15
MALUS = 0.90


def emoji(element: Element | None) -> str:
    return EMOJI.get(element, "❓")


def elementen_modifier(eigen: Element | None, tegenstander: Element | None) -> float:
    """Multiplier op de macht van 'eigen' in een matchup tegen 'tegenstander'.
    Chaos aan een van beide kanten maakt de uitkomst willekeurig (bonus,
    malus, of neutraal) i.p.v. de vaste contra-cirkel te volgen."""
    if eigen is None or tegenstander is None:
        return 1.0
    if eigen == Element.chaos or tegenstander == Element.chaos:
        return random.choice([BONUS, MALUS, 1.0])
    if STERKER_TEGEN.get(eigen) == tegenstander:
        return BONUS
    if STERKER_TEGEN.get(tegenstander) == eigen:
        return MALUS
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
