"""Check van /craft (2026-07-28, uitkomst van de balans-audit vraag 3):
recept-items krijgen een aparte preview + bevestigingsstap i.p.v. de
/shop-foutmelding-bij-tekort. Ook een korte regressiecheck dat /shop na de
_koop_item-refactor nog steeds gewoon werkt.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from cogs.verzorging import RECEPT_KOSTEN, VerzorgingCog
from db.engine import async_session
from db.models import InventarisItem, Item, Speler

SPELER = 999999999999999971


def fake_interaction(user_id: int) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    bericht = MagicMock()
    bericht.edit = AsyncMock()
    interaction.original_response = AsyncMock(return_value=bericht)
    return interaction


async def _geef_item(session, item_naam: str, aantal: int) -> None:
    item = await session.scalar(select(Item).where(Item.naam == item_naam))
    stmt = insert(InventarisItem).values(speler_id=SPELER, item_id=item.id, aantal=aantal)
    stmt = stmt.on_conflict_do_update(
        index_elements=["speler_id", "item_id"], set_={"aantal": InventarisItem.aantal + aantal}
    )
    await session.execute(stmt)


async def test_craft_overzicht() -> None:
    print("-- /craft zonder item: overzicht --")
    cog = VerzorgingCog(bot=MagicMock())
    interactie = fake_interaction(SPELER)
    await cog.craft.callback(cog, interactie)
    embed = interactie.response.send_message.call_args.kwargs["embed"]
    veldnamen = {f.name for f in embed.fields}
    print(f"Aantal recept-items in overzicht: {len(veldnamen)} (verwacht {len(RECEPT_KOSTEN)})")
    assert veldnamen == set(RECEPT_KOSTEN.keys())
    print("Overzicht toont alle recept-items.")


async def test_craft_lijst() -> None:
    print("\n-- /craft-lijst (tijdelijk commando): zelfde overzicht --")
    cog = VerzorgingCog(bot=MagicMock())
    interactie = fake_interaction(SPELER)
    await cog.craft_lijst.callback(cog, interactie)
    embed = interactie.response.send_message.call_args.kwargs["embed"]
    veldnamen = {f.name for f in embed.fields}
    assert veldnamen == set(RECEPT_KOSTEN.keys())
    print("/craft-lijst toont hetzelfde overzicht.")


async def test_craft_onbekend_item() -> None:
    print("\n-- /craft met een item zonder recept --")
    cog = VerzorgingCog(bot=MagicMock())
    interactie = fake_interaction(SPELER)
    await cog.craft.callback(cog, interactie, item="Basis brokjes")
    bericht = interactie.response.send_message.call_args[0][0]
    print(f"Basis brokjes (geen recept): {bericht}")
    assert "geen grondstof-recept" in bericht


async def test_craft_preview_en_bevestigen() -> None:
    print("\n-- /craft preview (te weinig) -> aanvullen -> bevestigen --")
    cog = VerzorgingCog(bot=MagicMock())
    try:
        async with async_session() as session:
            session.add(Speler(discord_id=SPELER, currency=1000, mmr=1000, volgend_pet_nummer=1))
            await session.commit()

        # Simpele voerbak: Water x2 + Fruit x2. Nog niets gegeven -> preview
        # moet kruisjes tonen en Bevestigen moet uitgeschakeld zijn.
        interactie1 = fake_interaction(SPELER)
        await cog.craft.callback(cog, interactie1, item="Simpele voerbak", aantal=1)
        embed1 = interactie1.response.send_message.call_args.kwargs["embed"]
        view1 = interactie1.response.send_message.call_args.kwargs["view"]
        print(f"Preview zonder grondstoffen: {embed1.fields[0].value}")
        assert "❌" in embed1.fields[0].value
        assert view1.bevestigen.disabled is True

        # Genoeg grondstoffen geven, preview opnieuw.
        async with async_session() as session:
            await _geef_item(session, "Water", 2)
            await _geef_item(session, "Fruit", 2)
            await session.commit()

        interactie2 = fake_interaction(SPELER)
        await cog.craft.callback(cog, interactie2, item="Simpele voerbak", aantal=1)
        embed2 = interactie2.response.send_message.call_args.kwargs["embed"]
        view2 = interactie2.response.send_message.call_args.kwargs["view"]
        print(f"Preview met genoeg grondstoffen: {embed2.fields[0].value}")
        assert "❌" not in embed2.fields[0].value
        assert view2.bevestigen.disabled is False

        # Bevestigen indrukken -> echte aankoop.
        interactie_bevestig = fake_interaction(SPELER)
        await view2.bevestigen.callback(interactie_bevestig)
        eind_bericht = interactie_bevestig.response.edit_message.call_args.kwargs["content"]
        print(f"Na bevestigen: {eind_bericht}")
        assert "Gekocht" in eind_bericht and "Simpele voerbak" in eind_bericht

        async with async_session() as session:
            water = await session.scalar(select(Item).where(Item.naam == "Water"))
            water_inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == SPELER, InventarisItem.item_id == water.id
                )
            )
            print(f"Water over: {water_inv.aantal} (verwacht 0)")
            assert water_inv.aantal == 0
        print("Preview + bevestigen werken correct.")
    finally:
        async with async_session() as session:
            await session.execute(InventarisItem.__table__.delete().where(InventarisItem.speler_id == SPELER))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == SPELER))
            await session.commit()
        print("Testdata opgeruimd.")


async def test_shop_regressie() -> None:
    print("\n-- Regressie: /shop koopt nog steeds gewoon (na _koop_item-refactor) --")
    cog = VerzorgingCog(bot=MagicMock())
    try:
        async with async_session() as session:
            session.add(Speler(discord_id=SPELER, currency=1000, mmr=1000, volgend_pet_nummer=1))
            await session.commit()

        interactie = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie, item="Basis brokjes", aantal=2)
        bericht = interactie.response.send_message.call_args[0][0]
        print(f"Koop Basis brokjes x2: {bericht}")
        assert "Gekocht" in bericht and "Basis brokjes" in bericht
        print("/shop werkt nog steeds.")
    finally:
        async with async_session() as session:
            await session.execute(InventarisItem.__table__.delete().where(InventarisItem.speler_id == SPELER))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == SPELER))
            await session.commit()
        print("Testdata opgeruimd.")


async def main() -> None:
    await test_craft_overzicht()
    await test_craft_lijst()
    await test_craft_onbekend_item()
    await test_craft_preview_en_bevestigen()
    await test_shop_regressie()
    print("\nAlle checks geslaagd.")


if __name__ == "__main__":
    asyncio.run(main())
