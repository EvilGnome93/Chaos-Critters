"""Level-up systeem voor huisdieren. Zie projectbrief sectie 9.

XP komt voorlopig alleen uit voltooide werk-shifts (cogs/werk.py) — vechten
kan hier later ook XP aan toevoegen zodra dat gebouwd is.
"""

from db.models import Huisdier
from utils import balans

# 2026-07-30, admin panel fase 2, blok 2: was hardcoded module-constanten,
# nu functies die de actuele waarde uit de balans-cache lezen (zie
# utils/balans.py). De defaults zijn de oude hardcoded waarden.
#
# XP_PER_EFFECTIEVE_UUR-geschiedenis (2026-07-28, Balans-audit): was 5, gaf
# ~227 dagen tot max_level(). Verhoogd naar 95 met als doel ~2-4 weken, maar
# die berekening ging uit van *continu* overnacht-werken, en dat kan niet:
# een overnacht-shift kost 70 energie en energie herstelt alleen tijdens
# rust (+6/uur, utils/stats.py). In de praktijk kwam 95 uit op ~45 dagen
# i.p.v. 21. Bijgesteld naar 180, waarmee hetzelfde scenario inclusief
# energie-herstel op ~24 dagen uitkomt (korte ~38 dagen, lange ~30 dagen,
# overnacht ~24 dagen). Met een Zelfreinigend systeem (energie herstelt ook
# tijdens werk) halveert dat ruwweg.
def xp_per_effectieve_uur() -> int:
    return balans.get_int("xp_per_effectieve_uur", 180)


def max_level() -> int:
    return balans.get_int("max_level", 50)


def genen_groei_per_level() -> float:
    return balans.get_float("genen_groei_per_level", 0.02)  # +2% samengesteld per level (sectie 9)


# Level-curve (2026-07-30, gemeld door de gebruiker): een pet ging in één
# overnacht-shift (4680 XP) van level 1 naar 10, omdat de oude curve
# (level x 100) de eerste stappen bijna gratis maakte t.o.v. wat een shift
# oplevert — de eerste 9 levels kostten samen maar 4500 XP. Vervangen door
# een vlakkere curve die bewust hetzelfde totaal (122.500 XP voor
# level 1->50) nodig heeft, dus de ~24-dagen-tuning hierboven blijft geldig,
# alleen nu gelijkmatig verdeeld (2020 XP voor level 1, 2980 voor level 49)
# i.p.v. bijna gratis begin en heel duur einde (was 100 vs. 4900).
def _level_xp_basis() -> int:
    return balans.get_int("level_xp_basis", 2000)


def _level_xp_per_level() -> int:
    return balans.get_int("level_xp_per_level", 20)


def xp_voor_volgend_level(huidig_level: int) -> int:
    return _level_xp_basis() + huidig_level * _level_xp_per_level()


def voeg_xp_toe(huisdier: Huisdier, xp: int) -> list[int]:
    """Voegt XP toe en verwerkt eventuele level-up(s) (genen +2% samengesteld
    per level, tot max_level()). Geeft de lijst nieuw behaalde levels terug."""
    limiet = max_level()
    if huisdier.level >= limiet:
        return []

    huisdier.xp += xp
    nieuwe_levels: list[int] = []
    groei = genen_groei_per_level()

    while huisdier.level < limiet:
        benodigd = xp_voor_volgend_level(huisdier.level)
        if huisdier.xp < benodigd:
            break
        huisdier.xp -= benodigd
        huisdier.level += 1
        huisdier.gevecht_genen = round(float(huisdier.gevecht_genen) * (1 + groei), 2)
        huisdier.werk_genen = round(float(huisdier.werk_genen) * (1 + groei), 2)
        nieuwe_levels.append(huisdier.level)

    if huisdier.level >= limiet:
        huisdier.xp = 0

    return nieuwe_levels
