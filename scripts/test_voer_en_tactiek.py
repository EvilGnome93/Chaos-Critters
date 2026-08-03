"""Checks voor admin panel fase 2, blok 5 (2026-07-30): de voer-effecten en
de tactiek-variantie komen niet langer uit hardcoded Python-constanten maar
uit de database.

Wat hier bewaakt wordt:
1. De waarden uit de database zijn identiek aan de oude hardcoded waarden,
   dus spelers merken niets van de verhuizing.
2. Een wijziging in de database werkt echt door in het gedrag (voerbak,
   /verzorg, gevechtsvariantie) — dat is het hele punt van blok 5.
3. Een item zonder honger_herstel is geen voer en wordt door geen enkele
   voerbak gepakt.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, update

from cogs.verzorging import _MYSTERIE_VOEDSEL, _toepassen_voeding, voeding_items
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, PetSoort, PetStatus, Speler
from utils import balans, gevechten
from utils.stats import _nu, sync_stats_met_voerbak

SPELER = 999999999999999912

# De waarden zoals ze tot 2026-07-30 hardcoded in utils/stats.py stonden.
# "Vers vlees/vis" zat in VOLLEDIG_HERSTEL_ITEMS; dat is nu 100, wat door de
# klem op 100 exact hetzelfde doet.
OUDE_HERSTEL = {"Basis brokjes": 15, "Graanvrije premium voeding": 40, "Vers vlees/vis": 100}
OUDE_VOERBAK = {
    "simpel": ["Basis brokjes"],
    "slim": ["Basis brokjes", "Graanvrije premium voeding", "Vers vlees/vis"],
}
OUDE_TACTIEK = {
    "aggressief": (-0.25, 0.35),
    "gebalanceerd": (-0.15, 0.15),
    "voorzichtig": (-0.10, 0.10),
}


async def _opruimen() -> None:
    async with async_session() as session:
        await session.execute(delete(InventarisItem).where(InventarisItem.speler_id == SPELER))
        await session.execute(delete(Huisdier).where(Huisdier.eigenaar_id == SPELER))
        await session.execute(delete(Speler).where(Speler.discord_id == SPELER))
        await session.commit()


async def _maak_pet(voerbak_niveau: str | None, honger: int) -> int:
    """Maakt de testspeler + een pet die al een verval-interval geleden
    verzorgd is, en geeft het pet-ID terug."""
    async with async_session() as session:
        speler = await session.get(Speler, SPELER)
        if speler is None:
            session.add(Speler(discord_id=SPELER, volgend_pet_nummer=1))
            await session.commit()

        soort = await session.scalar(select(PetSoort).limit(1))
        pet = Huisdier(
            eigenaar_id=SPELER,
            soort_id=soort.id,
            tier_id=soort.tier_id,
            naam="Voertest",
            volgnummer=1,
            gevecht_genen=50,
            werk_genen=50,
            honger=honger,
            energie=100,
            status=PetStatus.rust,
            voerbak_niveau=voerbak_niveau,
            laatste_verzorging_op=_nu(),
        )
        session.add(pet)
        await session.commit()
        return pet.id


async def _geef_item(itemnaam: str, aantal: int) -> None:
    async with async_session() as session:
        item = await session.scalar(select(Item).where(Item.naam == itemnaam))
        session.add(InventarisItem(speler_id=SPELER, item_id=item.id, aantal=aantal))
        await session.commit()


async def test_waarden_zijn_ongewijzigd() -> None:
    print("-- De database geeft exact de oude hardcoded waarden --")
    print(f"voer_effecten: {balans.voer_effecten()}")
    assert balans.voer_effecten() == OUDE_HERSTEL, "honger-herstel wijkt af van vóór de verhuizing"
    for niveau, verwacht in OUDE_VOERBAK.items():
        gekregen = balans.voerbak_voer(niveau)
        print(f"voerbak '{niveau}': {gekregen}")
        assert gekregen == verwacht, f"voerbak '{niveau}' pakt andere items dan voorheen"
    for tactiek, verwacht in OUDE_TACTIEK.items():
        gekregen = balans.tactiek_variantie(tactiek)
        print(f"tactiek '{tactiek}': {gekregen}")
        assert gekregen == verwacht, f"variantie van '{tactiek}' wijkt af"

    # De Mysterie voedselzak heeft geen eigen honger-effect: die simuleert
    # bij gebruik een willekeurig ánder voedingsitem.
    assert _MYSTERIE_VOEDSEL not in balans.voer_effecten()
    assert _MYSTERIE_VOEDSEL in voeding_items()
    assert _MYSTERIE_VOEDSEL not in balans.voerbak_voer("slim"), "voerbak mag niet gokken met de mysteriezak"
    print("Mysteriezak: wel in /verzorg, geen eigen effect, nooit automatisch gevoerd.")


async def test_voerbak_gebruikt_de_databasewaarden() -> None:
    print("\n-- De voerbak voert op basis van items.honger_herstel --")
    await _maak_pet("simpel", honger=50)
    await _geef_item("Basis brokjes", 2)

    async with async_session() as session:
        pet = await session.scalar(select(Huisdier).where(Huisdier.eigenaar_id == SPELER))
        await sync_stats_met_voerbak(session, pet)
        await session.commit()
        print(f"honger 50 -> {pet.honger} (verwacht 80: 2x Basis brokjes a +15)")
        assert pet.honger == 80

        inv = await session.scalar(select(InventarisItem).where(InventarisItem.speler_id == SPELER))
        print(f"brokjes over: {inv.aantal} (verwacht 0)")
        assert inv.aantal == 0


async def test_wijziging_werkt_meteen_door() -> None:
    print("\n-- Een wijziging in de database verandert het gedrag --")
    async with async_session() as session:
        await session.execute(
            update(Item).where(Item.naam == "Basis brokjes").values(honger_herstel=50)
        )
        await session.commit()
    await balans.laad()

    try:
        assert balans.voer_effecten()["Basis brokjes"] == 50
        async with async_session() as session:
            pet = await session.scalar(select(Huisdier).where(Huisdier.eigenaar_id == SPELER))
            pet.honger = 20
            honger_voor = pet.honger
            _toepassen_voeding(pet, "Basis brokjes")
            print(f"/verzorg met de nieuwe waarde: honger {honger_voor} -> {pet.honger} (verwacht 70)")
            assert pet.honger == 70
            await session.rollback()
    finally:
        # Terugzetten, ook als de assert faalt: dit is de echte spelbalans.
        async with async_session() as session:
            await session.execute(
                update(Item).where(Item.naam == "Basis brokjes").values(honger_herstel=15)
            )
            await session.commit()
        await balans.laad()
    assert balans.voer_effecten()["Basis brokjes"] == 15
    print("Oude waarde weer teruggezet.")


async def test_item_zonder_herstel_is_geen_voer() -> None:
    print("\n-- Een item zonder honger_herstel wordt nooit gevoerd --")
    for naam in balans.voerbak_voer("slim"):
        assert balans.voer_effecten().get(naam), f"'{naam}' staat in een voerbak maar herstelt niets"
    async with async_session() as session:
        geen_voer = (
            await session.execute(
                select(Item.naam).where(Item.honger_herstel.is_(None), Item.voerbak_vanaf.is_not(None))
            )
        ).scalars().all()
    print(f"Items met een voerbak-niveau maar zonder herstel: {geen_voer or 'geen'}")
    assert not geen_voer, "deze items zouden een voerbak laten draaien zonder effect"


def test_tactiek_variantie_in_gevechten() -> None:
    print("\n-- macht_met_tactiek blijft binnen de ingestelde grenzen --")
    for tactiek, (laag, hoog) in OUDE_TACTIEK.items():
        machten = [gevechten.macht_met_tactiek(100.0, tactiek) for _ in range(500)]
        print(f"{tactiek}: {min(machten):.1f} .. {max(machten):.1f} (grenzen {100 * (1 + laag):.0f} .. {100 * (1 + hoog):.0f})")
        assert min(machten) >= 100 * (1 + laag) - 0.001
        assert max(machten) <= 100 * (1 + hoog) + 0.001

    # Onbekende tactiek: viel voorheen terug op een KeyError-vrije lookup en
    # moet nu ook gewoon gebalanceerd gedrag geven, geen crash.
    laag, hoog = balans.tactiek_variantie("bestaat-niet")
    print(f"onbekende tactiek valt terug op gebalanceerd: ({laag}, {hoog})")
    assert (laag, hoog) == OUDE_TACTIEK["gebalanceerd"]


async def main() -> None:
    await balans.laad()
    try:
        await _opruimen()
        await test_waarden_zijn_ongewijzigd()
        await test_voerbak_gebruikt_de_databasewaarden()
        await test_wijziging_werkt_meteen_door()
        await test_item_zonder_herstel_is_geen_voer()
        test_tactiek_variantie_in_gevechten()
        print("\nAlle checks geslaagd.")
    finally:
        await _opruimen()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
