"""Vecht-mechaniek voor /team en /vecht. Zie projectbrief sectie 12/13.

Structuur (uitgebreider dan de brief letterlijk beschrijft, op verzoek van
de gebruiker): een gevecht is een best-of-3 van opeenvolgende 1v1-matchups
(pet 1 vs pet 1, pet 2 vs pet 2, pet 3 vs pet 3), niet één enkele
team-vs-team vergelijking. Per matchup kiest de aanvaller een tactiek
(beïnvloedt de RNG-variantie uit de brief) of vlucht. Binnen een matchup
lossen meerdere interne rondes automatisch op tot een pet 0 HP heeft of
de rondelimiet bereikt is.

Bij PvP is de tegenstander-kant (nog) passief: die speelt altijd
"gebalanceerd". Echte beurt-voor-beurt inbreng van beide spelers is een
mogelijke latere uitbreiding.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import config
from db.models import Huisdier, Tier

_DEV_VERSNELLING = 120  # zelfde compressie-factor als werk/stats/slaap

TACTIEK_VARIANTIE = {
    "aggressief": (-0.25, 0.35),
    "gebalanceerd": (-0.15, 0.15),
    "voorzichtig": (-0.10, 0.10),
}

MAX_INTERNE_RONDES = 5
SCHADE_FRACTIE = 0.35  # aandeel van de macht-dezer-ronde dat als schade wordt toegebracht

ELO_K = 32
CURRENCY_BASIS_WINST = 20
CURRENCY_BONUS_PER_100_MMR = 2
XP_WINST = 30
XP_VERLIES = 10
ENERGIE_KOST_MIN = 10
ENERGIE_KOST_MAX = 20

PVE_BASIS_TEAM_POWER = 200  # team-macht van een gesimuleerde tegenstander bij MMR 1000

_RANKED_RESET_UUR_ECHT = 24
RANKED_RESET_UUR = (
    _RANKED_RESET_UUR_ECHT / _DEV_VERSNELLING if config.ENVIRONMENT == "dev" else _RANKED_RESET_UUR_ECHT
)


def _nu() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pet_power(huisdier: Huisdier, tier: Tier) -> float:
    """Brief sectie 12: pet_power = gevecht_genen x tier_multiplier x (1 + level x 0,05)."""
    return float(huisdier.gevecht_genen) * float(tier.stat_multiplier) * (1 + huisdier.level * 0.05)


def pet_hp(macht: float) -> int:
    return max(20, round(macht))


def macht_met_tactiek(basis_macht: float, tactiek: str) -> float:
    laag, hoog = TACTIEK_VARIANTIE[tactiek]
    return basis_macht * (1 + random.uniform(laag, hoog))


def bereken_schade(macht: float) -> int:
    return max(1, round(macht * SCHADE_FRACTIE))


def synthetische_tegenstander_macht(mmr: int) -> float:
    """Genereert de macht van een gesimuleerde PvE-tegenstander, geschaald op MMR."""
    return (mmr / 1000) * PVE_BASIS_TEAM_POWER


def elo_delta(mmr_eigen: int, mmr_tegenstander: int, gewonnen: bool) -> int:
    verwacht = 1 / (1 + 10 ** ((mmr_tegenstander - mmr_eigen) / 400))
    score = 1.0 if gewonnen else 0.0
    return round(ELO_K * (score - verwacht))


def currency_beloning(tegenstander_mmr: int) -> int:
    return CURRENCY_BASIS_WINST + round(tegenstander_mmr / 100) * CURRENCY_BONUS_PER_100_MMR


@dataclass
class MatchupResultaat:
    ronde_log: list[str]
    eigen_wint: bool
    eigen_hp_over: int
    tegenstander_hp_over: int
    gevlucht: bool = False


def speel_matchup(eigen_macht_basis: float, tegenstander_macht_basis: float, tactiek: str) -> MatchupResultaat:
    """Lost één 1v1-matchup op: meerdere interne rondes tot een kant 0 HP heeft
    of de rondelimiet bereikt wordt (dan wint wie meer HP over heeft)."""
    eigen_hp = pet_hp(eigen_macht_basis)
    tegenstander_hp = pet_hp(tegenstander_macht_basis)
    log: list[str] = []

    for ronde in range(1, MAX_INTERNE_RONDES + 1):
        eigen_macht = macht_met_tactiek(eigen_macht_basis, tactiek)
        tegenstander_macht = macht_met_tactiek(tegenstander_macht_basis, "gebalanceerd")

        schade_aan_tegenstander = bereken_schade(eigen_macht)
        schade_aan_mij = bereken_schade(tegenstander_macht)

        tegenstander_hp = max(0, tegenstander_hp - schade_aan_tegenstander)
        eigen_hp = max(0, eigen_hp - schade_aan_mij)

        log.append(
            f"Ronde {ronde}: jij deelt {schade_aan_tegenstander} schade uit, "
            f"tegenstander deelt {schade_aan_mij} schade uit."
        )

        if eigen_hp <= 0 or tegenstander_hp <= 0:
            break

    if eigen_hp == tegenstander_hp:
        eigen_wint = random.choice([True, False])
    else:
        eigen_wint = eigen_hp > tegenstander_hp
    return MatchupResultaat(
        ronde_log=log, eigen_wint=eigen_wint, eigen_hp_over=eigen_hp, tegenstander_hp_over=tegenstander_hp
    )
