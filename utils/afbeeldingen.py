"""Gedeelde helpers om pet-afbeeldingen te downloaden en samen te stellen
tot één render (Pillow) — gebruikt door utils/trade_image.py en
utils/vecht_afbeelding.py. Discord-embeds ondersteunen zelf maar één
losse afbeelding, dus dit wordt zelf gerenderd i.p.v. twee losse
image-velden te proberen.
"""

import io
from collections import OrderedDict

import aiohttp
from PIL import Image
from sqlalchemy import select

from db.models import PetSoort

VAKGROOTTE = 400
MARGE = 40
MIDDEN_BREEDTE = 120

# Pet-afbeeldingen zijn statisch (vaste raw.githubusercontent-URL's per
# soort), maar werden bij elke matchup opnieuw opgehaald: een PvP-gevecht
# deed 6 downloads (3 matchups x 2 pets). Een kleine LRU-cache op de
# gedecodeerde afbeelding scheelt dat vrijwel helemaal; 64 plaatjes van
# 400x400 RGBA is grofweg 40 MB in het slechtste geval, ruim binnen wat
# Railway aankan (2026-07-28, codebase-review).
_CACHE_MAX = 64
_cache: OrderedDict[str, Image.Image] = OrderedDict()
_sessie: aiohttp.ClientSession | None = None


async def soort_afbeeldingen(session) -> dict[int, str | None]:
    """soort_id -> afbeelding_url."""
    rijen = (await session.execute(select(PetSoort.id, PetSoort.afbeelding_url))).all()
    return dict(rijen)


async def _http_sessie() -> aiohttp.ClientSession:
    """Eén gedeelde ClientSession i.p.v. één per download: die opzetten kost
    een nieuwe connectiepool per aanroep, en aiohttp waarschuwt terecht over
    sessies die niet netjes hergebruikt worden."""
    global _sessie
    if _sessie is None or _sessie.closed:
        _sessie = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    return _sessie


async def download_afbeelding(url: str) -> Image.Image | None:
    gecachet = _cache.get(url)
    if gecachet is not None:
        _cache.move_to_end(url)
        # Kopie teruggeven: aanroepers bewerken de afbeelding (bijsnijden,
        # plakken), en dat mag het exemplaar in de cache niet aantasten.
        return gecachet.copy()

    try:
        sessie = await _http_sessie()
        async with sessie.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
    except (aiohttp.ClientError, TimeoutError):
        return None

    try:
        afbeelding = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None

    _cache[url] = afbeelding
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return afbeelding.copy()


async def sluit_http_sessie() -> None:
    """Sluit de gedeelde sessie netjes af (aangeroepen bij bot-shutdown).
    Zonder dit logt aiohttp bij het afsluiten een 'Unclosed client
    session'-waarschuwing."""
    global _sessie
    if _sessie is not None and not _sessie.closed:
        await _sessie.close()
    _sessie = None


def kwadraat_bijsnijden(afbeelding: Image.Image) -> Image.Image:
    breedte, hoogte = afbeelding.size
    kant = min(breedte, hoogte)
    links = (breedte - kant) // 2
    boven = (hoogte - kant) // 2
    return afbeelding.crop((links, boven, links + kant, boven + kant)).resize((VAKGROOTTE, VAKGROOTTE))
