"""Handmatige, niet-geautomatiseerde check van het verzorgingssysteem
(stat-verval, inzetbaarheid, voeding gebruiken) zonder Discord.

Ruimt zijn eigen testdata op aan het eind, ongeacht of de checks slagen.
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from cogs.verzorging import _toepassen_voeding
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, PetSoort, PetStatus, Speler
from utils.stats import HONGER_VERVAL_MINUTEN, _nu, inzetbaarheid_probleem, sync_stats

TEST_SPELER_ID = 999999999999999998


async def main() -> None:
    async with async_session() as session:
        speler = await session.get(Speler, TEST_SPELER_ID)
        if speler is None:
            speler = Speler(discord_id=TEST_SPELER_ID, volgend_pet_nummer=1)
            session.add(speler)
            await session.commit()
            speler = await session.get(Speler, TEST_SPELER_ID)

        soort = await session.scalar(select(PetSoort).limit(1))
        huisdier = Huisdier(
            eigenaar_id=TEST_SPELER_ID,
            soort_id=soort.id,
            tier_id=soort.tier_id,
            naam="Verzorgtest",
            volgnummer=speler.volgend_pet_nummer,
            gevecht_genen=50,
            werk_genen=50,
            honger=100,
            energie=50,
            status=PetStatus.rust,
            laatste_verzorging_op=_nu() - timedelta(minutes=HONGER_VERVAL_MINUTEN * 3),
        )
        session.add(huisdier)
        await session.commit()
        await session.refresh(huisdier)

        try:
            print("-- verval na 3x verval-interval --")
            sync_stats(huisdier)
            print(f"honger={huisdier.honger} (verwacht 97), energie={huisdier.energie}")
            assert huisdier.honger == 97

            print("\n-- inzetbaarheid bij honger=0 --")
            huisdier.honger = 0
            probleem = inzetbaarheid_probleem(huisdier)
            print(probleem)
            assert probleem is not None

            print("\n-- voeding herstelt honger, niet energie (Basis brokjes) --")
            huisdier.honger = 50
            item = await session.scalar(select(Item).where(Item.naam == "Basis brokjes"))
            stmt = insert(InventarisItem).values(speler_id=TEST_SPELER_ID, item_id=item.id, aantal=1)
            stmt = stmt.on_conflict_do_update(
                index_elements=["speler_id", "item_id"], set_={"aantal": InventarisItem.aantal + 1}
            )
            await session.execute(stmt)

            honger_voor = huisdier.honger
            energie_voor = huisdier.energie
            _toepassen_voeding(huisdier, "Basis brokjes")
            print(f"honger {honger_voor} -> {huisdier.honger} (verwacht +15), energie ongewijzigd: {huisdier.energie}")
            assert huisdier.honger == min(100, honger_voor + 15)
            assert huisdier.energie == energie_voor
            assert inzetbaarheid_probleem(huisdier) is None

            print("\nAlle checks geslaagd.")
        finally:
            await session.execute(
                InventarisItem.__table__.delete().where(InventarisItem.speler_id == TEST_SPELER_ID)
            )
            await session.delete(huisdier)
            await session.delete(speler)
            await session.commit()
            print("\nTestdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
