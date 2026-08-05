"""Dagelijkse opdrachten (2026-08-05, verzoek van de gebruiker).

Drie willekeurige opdrachten per speler per dag, die op een vast tijdstip
voor iedereen tegelijk resetten. Elke afgeronde opdracht geeft Chaos Coins,
en alle drie afronden geeft een extra bonus.

**Waarom voortgang ophogen i.p.v. afleiden.** De verleiding is om de al
bestaande tellers te gebruiken (`Speler.shiften_voltooid`, `pvp_gewonnen`,
het aantal `Huisdier`-rijen). Dat gaat mis: het aantal Huisdier-rijen is je
*huidige* bezit, dus een `/release` zou de voortgang van "vang 3 critters"
weer laten dalen. Daarom houdt elke opdracht z'n eigen voortgang bij, die
opgehoogd wordt op het moment dat de gebeurtenis plaatsvindt.

**Waarom de types hardcoded zijn.** Elk opdracht-type heeft een aanroep van
`verhoog()` op de juiste plek in de code nodig; een rij toevoegen via het
admin panel zou dus niets doen. Alleen de doelen en beloningen zijn zinvol
aanpasbaar, en die staan als `Instelling` in de database — precies dezelfde
afweging als bij de tactiek-variantie (fase 2, blok 5).

**Waarom de dag om 04:00 draait en niet om middernacht.** Wie 's avonds laat
speelt zou anders midden in een sessie z'n voortgang kwijtraken. Het uur is
instelbaar via `opdracht_reset_uur`.
"""

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from db.models import SpelerOpdracht, Speler
from utils import balans

log = logging.getLogger("chaos_critters")

AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")

# Hoeveel opdrachten een speler per dag krijgt. Geen instelling: de bonus
# heet "alle drie af" en de embed is erop ingericht, dus dit getal zomaar
# kunnen wijzigen zou meer stukmaken dan het oplevert.
OPDRACHTEN_PER_DAG = 3


@dataclass(frozen=True)
class OpdrachtType:
    sleutel: str
    # Twee vormen, want de doelen zijn via het admin panel aanpasbaar en
    # Nederlandse meervouden zijn niet uniform (gevecht -> gevechten, shift
    # -> shifts, keer -> keer). Eén template met een losse "s" zou dus
    # "Win 1 gevechten" of "Voer je pets 3 keers" opleveren.
    enkelvoud: str
    meervoud: str
    emoji: str
    standaard_doel: int
    standaard_beloning: int

    def doel(self) -> int:
        return balans.get_int(f"opdracht_{self.sleutel}_doel", self.standaard_doel)

    def beloning(self) -> int:
        return balans.get_int(f"opdracht_{self.sleutel}_beloning", self.standaard_beloning)

    def tekst(self, doel: int) -> str:
        return (self.enkelvoud if doel == 1 else self.meervoud).format(doel=doel)


TYPES: dict[str, OpdrachtType] = {
    t.sleutel: t
    for t in (
        OpdrachtType("vangen", "Vang {doel} critter", "Vang {doel} critters", "🐾", 3, 60),
        OpdrachtType("werken", "Voltooi {doel} werk-shift", "Voltooi {doel} werk-shifts", "⛏️", 2, 70),
        OpdrachtType("winnen", "Win {doel} gevecht", "Win {doel} gevechten", "⚔️", 1, 80),
        OpdrachtType("voeren", "Voer je pets {doel} keer", "Voer je pets {doel} keer", "🍖", 3, 40),
        OpdrachtType("craften", "Craft {doel} item", "Craft {doel} items", "🔨", 1, 70),
        OpdrachtType(
            "zeldzaam_vangen",
            "Vang {doel} critter van Rare of hoger",
            "Vang {doel} critters van Rare of hoger",
            "💎",
            1,
            90,
        ),
    )
}

# Vanaf welk tier "zeldzaam_vangen" meetelt. Rare is tier 3; Uncommon (2)
# telt bewust niet mee, anders is de opdracht bijna gratis.
ZELDZAAM_VANAF_TIER = 3


def bonus_alle_drie() -> int:
    return balans.get_int("opdracht_bonus_alle_drie", 150)


def huidige_dag(nu: datetime | None = None) -> date:
    """De 'opdracht-dag' waar dit moment bij hoort. Draait om het ingestelde
    resetuur, dus om 02:00 hoor je nog bij de dag ervoor."""
    nu = nu or datetime.now(AMSTERDAM_TZ)
    if nu.tzinfo is None:
        nu = nu.replace(tzinfo=AMSTERDAM_TZ)
    else:
        nu = nu.astimezone(AMSTERDAM_TZ)
    return (nu - timedelta(hours=balans.get_int("opdracht_reset_uur", 4))).date()


def _nu() -> datetime:
    """Naïeve UTC, net als overal elders in de codebase (utils/stats.py)."""
    return datetime.now(AMSTERDAM_TZ).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


