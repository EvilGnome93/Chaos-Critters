"""Check van de werkplekken-uitbreiding (2026-07-26, verzoek van de
gebruiker): gedeelde capaciteit over alle spelers heen wordt afgedwongen,
elke werkplek heeft nu een tweede (zeldzame) grondstof met een kleine kans
per shift, en de eerder ontbrekende 'Mijnschacht'-optie in /werk is
toegevoegd zodat pets met die werkplek-voorkeur er ook echt heen kunnen.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.werk import WerkCog, _nu
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, PetSoort, PetStatus, Speler, Werkplek

SPELERS = [999999999999999931, 999999999999999932, 999999999999999933]


def fake_interaction(user_id: int, guild_id: int | None = 1, channel_id: int = 42) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.user.mention = f"<@{user_id}>"
    interaction.guild_id = guild_id
    interaction.channel_id = channel_id
    interaction.response = AsyncMock()
    return interaction


def fake_choice(value: str) -> MagicMock:
    choice = MagicMock()
    choice.value = value
    return choice


async def _maak_pet(session, speler_id: int, soort: PetSoort, naam: str) -> int:
    if await session.get(Speler, speler_id) is None:
        session.add(Speler(discord_id=speler_id, currency=0, mmr=1000, volgend_pet_nummer=1))
        await session.commit()
    speler = await session.get(Speler, speler_id)
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


async def test_gedeelde_capaciteit() -> None:
    print("-- Gedeelde werkplek-capaciteit over alle spelers heen --")
    cog = WerkCog(bot=MagicMock())
    pet_ids: list[int] = []
    try:
        async with async_session() as session:
            # Nachtwacht heeft capaciteit 1 (kleinste werkplek) — ideaal om
            # de limiet met maar 2 spelers te kunnen raken.
            soort = await session.scalar(select(PetSoort).limit(1))
            for i, speler_id in enumerate(SPELERS[:2]):
                pet_ids.append(await _maak_pet(session, speler_id, soort, f"NachtwachtTest{i}"))

        interactie_1 = fake_interaction(SPELERS[0])
        await cog.werk.callback(
            cog, interactie_1, pet_id=1, werkplek=fake_choice("Nachtwacht"), cyclus=fake_choice("korte")
        )
        interactie_1.response.send_message.assert_awaited()
        bericht_1 = interactie_1.response.send_message.call_args[0][0]
        print(f"Speler 1: {bericht_1}")
        assert "aan het werk gezet" in bericht_1

        interactie_2 = fake_interaction(SPELERS[1])
        await cog.werk.callback(
            cog, interactie_2, pet_id=1, werkplek=fake_choice("Nachtwacht"), cyclus=fake_choice("korte")
        )
        bericht_2 = interactie_2.response.send_message.call_args[0][0]
        print(f"Speler 2 (moet geweigerd worden): {bericht_2}")
        assert "zit vol" in bericht_2

        async with async_session() as session:
            pet2 = await session.get(Huisdier, pet_ids[1])
            assert pet2.status == PetStatus.rust, "Speler 2's pet zou niet aan het werk moeten zijn gezet"
        print("Capaciteit wordt correct gedeeld/afgedwongen over spelers heen.")
    finally:
        async with async_session() as session:
            if pet_ids:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids)))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id.in_(SPELERS[:2])))
            await session.commit()


async def test_mijnschacht_en_bonus_grondstof() -> None:
    print("\n-- Mijnschacht-optie + tweede grondstof (kans per shift) --")
    cog = WerkCog(bot=MagicMock())
    pet_id = None
    speler_id = SPELERS[2]
    try:
        async with async_session() as session:
            soort = await session.scalar(select(PetSoort).limit(1))
            pet_id = await _maak_pet(session, speler_id, soort, "MijnwerkerTest")

        interactie = fake_interaction(speler_id)
        await cog.werk.callback(
            cog, interactie, pet_id=1, werkplek=fake_choice("Mijnschacht"), cyclus=fake_choice("korte")
        )
        bericht = interactie.response.send_message.call_args[0][0]
        print(f"Shift gestart: {bericht}")
        assert "Mijnschacht" in bericht

        async with async_session() as session:
            pet = await session.get(Huisdier, pet_id)
            pet.werk_gestart_op = _nu() - timedelta(hours=999)  # forceer 'klaar'
            await session.commit()

        # Forceer een gegarandeerde bonus-roll (random.random() < kans).
        interactie_ophalen = fake_interaction(speler_id)
        with patch("cogs.werk.random.random", return_value=0.0):
            await cog.werk.callback(cog, interactie_ophalen, pet_id=1)
        bericht_op = interactie_ophalen.response.send_message.call_args[0][0]
        print(f"Opgehaald met geforceerde bonus: {bericht_op}")
        assert "Bonus:" in bericht_op and "Edelsteen" in bericht_op

        async with async_session() as session:
            item = await session.scalar(select(Item).where(Item.naam == "Edelsteen"))
            inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == speler_id, InventarisItem.item_id == item.id
                )
            )
            assert inv is not None and inv.aantal >= 1
        print("Mijnschacht werkt, en de bonus-grondstof-roll wordt correct toegepast.")

        # Tweede shift: forceer GEEN bonus-roll (random.random() >= kans).
        async with async_session() as session:
            speler = await session.get(Speler, speler_id)
            pet = await session.get(Huisdier, pet_id)
            pet.status = PetStatus.rust
            await session.commit()

        interactie_start2 = fake_interaction(speler_id)
        await cog.werk.callback(
            cog, interactie_start2, pet_id=1, werkplek=fake_choice("Mijnschacht"), cyclus=fake_choice("korte")
        )
        async with async_session() as session:
            pet = await session.get(Huisdier, pet_id)
            pet.werk_gestart_op = _nu() - timedelta(hours=999)
            await session.commit()

        interactie_ophalen2 = fake_interaction(speler_id)
        with patch("cogs.werk.random.random", return_value=0.99):
            await cog.werk.callback(cog, interactie_ophalen2, pet_id=1)
        bericht_op2 = interactie_ophalen2.response.send_message.call_args[0][0]
        print(f"Opgehaald zonder bonus: {bericht_op2}")
        assert "Bonus:" not in bericht_op2
        print("Geen bonus-roll (kans niet gehaald) geeft ook geen bonus-tekst/item.")
    finally:
        async with async_session() as session:
            if pet_id:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id == pet_id))
            await session.execute(InventarisItem.__table__.delete().where(InventarisItem.speler_id == speler_id))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == speler_id))
            await session.commit()
        print("Testdata opgeruimd.")


async def main() -> None:
    await test_gedeelde_capaciteit()
    await test_mijnschacht_en_bonus_grondstof()
    print("\nAlle checks geslaagd.")


if __name__ == "__main__":
    asyncio.run(main())
