"""Gedeelde helpers om pet-afbeeldingen te downloaden en samen te stellen
tot één render (Pillow) — gebruikt door utils/trade_image.py en
utils/vecht_afbeelding.py. Discord-embeds ondersteunen zelf maar één
losse afbeelding, dus dit wordt zelf gerenderd i.p.v. twee losse
image-velden te proberen.
"""

import io

import aiohttp
from PIL import Image
from sqlalchemy import select

from db.models import PetSoort

VAKGROOTTE = 400
MARGE = 40
MIDDEN_BREEDTE = 120


async def soort_afbeeldingen(session) -> dict[int, str | None]:
    """soort_id -> afbeelding_url."""
    rijen = (await session.execute(select(PetSoort.id, PetSoort.afbeelding_url))).all()
    return dict(rijen)


async def download_afbeelding(url: str) -> Image.Image | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
    except (aiohttp.ClientError, TimeoutError):
        return None

    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def kwadraat_bijsnijden(afbeelding: Image.Image) -> Image.Image:
    breedte, hoogte = afbeelding.size
    kant = min(breedte, hoogte)
    links = (breedte - kant) // 2
    boven = (hoogte - kant) // 2
    return afbeelding.crop((links, boven, links + kant, boven + kant)).resize((VAKGROOTTE, VAKGROOTTE))