async def zorg_voor_opdrachten(session, speler_id: int, dag: date | None = None) -> list[SpelerOpdracht]:
    """Geeft de opdrachten van deze speler voor deze dag, en maakt ze aan als
    ze er nog niet zijn. Commit bewust niet zelf: aanroepers zitten al in een
    transactie (bijv. midden in het afhandelen van een vangst).

    Toewijzing gebeurt lui, bij de eerste aanroep van de dag — geen
    achtergrondtaak die voor alle spelers rijen zit te maken, ook voor wie
    die dag niet speelt."""
    dag = dag or huidige_dag()
    bestaand = (
        await session.execute(
            select(SpelerOpdracht).where(
                SpelerOpdracht.speler_id == speler_id, SpelerOpdracht.dag == dag
            )
        )
    ).scalars().all()
    if bestaand:
        return list(bestaand)

    # De speler moet bestaan voor de foreign key. Wie /opdrachten doet zonder
    # ooit iets gevangen te hebben heeft nog geen rij.
    if await session.get(Speler, speler_id) is None:
        session.add(Speler(discord_id=speler_id))
        await session.flush()

    gekozen = random.sample(list(TYPES.values()), k=min(OPDRACHTEN_PER_DAG, len(TYPES)))
    nieuw = [
        SpelerOpdracht(
            speler_id=speler_id,
            dag=dag,
            sleutel=type_.sleutel,
            voortgang=0,
            # Momentopname: een balanswijziging halverwege de dag verplaatst
            # zo niet de doelpaal van een opdracht die al loopt.
            doel=type_.doel(),
            beloning=type_.beloning(),
        )
        for type_ in gekozen
    ]
    session.add_all(nieuw)
    await session.flush()
    return nieuw


async def verhoog(session, speler_id: int, sleutel: str, aantal: int = 1) -> list[tuple[SpelerOpdracht, int]]:
    """Hoogt de voortgang op van de opdracht met deze sleutel, als de speler
    'm vandaag heeft. Geeft de zojuist voltooide opdrachten terug als
    [(opdracht, uitbetaald bedrag)] — leeg als er niets afgerond is.

    Het uitbetaalde bedrag is inclusief de "alle drie af"-bonus bij de
    laatste opdracht van de dag. Die bonus hangt bewust aan de overgang van
    `voltooid_op = NULL` naar een tijdstip: die gebeurt per opdracht precies
    één keer, dus dubbel uitbetalen kan niet.

    Commit niet zelf — de aanroeper zit al in een transactie, en zo blijft
    "de vangst is gelukt" en "de opdracht telde mee" één geheel."""
    if sleutel not in TYPES:
        # Een typefout in een aanroep mag geen stille no-op zijn.
        raise ValueError(f"Onbekende opdracht-sleutel: {sleutel!r}")

    opdrachten = await zorg_voor_opdrachten(session, speler_id)
    doel_opdracht = next((o for o in opdrachten if o.sleutel == sleutel), None)
    if doel_opdracht is None or doel_opdracht.voltooid_op is not None:
        return []

    doel_opdracht.voortgang = min(doel_opdracht.doel, doel_opdracht.voortgang + aantal)
    if doel_opdracht.voortgang < doel_opdracht.doel:
        return []

    doel_opdracht.voltooid_op = _nu()
    uitbetaald = doel_opdracht.beloning
    if all(o.voltooid_op is not None for o in opdrachten):
        uitbetaald += bonus_alle_drie()

    speler = await session.get(Speler, speler_id)
    if speler is not None:
        speler.currency += uitbetaald

    log.info(
        "Speler %s rondde dagopdracht '%s' af (+%d Chaos Coins)", speler_id, sleutel, uitbetaald
    )
    return [(doel_opdracht, uitbetaald)]


def _label(opdracht: SpelerOpdracht) -> str:
    type_ = TYPES.get(opdracht.sleutel)
    return type_.tekst(opdracht.doel) if type_ else opdracht.sleutel


def voltooiing_tekst(opdracht: SpelerOpdracht, uitbetaald: int) -> str:
    """Regel om achter een bestaand antwoord te plakken wanneer een actie een
    opdracht afrondde. Bewust geen apart bericht: dat zou elk commando een
    tweede response geven."""
    regel = f"\n\n✅ **Dagopdracht voltooid**: {_label(opdracht)} (+{opdracht.beloning} Chaos Coins)"
    extra = uitbetaald - opdracht.beloning
    if extra > 0:
        regel += f"\n🎉 **Alle drie de dagopdrachten af!** Bonus: +{extra} Chaos Coins"
    return regel


def voltooiing_tekst_derde_persoon(opdracht: SpelerOpdracht, uitbetaald: int, naam: str) -> str:
    """Zelfde melding, maar met de naam van de speler erbij. Nodig in de
    gevecht-embed: die is publiek en beide spelers kijken ernaar, dus "jij"
    zou daar dubbelzinnig zijn (zelfde reden als de expliciete weergavenamen
    in cogs/gevechten.py)."""
    regel = f"\n✅ {naam} voltooide een dagopdracht: {_label(opdracht)} (+{opdracht.beloning} Chaos Coins)"
    extra = uitbetaald - opdracht.beloning
    if extra > 0:
        regel += f"\n🎉 {naam} heeft alle drie de dagopdrachten af! Bonus: +{extra} Chaos Coins"
    return regel
