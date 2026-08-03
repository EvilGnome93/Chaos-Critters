"""Vecht-mechaniek voor /team en /vecht. Zie projectbrief sectie 12/13.

Structuur (uitgebreider dan de brief letterlijk beschrijft, op verzoek van
de gebruiker): een gevecht is een best-of-3 van opeenvolgende 1v1-matchups
(pet 1 vs pet 1, pet 2 vs pet 2, pet 3 vs pet 3), niet één enkele
team-vs-team vergelijking. Per matchup kiest de aanvaller een tactiek
(beïnvloedt de RNG-variantie uit de brief) of vlucht. Binnen een matchup
lossen meerdere interne rondes automatisch op tot een pet 0 HP heeft of
de rondelimiet bereikt is.

Bij PvP kiezen beide spelers per matchup hun eigen tactiek (sinds
2026-07-22); de matchup lost pas op zodra allebei gekozen hebben. Bij PvE
is de gesimuleerde tegenstander passief en speelt die altijd
"gebalanceerd" — vandaar de default van `tegenstander_tactiek` hieronder.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import config
from db.models import Huisdier, Tier
from utils import balans

# De tactiek-variantie staat sinds 2026-07-30 (fase 2, blok 5) in de
# Instelling-tabel als tactiek_<naam>_variantie_min/_max; zie
# balans.tactiek_variantie(). Uiteindelijk toch losse sleutels en geen eigen
# tabel: het zijn drie vaste tactieken die in de keuzemenu's van /pvp en
# /pve hardcoded staan, dus rijen toevoegen of weghalen zou niets doen.
# Alleen de zes getallen zijn zinvol aanpasbaar.

# 2026-07-30, admin panel fase 2, blok 2: losse balansconstanten verhuisd
# naar de Instelling-tabel (utils/balans.py) — was hardcoded module-
# constanten, nu functies die de actuele waarde uit de cache lezen. De
# default in elke get_*-aanroep is de oude hardcoded waarde.


def _max_interne_rondes() -> int:
    return balans.get_int("max_interne_rondes", 5)


def _schade_fractie() -> float:
    return balans.get_float("schade_fractie", 0.35)


def _elo_k() -> int:
    return balans.get_int("elo_k", 32)


def _currency_basis_winst() -> int:
    return balans.get_int("currency_basis_winst", 20)


def _currency_bonus_per_100_mmr() -> int:
    return balans.get_int("currency_bonus_per_100_mmr", 2)


def xp_winst() -> int:
    return balans.get_int("xp_winst", 30)


def xp_verlies() -> int:
    return balans.get_int("xp_verlies", 10)


def energie_kost_min() -> int:
    return balans.get_int("energie_kost_min", 10)


def energie_kost_max() -> int:
    return balans.get_int("energie_kost_max", 20)


def ranked_reset_uur() -> float:
    """Was een module-constante afgeleid op import-tijd — moest een functie
    worden, anders bevriest de waarde vóór de eerste balans.laad()-aanroep
    (zie de valkuil hierover in docs/dev-status.md)."""
    echt = balans.get_float("ranked_reset_uur_echt", 24)
    versnelling = balans.get_float("dev_versnelling", 120)
    return echt / versnelling if config.ENVIRONMENT == "dev" else echt


def _nu() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pet_power(huisdier: Huisdier, tier: Tier) -> float:
    """Brief sectie 12: pet_power = gevecht_genen x tier_multiplier x (1 + level x 0,05)."""
    return float(huisdier.gevecht_genen) * float(tier.stat_multiplier) * (1 + huisdier.level * 0.05)


def pet_hp(macht: float) -> int:
    return max(20, round(macht))


def macht_met_tactiek(basis_macht: float, tactiek: str) -> float:
    laag, hoog = balans.tactiek_variantie(tactiek)
    return basis_macht * (1 + random.uniform(laag, hoog))


def bereken_schade(macht: float) -> int:
    return max(1, round(macht * _schade_fractie()))


def synthetische_tegenstander_macht(eigen_pet_macht: float, mmr: int) -> float:
    """Basismacht van de gesimuleerde PvE-tegenstander in één matchup.

    Spiegelt de macht van de eigen pet in díé specifieke matchup (niet het
    teamtotaal): matchups zijn opeenvolgend 1-op-1, dus een ongelijk
    verdeeld team (bijv. één sterke Legendary plus twee zwakkere pets) zou
    bij een totaal-gebaseerde tegenstander alsnog 2 van de 3 matchups
    verliezen ondanks een gelijk teamtotaal. Per-pet spiegelen blijft ook
    dan eerlijk. Kleine MMR-modifier zodat een hogere MMR iets zwaarder
    weegt; de aanroeper past er zelf nog eigen willekeurige variantie op
    toe per matchup."""
    mmr_factor = max(0.5, 1 + (mmr - 1000) / 1000 * 0.2)
    return eigen_pet_macht * mmr_factor


def elo_delta(mmr_eigen: int, mmr_tegenstander: int, gewonnen: bool) -> int:
    verwacht = 1 / (1 + 10 ** ((mmr_tegenstander - mmr_eigen) / 400))
    score = 1.0 if gewonnen else 0.0
    return round(_elo_k() * (score - verwacht))


def currency_beloning(tegenstander_mmr: int) -> int:
    return _currency_basis_winst() + round(tegenstander_mmr / 100) * _currency_bonus_per_100_mmr()


@dataclass
class MatchupResultaat:
    ronde_log: list[str]
    eigen_wint: bool
    # HP-restanten zijn (nog) puur informatief: de aanroeper gebruikt ze niet,
    # maar ze maken het resultaat wel zelfstandig te interpreteren en zijn
    # handig zodra een matchup-embed de eindstand in HP wil tonen.
    eigen_hp_over: int
    tegenstander_hp_over: int


def speel_matchup(
    eigen_macht_basis: float,
    tegenstander_macht_basis: float,
    tactiek: str,
    tegenstander_tactiek: str = "gebalanceerd",
    eigen_naam: str = "jij",
    tegenstander_naam: str = "tegenstander",
) -> MatchupResultaat:
    """Lost één 1v1-matchup op: meerdere interne rondes tot een kant 0 HP heeft
    of de rondelimiet bereikt wordt (dan wint wie meer HP over heeft).

    `tegenstander_tactiek` is 'gebalanceerd' bij PvE (passieve simulatie) of
    bij een PvP-tegenstander die zelf ook een tactiek koos. `eigen_naam`/
    `tegenstander_naam` zijn puur voor het rondelog: bij PvE blijft "jij"
    prima leesbaar, maar bij PvP kijken beide spelers naar hetzelfde
    bericht, dus geeft de aanroeper daar de echte namen door (anders leest
    "jij" voor de andere speler alsof het over hen gaat)."""
    eigen_hp = pet_hp(eigen_macht_basis)
    tegenstander_hp = pet_hp(tegenstander_macht_basis)
    log: list[str] = []

    for ronde in range(1, _max_interne_rondes() + 1):
        eigen_macht = macht_met_tactiek(eigen_macht_basis, tactiek)
        tegenstander_macht = macht_met_tactiek(tegenstander_macht_basis, tegenstander_tactiek)

        schade_aan_tegenstander = bereken_schade(eigen_macht)
        schade_aan_mij = bereken_schade(tegenstander_macht)

        tegenstander_hp = max(0, tegenstander_hp - schade_aan_tegenstander)
        eigen_hp = max(0, eigen_hp - schade_aan_mij)

        log.append(
            f"Ronde {ronde}: {eigen_naam} deelt {schade_aan_tegenstander} schade uit, "
            f"{tegenstander_naam} deelt {schade_aan_mij} schade uit."
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
