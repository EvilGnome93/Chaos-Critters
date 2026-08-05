"""Check van de chaos-events (2026-08-05, verzoek van de gebruiker).

Wat hier bewaakt wordt:
1. Zonder lopend event is elke factor 1.0, dus alle aanroepers kunnen
   onvoorwaardelijk vermenigvuldigen zonder dat er iets verandert.
2. Een incense verlaagt de spawn-drempel echt.
3. Een sterrenregen verschuift de spawnkans merkbaar naar Rare en hoger.
4. Grondstoffenregen en muntregen raken elkaar niet: een verdubbeling van
   de grondstoffen mag de coins niet stiekem meeverdubbelen.
5. Een event loopt vanzelf af zodra eindigt_op verstreken is, zonder dat er
   iets hoeft te draaien.
6. De sterkte is een momentopname: een balanswijziging tijdens een lopend
   event verandert de spelregels niet.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, update

from cogs.vangen import _kies_random_soort, _nieuwe_drempel
from db.engine import async_session
from db.models import Event, Instelling, Tier
from utils import balans, events
from utils.gevechten import currency_beloning

TREKKINGEN = 400


async def _opruimen() -> None:
    async with async_session() as session:
        await session.execute(delete(Event))
        await session.commit()
    await events.laad()


async def _start(sleutel: str, minuten: int = 60) -> Event:
    async with async_session() as session:
        event = await events.start(session, sleutel, duur_minuten=minuten)
        await session.commit()
        session.expunge_all()
    await events.laad()
    return event


async def _gemiddelde_drempel() -> float:
    return sum(_nieuwe_drempel() for _ in range(TREKKINGEN)) / TREKKINGEN


async def _aandeel_zeldzaam() -> float:
    """Welk deel van de spawns tier 3+ is. Statistisch, dus met een royale
    marge in de asserts — dit test de richting, niet een exact getal."""
    telling = Counter()
    async with async_session() as session:
        for _ in range(TREKKINGEN):
            _, tier = await _kies_random_soort(session)
            telling[tier.id >= events.ZELDZAAM_VANAF_TIER] += 1
    return telling[True] / TREKKINGEN


async def test_geen_event_is_neutraal() -> None:
    print("-- Zonder event verandert er niets --")
    assert events.actieve() == []
    for sleutel in events.TYPES:
        assert events.factor(sleutel) == 1.0, f"'{sleutel}' is niet neutraal zonder event"
        assert not events.is_actief(sleutel)
    print(f"Alle {len(events.TYPES)} factoren staan op 1.0.")


async def test_incense_verlaagt_de_drempel() -> None:
    print("\n-- Incense: sneller spawnen --")
    voor = await _gemiddelde_drempel()
    event = await _start("incense")
    na = await _gemiddelde_drempel()
    verwacht = voor * float(event.sterkte)
    print(f"Gemiddelde drempel: {voor:.1f} berichten -> {na:.1f} (verwacht ~{verwacht:.1f})")
    assert na < voor, "de drempel ging niet omlaag"
    # Ruime marge: de drempel is per trekking willekeurig en wordt afgerond.
    assert abs(na - verwacht) < max(2.0, verwacht * 0.25)

    await _opruimen()
    terug = await _gemiddelde_drempel()
    print(f"Na afloop weer {terug:.1f} berichten")
    assert abs(terug - voor) < voor * 0.25


async def test_sterrenregen_verschuift_de_tiers() -> None:
    print("\n-- Sterrenregen: meer zeldzame spawns --")
    voor = await _aandeel_zeldzaam()
    await _start("sterrenregen")
    na = await _aandeel_zeldzaam()
    print(f"Aandeel Rare of hoger: {voor:.0%} -> {na:.0%}")
    assert na > voor, "sterrenregen leverde niet meer zeldzame spawns op"
    await _opruimen()


async def test_grondstoffen_en_coins_staan_los() -> None:
    """Beide events raken dezelfde berekening in cogs/werk.py, dus de
    interessante vraag is of ze elkaar niet per ongeluk versterken."""
    print("\n-- Grondstoffenregen en muntregen beïnvloeden elkaar niet --")
    basis_grondstof, basis_coins = 10, 20

    def bereken() -> tuple[int, int]:
        # Zelfde volgorde als cogs/werk.py: coins uit de basis, grondstoffen
        # apart opgehoogd.
        coins = round(basis_coins * events.factor("dubbele_coins"))
        grondstof = round(basis_grondstof * events.factor("dubbele_grondstoffen"))
        return grondstof, coins

    await _start("dubbele_grondstoffen")
    grondstof, coins = bereken()
    print(f"Alleen grondstoffenregen: {grondstof} grondstoffen, {coins} coins")
    assert grondstof == basis_grondstof * 2
    assert coins == basis_coins, "de grondstoffenregen verdubbelde ook de coins"
    await _opruimen()

    await _start("dubbele_coins")
    grondstof, coins = bereken()
    print(f"Alleen muntregen: {grondstof} grondstoffen, {coins} coins")
    assert grondstof == basis_grondstof, "de muntregen verdubbelde ook de grondstoffen"
    assert coins == basis_coins * 2

    # Muntregen raakt ook gevechten.
    zonder = None
    await _opruimen()
    zonder = currency_beloning(1000)
    await _start("dubbele_coins")
    met = currency_beloning(1000)
    print(f"Gevecht-beloning bij 1000 MMR: {zonder} -> {met}")
    assert met == zonder * 2
    await _opruimen()


async def test_event_loopt_vanzelf_af() -> None:
    print("\n-- Een verlopen event is vanzelf niet meer actief --")
    event = await _start("incense", minuten=60)
    assert events.is_actief("incense")

    # Terugzetten in de tijd zonder de cache te herladen: zo bewijst dit dat
    # actieve() op de klok filtert en niet op een herlaadmoment.
    async with async_session() as session:
        await session.execute(
            update(Event).where(Event.id == event.id).values(eindigt_op=events._nu() - timedelta(minutes=1))
        )
        await session.commit()
    for gecached in events._cache:
        if gecached.id == event.id:
            gecached.eindigt_op = events._nu() - timedelta(minutes=1)

    print(f"is_actief zonder herladen: {events.is_actief('incense')}")
    assert not events.is_actief("incense"), "een verlopen event telt nog steeds mee"
    assert events.factor("incense") == 1.0
    await _opruimen()


async def test_sterkte_is_een_momentopname() -> None:
    print("\n-- Een balanswijziging raakt een lopend event niet --")
    event = await _start("dubbele_coins")
    oorspronkelijk = float(event.sterkte)
    print(f"Gestart met sterkte {oorspronkelijk}")

    async with async_session() as session:
        instelling = await session.get(Instelling, "event_dubbele_coins_sterkte")
        oude_waarde = instelling.waarde
        instelling.waarde = "9.0"
        await session.commit()
    await balans.laad()
    try:
        print(f"Instelling staat nu op 9.0, lopend event geeft {events.factor('dubbele_coins')}")
        assert events.factor("dubbele_coins") == oorspronkelijk, (
            "een lopend event volgde de nieuwe instelling — dan verandert de "
            "beloning halverwege"
        )
    finally:
        async with async_session() as session:
            instelling = await session.get(Instelling, "event_dubbele_coins_sterkte")
            instelling.waarde = oude_waarde
            await session.commit()
        await balans.laad()
    await _opruimen()


async def test_onbekend_type_wordt_geweigerd() -> None:
    print("\n-- Een onbekend event-type is een harde fout --")
    async with async_session() as session:
        try:
            await events.start(session, "bestaat-niet")
        except ValueError as e:
            print(f"Geweigerd: {e}")
        else:
            raise AssertionError("onbekend event-type werd geaccepteerd")


async def main() -> None:
    await balans.laad()
    try:
        await _opruimen()
        await test_geen_event_is_neutraal()
        await test_incense_verlaagt_de_drempel()
        await test_sterrenregen_verschuift_de_tiers()
        await test_grondstoffen_en_coins_staan_los()
        await test_event_loopt_vanzelf_af()
        await test_sterkte_is_een_momentopname()
        await test_onbekend_type_wordt_geweigerd()
        print("\nAlle checks geslaagd.")
    finally:
        await _opruimen()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
