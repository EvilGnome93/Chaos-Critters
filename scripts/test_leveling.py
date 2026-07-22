"""Handmatige, niet-geautomatiseerde check van het level-up systeem
(XP toevoegen, level-up, genen-groei, meerdere levels in 1x, max-level cap)
zonder Discord.

Ruimt zijn eigen testdata op aan het eind, ongeacht of de checks slagen.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from db.engine import async_session
from db.models import Huisdier, PetSoort, Speler
from utils.leveling import MAX_LEVEL, voeg_xp_toe, xp_voor_volgend_level

TEST_SPELER_ID = 999999999999999997


async def main() -> None:
    async with async_session() as session:
        speler = await session.get(Speler, TEST_SPELER_ID)
        if speler is None:
            speler = Speler(discord_id=TEST_SPELER_ID)
            session.add(speler)

        soort = await session.scalar(select(PetSoort).limit(1))
        huisdier = Huisdier(
            eigenaar_id=TEST_SPELER_ID,
            soort_id=soort.id,
            tier_id=soort.tier_id,
            naam="Leveltest",
            gevecht_genen=60,
            werk_genen=60,
        )
        session.add(huisdier)
        await session.commit()
        await session.refresh(huisdier)

        try:
            print("-- kleine hoeveelheid xp, geen level-up --")
            levels = voeg_xp_toe(huisdier, 10)
            print(f"level={huisdier.level} xp={huisdier.xp} levels={levels}")
            assert huisdier.level == 1 and huisdier.xp == 10 and levels == []

            print("\n-- net genoeg voor level 2 (genen +2%) --")
            gevecht_voor = float(huisdier.gevecht_genen)
            levels = voeg_xp_toe(huisdier, xp_voor_volgend_level(1) - 10)
            print(f"level={huisdier.level} xp={huisdier.xp} levels={levels} genen={huisdier.gevecht_genen}")
            assert huisdier.level == 2 and huisdier.xp == 0 and levels == [2]
            assert abs(float(huisdier.gevecht_genen) - round(gevecht_voor * 1.02, 2)) < 0.01

            print("\n-- grote hoeveelheid xp, meerdere levels in 1x --")
            levels = voeg_xp_toe(huisdier, 1000)
            print(f"level={huisdier.level} xp={huisdier.xp} levels={levels}")
            assert levels == [3, 4, 5]
            assert huisdier.level == 5

            print("\n-- max-level cap --")
            huisdier.level = MAX_LEVEL
            huisdier.xp = 0
            levels = voeg_xp_toe(huisdier, 999999)
            print(f"level={huisdier.level} xp={huisdier.xp} levels={levels}")
            assert huisdier.level == MAX_LEVEL and huisdier.xp == 0 and levels == []

            print("\nAlle checks geslaagd.")
        finally:
            await session.delete(huisdier)
            await session.delete(speler)
            await session.commit()
            print("\nTestdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
