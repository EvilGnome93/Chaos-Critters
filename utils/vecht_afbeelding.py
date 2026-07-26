"""Stelt een afbeelding samen van de twee pets in een matchup naast elkaar
met een 'VS'-badge ertussen, voor gebruik tijdens /vecht. Alleen zinvol bij
PvP — bij PvE heeft de gesimuleerde tegenstander geen echte afbeelding, dus
toont het gevecht dan alleen de eigen pet."""

import io

from PIL import Image, ImageDraw, ImageFont

from utils.afbeeldingen import MARGE, MIDDEN_BREEDTE, VAKGROOTTE, download_afbeelding, kwadraat_bijsnijden

CANVAS_HOOGTE = VAKGROOTTE + MARGE * 2
CANVAS_BREEDTE = VAKGROOTTE * 2 + MIDDEN_BREEDTE + MARGE * 2

ACHTERGROND = (255, 255, 255, 255)
BADGE_KLEUR = (237, 66, 69, 255)
BADGE_STRAAL = 50


def _teken_vs_badge(canvas: Image.Image, midden_x: int, midden_y: int) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.ellipse(
        (midden_x - BADGE_STRAAL, midden_y - BADGE_STRAAL, midden_x + BADGE_STRAAL, midden_y + BADGE_STRAAL),
        fill=BADGE_KLEUR,
    )
    try:
        font = ImageFont.truetype("arialbd.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    tekst = "VS"
    bbox = draw.textbbox((0, 0), tekst, font=font)
    tekst_breedte, tekst_hoogte = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (midden_x - tekst_breedte / 2 - bbox[0], midden_y - tekst_hoogte / 2 - bbox[1]),
        tekst, font=font, fill=(255, 255, 255, 255),
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
    _teken_vs_badge(canvas, MARGE + VAKGROOTTE + MIDDEN_BREEDTE // 2, CANVAS_HOOGTE // 2)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
