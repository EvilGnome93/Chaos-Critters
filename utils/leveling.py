"""Level-up systeem voor huisdieren. Zie projectbrief sectie 9.

XP komt voorlopig alleen uit voltooide werk-shifts (cogs/werk.py) — vechten
kan hier later ook XP aan toevoegen zodra dat gebouwd is.
"""

from db.models import Huisdier

MAX_LEVEL = 50
GENEN_GROEI_PER_LEVEL = 0.02  # +2% samengesteld per level (sectie 9, letterlijk voorbeeld)
# 2026-07-28, Balans-audit: was 5, gaf ~227 dagen tot MAX_LEVEL. Verhoogd naar
# 95 met als doel ~2-4 weken — maar die berekening ging uit van *continu*
# overnacht-werken, en dat kan niet: een overnacht-shift kost 70 energie en
# energie herstelt alleen tijdens rust (+6/uur, utils/stats.py). Een pet is dus
# 10u aan het werk en daarna ~11,7u aan het bijkomen; in de praktijk kwam 95
# uit op ~45 dagen i.p.v. 21.
#
# Bijgesteld naar 180 (2026-07-28, na de codebase-review), waarmee hetzelfde
# scenario inclusief energie-herstel op ~24 dagen uitkomt. Referentie per
# shift-type (1 pet, volledige energie-cyclus meegerekend):
#   korte ~38 dagen | lange ~30 dagen | overnacht ~24 dagen
# Met een Zelfreinigend systeem (energie herstelt ook tijdens werk) halveert
# dat ruwweg — dat item is daarmee een echte upgrade i.p.v. een randgeval.
XP_PER_EFFECTIEVE_UUR = 180

# 2026-07-30, gemeld door de gebruiker: een pet ging in één overnacht-shift
# (4680 XP) van level 1 naar 10, omdat de oude curve (level x 100) de eerste
# stappen bijna gratis maakte t.o.v. wat een shift oplevert — de eerste 9
# levels kostten samen maar 4500 XP. Vervangen door een vlakkere curve die
# bewust hetzelfde totaal (122.500 XP voor level 1->50) nodig heeft, dus de
# ~24-dagen-tuning van XP_PER_EFFECTIEVE_UUR hierboven blijft geldig — alleen
# nu gelijkmatig verdeeld (2020 XP voor level 1, 2980 voor level 49) i.p.v.
# bijna gratis begin en heel duur einde (was 100 vs. 4900). Dezelfde shift
# geeft nu 2 levels i.p.v. 9.
LEVEL_XP_BASIS = 2000
LEVEL_XP_PER_LEVEL = 20


def xp_voor_volgend_level(huidig_level: int) -> int:
    return LEVEL_XP_BASIS + huidig_level * LEVEL_XP_PER_LEVEL


def voeg_xp_toe(huisdier: Huisdier, xp: int) -> list[int]:
    """Voegt XP toe en verwerkt eventuele level-up(s) (genen +2% samengesteld
    per level, tot MAX_LEVEL). Geeft de lijst nieuw behaalde levels terug."""
    if huisdier.level >= MAX_LEVEL:
        return []

    huisdier.xp += xp
    nieuwe_levels: list[int] = []

    while huisdier.level < MAX_LEVEL:
        benodigd = xp_voor_volgend_level(huisdier.level)
        if huisdier.xp < benodigd:
            break
        huisdier.xp -= benodigd
        huisdier.level += 1
        huisdier.gevecht_genen = round(float(huisdier.gevecht_genen) * (1 + GENEN_GROEI_PER_LEVEL), 2)
        huisdier.werk_genen = round(float(huisdier.werk_genen) * (1 + GENEN_GROEI_PER_LEVEL), 2)
        nieuwe_levels.append(huisdier.level)

    if huisdier.level >= MAX_LEVEL:
        huisdier.xp = 0

    return nieuwe_levels
