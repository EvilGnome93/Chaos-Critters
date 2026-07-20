import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from db.engine import async_session
from db.models import Instelling, Item, PetSoort, Tier, Werkplek


async def verify() -> None:
    async with async_session() as session:
        for model, verwacht in ((Tier, 3), (Werkplek, 5), (PetSoort, 13), (Item, 11), (Instelling, 4)):
            aantal = await session.scalar(select(func.count()).select_from(model))
            status = "OK" if aantal == verwacht else "MISMATCH"
            print(f"{model.__tablename__}: {aantal} (verwacht {verwacht}) [{status}]")

        print("\nPet soorten zonder werkplek_voorkeur (verwacht: Egel, Chaos Kip, Wolf, Steenarend, Chaos Eenhoorn):")
        rows = (
            await session.execute(
                select(PetSoort.naam).where(PetSoort.werkplek_voorkeur_id.is_(None))
            )
        ).scalars().all()
        for naam in rows:
            print(f"  - {naam}")


if __name__ == "__main__":
    asyncio.run(verify())
