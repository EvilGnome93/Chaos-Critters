"""Stelt een afbeelding samen van de twee pets in een matchup naast elkaar
met gekruiste zwaarden ertussen, voor gebruik tijdens /vecht. Alleen zinvol
bij PvP — bij PvE heeft de gesimuleerde tegenstander geen echte afbeelding,
dus toont het gevecht dan alleen de eigen pet."""

import io
import math

from PIL import Image, ImageDraw

from utils.afbeeldingen import MARGE, MIDDEN_BREEDTE, VAKGROOTTE, download_afbeelding, kwadraat_bijsnijden

CANVAS_HOOGTE = VAKGROOTTE + MARGE * 2
CANVAS_BREEDTE = VAKGROOTTE * 2 + MIDDEN_BREEDTE + MARGE * 2

ACHTERGROND = (255, 255, 255, 255)
KLING_KLEUR = (222, 224, 228, 255)
GREEP_KLEUR = (96, 64, 32, 255)
GARDE_KLEUR = (201, 162, 39, 255)


def _teken_kruisende_zwaarden(canvas: Image.Image, midden_x: int, midden_y: int) -> None:
    """Twee eenvoudige zwaarden in een X, tip omhoog-buiten en greep
    omlaag-binnen — zelfde idee als het ⚔️-icoon, maar zelf getekend zodat
    het niet van een emoji-lettertype afhangt (die ontbreekt soms op de
    server waar de bot draait)."""
    draw = ImageDraw.Draw(canvas)
    lengte = 62

    for hoek_graden in (45, 135):
        hoek = math.radians(hoek_graden)
        rx, ry = math.cos(hoek), math.sin(hoek)
        tip = (midden_x + rx * lengte, midden_y - ry * lengte)
        hilt = (midden_x - rx * lengte, midden_y + ry * lengte)
        garde_punt = (hilt[0] + (tip[0] - hilt[0]) * 0.32, hilt[1] + (tip[1] - hilt[1]) * 0.32)

        draw.line([garde_punt, tip], fill=KLING_KLEUR, width=9)
        draw.line([hilt, garde_punt], fill=GREEP_KLEUR, width=11)

        rich_dx, rich_dy = tip[0] - hilt[0], tip[1] - hilt[1]
        rich_lengte = math.hypot(rich_dx, rich_dy)
        perp_dx, perp_dy = -rich_dy / rich_lengte * 16, rich_dx / rich_lengte * 16
        draw.line(
            [
                (garde_punt[0] - perp_dx, garde_punt[1] - perp_dy),
                (garde_punt[0] + perp_dx, garde_punt[1] + perp_dy),
            ],
            fill=GARDE_KLEUR, width=7,
        )

        straal = 7
        draw.ellipse(
            [hilt[0] - straal, hilt[1] - straal, hilt[0] + straal, hilt[1] + straal],
            fill=GREEP_KLEUR,
        )


async def bouw_vs_afbeelding(links_url: str, rechts_url: str) -> io.BytesIO | None:
    """Geeft None terug als één van beide afbeeldingen niet opgehaald kon
    worden — de aanroeper valt dan terug op geen afbeelding."""
    links_img = await download_afbeelding(links_url)
    rechts_img = await download_afbeelding(rechts_url)
    if links_img is None or rechts_img is None:
        return None

    canvas = Image.new("RGBA", (CANVAS_BREEDTE, CANVAS_HOOGTE), ACHTERGROND)
    canvas.paste(kwadraat_bijsnijden(links_img), (MARGE, MARGE))
    canvas.paste(kwadraat_bijsnijden(rechts_img), (MARGE + VAKGROOTTE + MIDDEN_BREEDTE, MARGE))
    _teken_kruisende_zwaarden(canvas, MARGE + VAKGROOTTE + MIDDEN_BREEDTE // 2, CANVAS_HOOGTE // 2)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
