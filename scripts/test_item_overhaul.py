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


def _verstreken(minuten: float) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minuten)


def _pet_stub(**overrides) -> Huisdier:
    basis = dict(
        status=PetStatus.werkplek, honger=50, energie=50,
        voerbak_niveau=None, zelfreinigend_actief=False,
        laatste_verzorging_op=_verstreken(ENERGIE_HERSTEL_MINUTEN * 10),
    )
    basis.update(overrides)
    return Huisdier(**basis)


def test_sync_stats_passief_effect() -> None:
    print("-- sync_stats: passieve voerbak/zelfreinigend-effecten (pure unit-test) --")

    # Voerbak = voer -> geeft passief HONGER terug (2026-07-27, verzoek van
    # de gebruiker: "voerbak geeft toch echt voer, niet energie" — logische
    # correctie op de eerste versie hieronder).
    geen = _pet_stub(honger=50, laatste_verzorging_op=_verstreken(HONGER_VERVAL_MINUTEN * 10))
    sync_stats(geen)
    print(f"Zonder voerbak: honger {geen.honger} (verwacht < 50, normaal verval)")
    assert geen.honger < 50

    simpel = _pet_stub(honger=50, voerbak_niveau="simpel", laatste_verzorging_op=_verstreken(HONGER_VERVAL_MINUTEN * 10))
    sync_stats(simpel)
    print(f"Simpele voerbak: honger {simpel.honger} (verwacht > zonder voerbak, vult helft van verval aan)")
    assert simpel.honger > geen.honger

    slim = _pet_stub(honger=50, voerbak_niveau="slim", laatste_verzorging_op=_verstreken(HONGER_VERVAL_MINUTEN * 10))
    sync_stats(slim)
    print(f"Slimme voerbak: honger {slim.honger} (verwacht == 50, vult volledig verval aan, netto stabiel)")
    assert slim.honger == 50

    # Zelfreinigend systeem: laat ENERGIE ook buiten rust herstellen (het
    # effect dat voorheen aan de voerbak hing).
    zonder_zelfreinigend = _pet_stub(energie=50, laatste_verzorging_op=_verstreken(ENERGIE_HERSTEL_MINUTEN * 10))
    sync_stats(zonder_zelfreinigend)
    print(f"Zonder zelfreinigend, buiten rust: energie bleef {zonder_zelfreinigend.energie} (verwacht ongewijzigd, 50)")
    assert zonder_zelfreinigend.energie == 50

    met_zelfreinigend = _pet_stub(
        energie=50, zelfreinigend_actief=True, laatste_verzorging_op=_verstreken(ENERGIE_HERSTEL_MINUTEN * 10)
    )
    sync_stats(met_zelfreinigend)
    print(f"Met zelfreinigend, buiten rust: energie {met_zelfreinigend.energie} (verwacht > 50)")
    assert met_zelfreinigend.energie > 50
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
            water = await session.scalar(select(Item).where(Item.naam == "Water"))
            fruit = await session.scalar(select(Item).where(Item.naam == "Fruit"))
            session.add(InventarisItem(speler_id=SPELER, item_id=water.id, aantal=5))
            session.add(InventarisItem(speler_id=SPELER, item_id=fruit.id, aantal=5))
            await session.commit()

        # Simpele voerbak kopen (kost ook Water + Fruit sinds de balans-audit) en uitrusten.
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

        # Slimme voerbak kopen zonder Schroot/Erts moet mislukken (2 ingrediënten sinds de balans-audit).
        interactie3 = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie3, item="Slimme voerbak", aantal=1)
        bericht3 = interactie3.response.send_message.call_args[0][0]
        print(f"Koop Slimme voerbak zonder Schroot: {bericht3}")
        assert "vereist ook" in bericht3 and "Schroot" in bericht3

        # Geef genoeg Schroot, maar nog geen Erts: moet mislukken op het 2e ingrediënt.
        async with async_session() as session:
            schroot = await session.scalar(select(Item).where(Item.naam == "Schroot"))
            session.add(InventarisItem(speler_id=SPELER, item_id=schroot.id, aantal=40))
            await session.commit()

        interactie3b = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie3b, item="Slimme voerbak", aantal=1)
        bericht3b = interactie3b.response.send_message.call_args[0][0]
        print(f"Koop Slimme voerbak met Schroot maar zonder Erts: {bericht3b}")
        assert "vereist ook" in bericht3b and "Erts" in bericht3b

        # Geef ook genoeg Erts en probeer opnieuw.
        async with async_session() as session:
            erts = await session.scalar(select(Item).where(Item.naam == "Erts"))
            session.add(InventarisItem(speler_id=SPELER, item_id=erts.id, aantal=20))
            await session.commit()

        interactie4 = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie4, item="Slimme voerbak", aantal=1)
        bericht4 = interactie4.response.send_message.call_args[0][0]
        print(f"Koop Slimme voerbak met genoeg Schroot + Erts: {bericht4}")
        assert "Gekocht" in bericht4 and "Schroot" in bericht4 and "Erts" in bericht4

        async with async_session() as session:
            schroot_inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == SPELER, InventarisItem.item_id == schroot.id
                )
            )
            erts_inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == SPELER, InventarisItem.item_id == erts.id
                )
            )
            print(f"Schroot over: {schroot_inv.aantal} (verwacht 0), Erts over: {erts_inv.aantal} (verwacht 0)")
            assert schroot_inv.aantal == 0
            assert erts_inv.aantal == 0

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
