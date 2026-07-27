"""Check van "Doel voor grondstoffen" (2026-07-27, verzoek van de gebruiker):
de 11 grondstoffen die tot nu toe nergens voor te gebruiken waren, hebben nu
allemaal een recept-kosten aan een bestaand shop-item hangen (RECEPT_KOSTEN
in cogs/verzorging.py), inclusief twee multi-ingrediënt recepten
(Werk-elixer, Extra match token). Ook: Extra match token's prijs omhoog
(50 -> 150) als fix voor het gedocumenteerde ranked-daglimiet-lek.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.verzorging import RECEPT_KOSTEN, VerzorgingCog
from db.engine import async_session
from db.models import InventarisItem, Item, ItemType, Speler

SPELER = 999999999999999951


def fake_interaction(user_id: int) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    return interaction


def test_alle_grondstoffen_hebben_een_recept() -> None:
    print("-- Alle 12 grondstof/materiaal-items hebben nu minstens 1 recept --")
    gebruikte_grondstoffen = {naam for recept in RECEPT_KOSTEN.values() for naam, _ in recept}
    verwacht = {
        "Groente", "Algen", "Schroot", "Takken", "Maanschijnkristal", "Erts",
        "Fruit", "Water", "Spijker", "Bladeren", "Sterrenstof", "Edelsteen",
    }
    ontbrekend = verwacht - gebruikte_grondstoffen
    print(f"Gebruikt in recepten: {sorted(gebruikte_grondstoffen)}")
    print(f"Ontbrekend: {ontbrekend or 'geen'}")
    assert not ontbrekend, f"Deze grondstoffen hebben nog geen recept: {ontbrekend}"


async def _geef_item(session, speler_id: int, item_naam: str, aantal: int) -> None:
    item = await session.scalar(select(Item).where(Item.naam == item_naam))
    session.add(InventarisItem(speler_id=speler_id, item_id=item.id, aantal=aantal))


async def test_multi_ingredient_recept() -> None:
    print("\n-- Multi-ingrediënt recept: Werk-elixer (Erts + Spijker) --")
    cog = VerzorgingCog(bot=MagicMock())
    try:
        async with async_session() as session:
            session.add(Speler(discord_id=SPELER, currency=1000, mmr=1000, volgend_pet_nummer=1))
            await _geef_item(session, SPELER, "Erts", 3)
            # Bewust nog geen Spijker: moet mislukken op het 2e ingrediënt.
            await session.commit()

        interactie = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie, item="Werk-elixer", aantal=1)
        bericht = interactie.response.send_message.call_args[0][0]
        print(f"Alleen Erts (geen Spijker): {bericht}")
        assert "vereist ook" in bericht and "Spijker" in bericht

        async with async_session() as session:
            await _geef_item(session, SPELER, "Spijker", 2)
            await session.commit()

        interactie2 = fake_interaction(SPELER)
        await cog.shop.callback(cog, interactie2, item="Werk-elixer", aantal=1)
        bericht2 = interactie2.response.send_message.call_args[0][0]
        print(f"Erts + Spijker: {bericht2}")
        assert "Gekocht" in bericht2 and "Erts" in bericht2 and "Spijker" in bericht2

        async with async_session() as session:
            erts = await session.scalar(select(Item).where(Item.naam == "Erts"))
            spijker = await session.scalar(select(Item).where(Item.naam == "Spijker"))
            erts_inv = await session.scalar(
                select(InventarisItem).where(InventarisItem.speler_id == SPELER, InventarisItem.item_id == erts.id)
            )
            spijker_inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == SPELER, InventarisItem.item_id == spijker.id
                )
            )
            print(f"Erts over: {erts_inv.aantal} (verwacht 0), Spijker over: {spijker_inv.aantal} (verwacht 0)")
            assert erts_inv.aantal == 0
            assert spijker_inv.aantal == 0
        print("Multi-ingrediënt recept werkt: beide grondstoffen correct afgeboekt.")
    finally:
        async with async_session() as session:
            await session.execute(InventarisItem.__table__.delete().where(InventarisItem.speler_id == SPELER))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == SPELER))
            await session.commit()
        print("Testdata opgeruimd.")


async def test_extra_match_token_prijs_en_recept() -> None:
    print("\n-- Extra match token: prijs 50 -> 150, plus recept (ranked-lek-fix) --")
    async with async_session() as session:
        token = await session.scalar(select(Item).where(Item.naam == "Extra match token"))
        print(f"Huidige prijs: {token.prijs} (verwacht 150)")
        assert token.prijs == 150
        assert token.type == ItemType.boost
    assert RECEPT_KOSTEN["Extra match token"] == [("Maanschijnkristal", 2), ("Edelsteen", 1)]
    print("Prijs en recept kloppen.")


async def main() -> None:
    test_alle_grondstoffen_hebben_een_recept()
    await test_multi_ingredient_recept()
    await test_extra_match_token_prijs_en_recept()
    print("\nAlle checks geslaagd.")


if __name__ == "__main__":
    asyncio.run(main())
