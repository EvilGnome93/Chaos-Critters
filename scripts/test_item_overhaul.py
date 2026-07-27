"""Check van Item-overhaul deel 1 (2026-07-27, verzoek van de gebruiker):
Simpele/Slimme voerbak en Zelfreinigend systeem krijgen hun beloofde
passieve effect, per pet uit te rusten via het nieuwe /uitrusten-commando.
Slimme voerbak kost nu ook grondstoffen (Schroot) naast Chaos Coins.

Test 1 is een pure unit-test van sync_stats() (geen DB nodig). Tests 2+
draaien end-to-end tegen de dev-DB via de echte commands. Ruimt zijn eigen
testdata op aan het eind.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.verzorging import VerzorgingCog
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, PetSoort, PetStatus, Speler
from utils.stats import ENERGIE_HERSTEL_MINUTEN, HONGER_VERVAL_MINUTEN, sync_stats

SPELER = 999999999999999941


def fake_interaction(user_id: int) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    return interaction


def fake_choice(value: str) -> MagicMock:
    choice = MagicMock()
    choice.value = value
    return choice


def _pet_stub(**overrides) -> Huisdier:
    basis = dict(
        status=PetStatus.werkplek, honger=50, energie=50,
        voerbak_niveau=None, zelfreinigend_actief=False,
        laatste_verzorging_op=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=ENERGIE_HERSTEL_MINUTEN * 10),
    )
    basis.update(overrides)
    return Huisdier(**basis)


def test_sync_stats_passief_effect() -> None:
    print("-- sync_stats: passieve voerbak/zelfreinigend-effecten (pure unit-test) --")

    geen = _pet_stub()
    sync_stats(geen)
    print(f"Zonder voerbak, buiten rust: energie bleef {geen.energie} (verwacht ongewijzigd, 50)")
    assert geen.energie == 50, "energie hoort niet te herstellen buiten rust zonder voerbak"

    simpel = _pet_stub(voerbak_niveau="simpel")
    sync_stats(simpel)
    print(f"Simpele voerbak, buiten rust: energie {simpel.energie} (verwacht > 50, half tempo)")
    assert simpel.energie > 50

    slim = _pet_stub(voerbak_niveau="slim")
    sync_stats(slim)
    print(f"Slimme voerbak, buiten rust: energie {slim.energie} (verwacht > simpel, vol tempo)")
    assert slim.energie > simpel.energie

    zonder_zelfreinigend = _pet_stub(
        status=PetStatus.rust, laatste_verzorging_op=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=HONGER_VERVAL_MINUTEN * 10)
    )
    sync_stats(zonder_zelfreinigend)
    met_zelfreinigend = _pet_stub(
        status=PetStatus.rust, zelfreinigend_actief=True,
        laatste_verzorging_op=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=HONGER_VERVAL_MINUTEN * 10),
    )
    sync_stats(met_zelfreinigend)
    print(
        f"Honger zonder zelfreinigend: {zonder_zelfreinigend.honger}, met zelfreinigend: {met_zelfreinigend.honger} "
        "(verwacht: met > zonder, verval 2x zo traag)"
    )
    assert met_zelfreinigend.honger > zonder_zelfreinigend.honger
    print("Passieve effecten kloppen.")


async def _maak_pet(session, speler_id: int, naam: str) -> int:
    if await session.get(Speler, speler_id) is None:
        session.add(Speler(discord_id=speler_id, currency=1000, mmr=1000, volgend_pet_nummer=1))
        await session.commit()
    speler = await session.get(Speler, speler_id)
    soort = await session.scalar(select(PetSoort).limit(1))
    pet = Huisdier(
        eigenaar_id=speler_id, soort_id=soort.id, tier_id=soort.tier_id, naam=naam,
        volgnummer=speler.volgend_pet_nummer, gevecht_genen=50, werk_genen=50,
        status=PetStatus.rust, honger=100, energie=100,
    )
    speler.volgend_pet_nummer += 1
    session.add(pet)
    await session.commit()
    await session.refresh(pet)
    return pet.id


async def test_shop_en_uitrusten() -> None:
    print("\n-- /shop grondstof-kosten + /uitrusten (equip/swap/afkoppelen) --")
    cog = VerzorgingCog(bot=MagicMock())
    pet_id = None
    try:
        async with async_session() as session:
            pet_id = await _maak_pet(session, SPELER, "UitrustingTest")

        # Simpele voerbak kopen (geen grondstof-eis) en uitrusten.
        interactie = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie, item="Simpele voerbak", aantal=1)
        bericht = interactie.response.send_message.call_args.kwargs.get("embed") or \
            interactie.response.send_message.call_args[0][0]
        print(f"Koop Simpele voerbak: {bericht}")
        assert "Gekocht" in str(bericht)

        interactie2 = fake_interaction(SPELER)
        await cog.uitrusten.callback(cog, interactie2, pet_id=1, item=fake_choice("Simpele voerbak"))
        bericht2 = interactie2.response.send_message.call_args[0][0]
        print(f"Uitrusten: {bericht2}")
        assert "uitgerust" in bericht2

        async with async_session() as session:
            pet = await session.get(Huisdier, pet_id)
            assert pet.voerbak_niveau == "simpel"

        # Slimme voerbak kopen zonder genoeg Schroot moet mislukken.
        interactie3 = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie3, item="Slimme voerbak", aantal=1)
        bericht3 = interactie3.response.send_message.call_args[0][0]
        print(f"Koop Slimme voerbak zonder Schroot: {bericht3}")
        assert "vereist ook" in bericht3

        # Geef genoeg Schroot en probeer opnieuw.
        async with async_session() as session:
            schroot = await session.scalar(select(Item).where(Item.naam == "Schroot"))
            session.add(InventarisItem(speler_id=SPELER, item_id=schroot.id, aantal=10))
            await session.commit()

        interactie4 = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie4, item="Slimme voerbak", aantal=1)
        bericht4 = interactie4.response.send_message.call_args[0][0]
        print(f"Koop Slimme voerbak met genoeg Schroot: {bericht4}")
        assert "Gekocht" in bericht4 and "Schroot" in bericht4

        async with async_session() as session:
            schroot_inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == SPELER, InventarisItem.item_id == schroot.id
                )
            )
            print(f"Schroot over: {schroot_inv.aantal} (verwacht 5, was 10, -5 gebruikt)")
            assert schroot_inv.aantal == 5

        # Slimme voerbak uitrusten terwijl Simpele al actief is -> auto-swap.
        interactie5 = fake_interaction(SPELER)
        await cog.uitrusten.callback(cog, interactie5, pet_id=1, item=fake_choice("Slimme voerbak"))
        bericht5 = interactie5.response.send_message.call_args[0][0]
        print(f"Swap naar Slimme voerbak: {bericht5}")
        assert "Simpele voerbak" in bericht5 and "kwam terug" in bericht5

        async with async_session() as session:
            pet = await session.get(Huisdier, pet_id)
            assert pet.voerbak_niveau == "slim"
            simpele_item = await session.scalar(select(Item).where(Item.naam == "Simpele voerbak"))
            simpele_inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == SPELER, InventarisItem.item_id == simpele_item.id
                )
            )
            assert simpele_inv.aantal == 1, "Simpele voerbak had terug moeten komen in de inventaris"

        # Afkoppelen van de Slimme voerbak.
        interactie6 = fake_interaction(SPELER)
        await cog.uitrusten.callback(
            cog, interactie6, pet_id=1, item=fake_choice("Slimme voerbak"), afkoppelen=True
        )
        bericht6 = interactie6.response.send_message.call_args[0][0]
        print(f"Afkoppelen: {bericht6}")
        assert "afgekoppeld" in bericht6

        async with async_session() as session:
            pet = await session.get(Huisdier, pet_id)
            assert pet.voerbak_niveau is None
            slimme_item = await session.scalar(select(Item).where(Item.naam == "Slimme voerbak"))
            slimme_inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == SPELER, InventarisItem.item_id == slimme_item.id
                )
            )
            assert slimme_inv.aantal == 1
        print("Shop-grondstofkosten en /uitrusten (equip/swap/afkoppelen) werken correct.")
    finally:
        async with async_session() as session:
            if pet_id:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id == pet_id))
            await session.execute(InventarisItem.__table__.delete().where(InventarisItem.speler_id == SPELER))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == SPELER))
            await session.commit()
        print("Testdata opgeruimd.")


async def main() -> None:
    test_sync_stats_passief_effect()
    await test_shop_en_uitrusten()
    print("\nAlle checks geslaagd.")


if __name__ == "__main__":
    asyncio.run(main())
