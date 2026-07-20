"""Handmatige, niet-geautomatiseerde check van de /vang-logica zonder Discord.

Simuleert een vangst voor een test-speler en print het resultaat, zodat we
de query-logica (_vind_soort) en het aanmaken van Speler/Huisdier kunnen
verifiëren voordat we het via een echt Discord-commando testen.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.vangen import VangenCog, _met_variantie
from db.engine import async_session
from db.models import Huisdier, PetSoort, Speler

TEST_SPELER_ID = 999999999999999999


async def main() -> None:
    async with async_session() as session:
        print("-- exacte match 'Vos' --")
        print(await VangenCog._vind_soort(session, "Vos"))

        print("-- substring match 'hond' --")
        print(await VangenCog._vind_soort(session, "hond"))

        print("-- ambigue match 'v' --")
        result = await VangenCog._vind_soort(session, "v")
        print(result if not isinstance(result, list) else [s.naam for s in result])

        print("-- onbekend 'draak' --")
        print(await VangenCog._vind_soort(session, "draak"))

        soort = await session.scalar(select(PetSoort).where(PetSoort.naam.ilike("Vos")))
        speler = await session.get(Speler, TEST_SPELER_ID)
        if speler is None:
            speler = Speler(discord_id=TEST_SPELER_ID)
            session.add(speler)

        huisdier = Huisdier(
            eigenaar_id=TEST_SPELER_ID,
            soort_id=soort.id,
            tier_id=soort.tier_id,
            naam=soort.naam,
            gevecht_genen=_met_variantie(soort.gevecht_basis),
            werk_genen=_met_variantie(soort.werk_basis),
        )
        session.add(huisdier)
        await session.commit()
        await session.refresh(huisdier)

        print("\n-- aangemaakte huisdier --")
        print(
            f"id={huisdier.id} naam={huisdier.naam} status={huisdier.status} "
            f"gevecht_genen={huisdier.gevecht_genen} werk_genen={huisdier.werk_genen} "
            f"honger={huisdier.honger} energie={huisdier.energie} blijdschap={huisdier.blijdschap} "
            f"eigenaar_id={huisdier.eigenaar_id}"
        )

        aantal = len(
            (
                await session.execute(select(Huisdier).where(Huisdier.eigenaar_id == TEST_SPELER_ID))
            )
            .scalars()
            .all()
        )
        print(f"totaal aantal pets van test-speler: {aantal}")


if __name__ == "__main__":
    asyncio.run(main())
