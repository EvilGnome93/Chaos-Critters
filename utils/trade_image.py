"""Stelt een enkele afbeelding samen van twee pets naast elkaar met een
ruil-pijl ertussen, voor gebruik in een /trade-voorstel. Discord-embeds
ondersteunen maar één losse afbeelding, dus dit wordt zelf gerenderd
(Pillow) i.p.v. twee losse image-velden te proberen.
"""

import io

import aiohttp
from PIL import Image, ImageDraw

VAKGROOTTE = 400
MARGE = 40
PIJL_BREEDTE = 120
CANVAS_HOOGTE = VAKGROOTTE + MARGE * 2
CANVAS_BREEDTE = VAKGROOTTE * 2 + PIJL_BREEDTE + MARGE * 2

ACHTERGROND = (255, 255, 255, 255)
PIJL_KLEUR = (66, 133, 244, 255)


async def _download_afbeelding(url: str) -> Image.Image | None:
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


def _kwadraat_bijsnijden(afbeelding: Image.Image) -> Image.Image:
    breedte, hoogte = afbeelding.size
    kant = min(breedte, hoogte)
    links = (breedte - kant) // 2
    boven = (hoogte - kant) // 2
    return afbeelding.crop((links, boven, links + kant, boven + kant)).resize((VAKGROOTTE, VAKGROOTTE))


def _teken_ruilpijl(canvas: Image.Image, midden_x: int, midden_y: int) -> None:
    """Twee tegengestelde pijlen, boven naar rechts en onder naar links —
    zelfde idee als het 'ruil'-icoon (🔄)."""
    draw = ImageDraw.Draw(canvas)
    breedte = PIJL_BREEDTE - 20
    hoogte = 18
    kop = 30

    boven_y = midden_y - 25
    links = midden_x - breedte // 2
    rechts = midden_x + breedte // 2
    draw.line([(links, boven_y), (rechts - kop, boven_y)], fill=PIJL_KLEUR, width=hoogte)
    draw.polygon(
        [(rechts - kop, boven_y - kop // 2), (rechts, boven_y), (rechts - kop, boven_y + kop // 2)],
        fill=PIJL_KLEUR,
    )

    onder_y = midden_y + 25
    draw.line([(rechts, onder_y), (links + kop, onder_y)], fill=PIJL_KLEUR, width=hoogte)
    draw.polygon(
        [(links + kop, onder_y - kop // 2), (links, onder_y), (links + kop, onder_y + kop // 2)],
        fill=PIJL_KLEUR,
    )


async def bouw_ruil_afbeelding(geef_url: str, vraag_url: str) -> io.BytesIO | None:
    """Geeft None terug als één van beide afbeeldingen niet opgehaald kon
    worden — de aanroeper valt dan terug op geen afbeelding."""
    geef_img = await _download_afbeelding(geef_url)
    vraag_img = await _download_afbeelding(vraag_url)
    if geef_img is None or vraag_img is None:
        return None

    canvas = Image.new("RGBA", (CANVAS_BREEDTE, CANVAS_HOOGTE), ACHTERGROND)
    canvas.paste(_kwadraat_bijsnijden(geef_img), (MARGE, MARGE))
    canvas.paste(_kwadraat_bijsnijden(vraag_img), (MARGE + VAKGROOTTE + PIJL_BREEDTE, MARGE))
    _teken_ruilpijl(canvas, MARGE + VAKGROOTTE + PIJL_BREEDTE // 2, CANVAS_HOOGTE // 2)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
