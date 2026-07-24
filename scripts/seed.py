"""Vult de statische startdata uit de projectbrief (secties 2-5, 7-8).

Idempotent: draait op basis van INSERT ... ON CONFLICT DO NOTHING, dus
opnieuw uitvoeren maakt geen duplicaten. Nieuwe/gewijzigde rijen in de
lijsten hieronder worden bij een herrun wel toegevoegd, bestaande rijen
worden niet overschreven (pas die zelf aan via het admin panel of direct
in de database).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from db.engine import async_session
from db.models import Instelling, Item, ItemType, PetSoort, Tier, Werkplek

# Kwalitatieve schaal -> placeholder-getal, later bij te stellen via admin panel.
ZEER_LAAG, LAAG, GEMIDDELD, HOOG, ZEER_HOOG, HOOGSTE = 10, 20, 40, 60, 80, 95

TIERS = [
    {"id": 1, "naam": "Common", "spawnkans": 0.45, "stat_multiplier": 1.0},
    {"id": 2, "naam": "Uncommon", "spawnkans": 0.25, "stat_multiplier": 1.2},
    {"id": 3, "naam": "Rare", "spawnkans": 0.18, "stat_multiplier": 1.4},
    {"id": 4, "naam": "Epic", "spawnkans": 0.09, "stat_multiplier": 1.7},
    {"id": 5, "naam": "Legendary", "spawnkans": 0.03, "stat_multiplier": 2.0},
]

WERKPLEKKEN = [
    {
        "type": "Moestuin",
        "vereiste_werk_genen": "Hoge werk_genen, lage vereisten",
        "output_per_uur": 5.0,
        "capaciteit": 3,
    },
    {
        "type": "Vijver",
        "vereiste_werk_genen": "Water-affiniteit",
        "output_per_uur": 6.0,
        "capaciteit": 2,
    },
    {
        "type": "Werkbank",
        "vereiste_werk_genen": "Behendigheid",
        "output_per_uur": 6.0,
        "capaciteit": 2,
    },
    {
        "type": "Bos",
        "vereiste_werk_genen": "Verkenning",
        "output_per_uur": 5.5,
        "capaciteit": 2,
    },
    {
        "type": "Nachtwacht",
        "vereiste_werk_genen": "Nacht-affiniteit",
        "output_per_uur": 7.0,
        "capaciteit": 1,
    },
    {
        "type": "Mijnschacht",
        "vereiste_werk_genen": "Kracht/graafvermogen",
        "output_per_uur": 6.5,
        "capaciteit": 2,
    },
]

# (naam, tier_id, gevecht_basis, werk_basis, werkplek_type of None, beschrijving)
PET_SOORTEN = [
    ("Hond (Zwerfhond)", 1, GEMIDDELD, HOOG, "Moestuin", None),
    ("Kat (Steegkat)", 1, GEMIDDELD, GEMIDDELD, "Werkbank", None),
    ("Konijn", 1, LAAG, HOOG, "Moestuin", None),
    ("Eend", 1, LAAG, GEMIDDELD, "Vijver", None),
    ("Egel", 1, LAAG, LAAG, None, "Hoge blijdschap-bonus"),
    ("Vos", 3, HOOG, GEMIDDELD, "Bos", None),
    ("Uil", 3, GEMIDDELD, HOOG, "Nachtwacht", "Bonus op overnacht shifts"),
    ("Wasbeer", 3, GEMIDDELD, HOOG, "Werkbank", "Heeft ook toegang tot de mijnschacht"),
    ("Otter", 3, LAAG, HOOG, "Vijver", "Snelste werker in de vijver"),
    ("Chaos Kip", 3, GEMIDDELD, GEMIDDELD, None, "Onvoorspelbare stats die dagelijks licht wisselen"),
    ("Wolf", 5, ZEER_HOOG, LAAG, None, None),
    (
        "Steenarend",
        5,
        HOOG,
        GEMIDDELD,
        None,
        "Verhoogt zeldzame spawn kans in zijn kanaal",
    ),
    (
        "Chaos Eenhoorn",
        5,
        HOOGSTE,
        HOOGSTE,
        None,
        "Willekeurige chaos events bij gebruik",
    ),
    # Tweede lichting (2026-07-21), aangeleverd als (soort, tier) door de
    # gebruiker; stats/werkplek/beschrijving hieronder ingevuld met dezelfde
    # aanpak als de eerste 13: omgekeerde correlatie gevecht/werk, en Legendary
    # (tier 5) zonder werkplek-voorkeur, zoals Wolf/Steenarend/Chaos Eenhoorn.
    ("Gans", 1, GEMIDDELD, HOOG, "Vijver", None),
    ("Marter", 1, GEMIDDELD, HOOG, "Werkbank", None),
    ("Chaos Rat", 1, LAAG, GEMIDDELD, None, "Vermenigvuldigt zich razendsnel, niemand weet precies hoeveel er rondlopen"),
    ("Eekhoorn", 1, LAAG, HOOG, "Bos", None),
    ("Hagedis", 1, LAAG, GEMIDDELD, "Moestuin", None),
    ("Kever", 1, LAAG, GEMIDDELD, "Moestuin", None),
    ("Valk", 3, HOOG, GEMIDDELD, "Nachtwacht", None),
    ("Hert", 3, GEMIDDELD, HOOG, "Bos", None),
    ("Chaos Bever", 3, GEMIDDELD, HOOG, "Bos", "Bouwt constructies die niemand gevraagd heeft, meestal midden in het bos"),
    ("Hermelijn", 3, GEMIDDELD, HOOG, "Werkbank", None),
    ("Lynx", 5, ZEER_HOOG, LAAG, None, "Legendarisch stille jager, vrijwel nooit gespot vóór de aanval"),
    ("Slang", 5, HOOG, GEMIDDELD, None, "Vrijwel onzichtbaar in het gras, glipt gemakkelijk voorbij vangpogingen"),
    ("Chaos Zwijn", 5, HOOGSTE, HOOGSTE, None, "Ontketent pure chaos zodra hij wordt losgelaten"),
    # Derde lichting (2026-07-23), aangeleverd door de gebruiker met dezelfde
    # aanpak: omgekeerde correlatie gevecht/werk, Legendary zonder
    # werkplek-voorkeur. Das/Chaos Mol krijgen de nieuwe Mijnschacht-werkplek
    # (voorheen alleen flavor-tekst bij Wasbeer).
    ("Duif", 1, LAAG, GEMIDDELD, "Moestuin", "Werkt goed op de Moestuin, stedelijk foerageren"),
    ("Cavia", 1, ZEER_LAAG, LAAG, None, "Hoogste blijdschap bonus van alle Common pets"),
    ("Krab", 1, GEMIDDELD, HOOG, "Werkbank", "Werkt efficiënt op de Werkbank door precisieklauwen"),
    ("Mier", 1, LAAG, HOOG, None, "Colony-bonus: efficiënter naarmate meer Mieren op dezelfde werkplek staan"),
    ("Chaos Mol", 1, GEMIDDELD, GEMIDDELD, "Mijnschacht", "Onvoorspelbare stats die dagelijks licht wisselen, sterk in de Mijnschacht"),
    ("Specht", 1, LAAG, HOOG, "Werkbank", "Werkt goed op de Werkbank, bonus kans op extra grondstof"),
    ("Slak", 1, ZEER_LAAG, LAAG, None, "Laagste energiekosten van alle pets, traag maar zuinig"),
    ("Das", 3, GEMIDDELD, HOOG, "Mijnschacht", "Sterk in de Mijnschacht, stevige verdediging in gevechten"),
    ("Zeehond", 3, LAAG, HOOG, "Vijver", "Snelste werker op de Vijver"),
    ("Havik", 3, HOOG, GEMIDDELD, None, "Kleine verkenner-bonus zoals Steenarend, maar zwakker effect"),
    ("Vleermuis", 3, GEMIDDELD, HOOG, "Nachtwacht", "Extra sterk tijdens de Nachtwacht overnacht-cyclus"),
    ("Chaos Reiger", 3, GEMIDDELD, GEMIDDELD, "Vijver", "Onvoorspelbare stats die dagelijks licht wisselen, sterk op de Vijver"),
    ("Beer", 5, ZEER_HOOG, LAAG, None, "Intimidatie-bonus: verhoogt winstkans tegen lagere tier teams"),
    ("Chaos Olifant", 5, HOOGSTE, HOOGSTE, None, "Willekeurige chaos events bij gebruik, unieke bonus op XP-gain"),
    # Vierde lichting (2026-07-24), aangeleverd door de gebruiker met dezelfde
    # aanpak: omgekeerde correlatie gevecht/werk, Legendary zonder
    # werkplek-voorkeur. "Laag-gemiddeld" (Geit) ingevuld als LAAG.
    ("Fret", 1, LAAG, HOOG, None, "Kan wisselen tussen werkplekken zonder cooldown verlies"),
    ("Schaap", 1, LAAG, GEMIDDELD, None, "Hoogste blijdschap herstel bij groepswerk"),
    ("Geit", 1, LAAG, HOOG, None, "Allrounder: geen efficiëntieverlies op elke werkplek"),
    ("Kikker", 1, LAAG, GEMIDDELD, "Vijver", "Sterk op de Vijver, extra kans op zeldzame grondstof"),
    ("Pauw", 1, LAAG, LAAG, None, "Verhoogt blijdschap van het hele team"),
    ("Goudvis", 1, ZEER_LAAG, LAAG, None, "Laagste onderhoudskosten van alle pets"),
    ("Muis", 1, LAAG, HOOG, None, "Snelste energie-herstel in rust"),
    ("Mus", 1, LAAG, GEMIDDELD, None, "Kleine kans op extra currency tijdens werk"),
    ("Chaos Spin", 1, GEMIDDELD, GEMIDDELD, "Werkbank", "Onvoorspelbare stats die dagelijks licht wisselen, sterk op de Werkbank"),
    ("Kraai", 3, GEMIDDELD, HOOG, None, "Kleine kans op bonus grondstof per werk-cyclus"),
    ("Pelikaan", 3, LAAG, HOOG, "Vijver", "Grotere opbrengst per werk-cyclus op de Vijver"),
    ("Flamingo", 3, LAAG, GEMIDDELD, "Vijver", "Hoogste blijdschap bonus op de Vijver"),
    ("Stekelvarken", 3, HOOG, LAAG, None, "Defensieve bonus, moeilijker te verslaan in gevechten"),
    ("Kwal", 3, GEMIDDELD, LAAG, None, "Vermindert tegenstander energie tijdens gevecht"),
    ("Zwaan", 3, GEMIDDELD, GEMIDDELD, None, "Elegante allrounder, kleine bonus op beide assen"),
    ("Chaos Kameleon", 3, GEMIDDELD, GEMIDDELD, None, "Onvoorspelbare stats die dagelijks licht wisselen, camouflage-bonus verhoogt ontsnappingskans bij vangst"),
    ("Tijger", 5, ZEER_HOOG, LAAG, None, "Sterkste directe impact in team gevechten"),
    ("Panter", 5, HOOG, GEMIDDELD, None, "Snelheidsbonus, verhoogt kans op eerste aanval"),
    ("Neushoorn", 5, ZEER_HOOG, LAAG, None, "Doorbreekt verdediging, bonus tegen defensieve teams"),
    ("Chaos Giraffe", 5, HOOGSTE, HOOGSTE, None, "Willekeurige chaos events, verhoogt zeldzame spawn kans in zijn kanaal"),
    # Vijfde lichting (2026-07-24): eerste soorten voor de nieuwe tussentiers
    # Uncommon (2) en Epic (4), zelf verzonnen (naam+stats+beschrijving) op
    # verzoek van de gebruiker. Afbeeldingen komen later — tot dan gebruikt
    # /vang de placeholder-afbeelding voor deze 30 soorten.
    ("Hamster", 2, ZEER_LAAG, LAAG, None, "Verzamelt stiekem extra voorraad, kleine kans op bonus grondstof"),
    ("Varken", 2, LAAG, HOOG, "Mijnschacht", "Wroet met de snuit dieper dan de meeste pets, sterk in de Mijnschacht"),
    ("Ezel", 2, LAAG, HOOG, "Bos", "Onvermoeibaar lastdier, houdt het langst vol op zware klussen in het Bos"),
    ("Wezel", 2, GEMIDDELD, HOOG, "Werkbank", "Rap en behendig, glipt overal tussendoor op de Werkbank"),
    ("Bunzing", 2, GEMIDDELD, GEMIDDELD, "Bos", "Familie van de Wezel, jaagt liever alleen door het Bos"),
    ("Zeepaardje", 2, ZEER_LAAG, LAAG, "Vijver", "Verlegen maar sierlijk, moeilijk te vangen tussen het riet"),
    ("Kraanvogel", 2, LAAG, GEMIDDELD, "Vijver", "Elegante wadervogel, geduldig en efficiënt op de Vijver"),
    ("Alpaca", 2, LAAG, GEMIDDELD, "Moestuin", "Kalmeert de rest van het team, kleine blijdschap-bonus"),
    ("Lama", 2, LAAG, HOOG, "Bos", "Sterker familielid van de Alpaca, uitstekend pakdier in het Bos"),
    ("Kwartel", 2, ZEER_LAAG, LAAG, "Moestuin", "Klein en schuw, moeilijk te vangen tussen het groen"),
    ("Parkiet", 2, ZEER_LAAG, LAAG, None, "Praatgraag, kleine blijdschap-bonus voor de rest van het team"),
    ("Faisant", 2, LAAG, GEMIDDELD, "Bos", "Kleurrijke grondbewoner, houdt zich schuil in het Bos"),
    ("Stokstaartje", 2, LAAG, GEMIDDELD, None, "Altijd op wacht, kleine kans om een ontsnapping te voorkomen bij vangst"),
    ("Chaos Kangoeroe", 2, GEMIDDELD, GEMIDDELD, None, "Onvoorspelbare stats die dagelijks licht wisselen, onberekenbare trapaanval"),
    ("Chaos Toekan", 2, GEMIDDELD, GEMIDDELD, "Bos", "Onvoorspelbare stats die dagelijks licht wisselen, opvallende kleuren in het Bos"),
    ("IJsbeer", 4, ZEER_HOOG, LAAG, None, "Ongenaakbare kracht, imposant en moeilijk te stoppen in gevechten"),
    ("Luipaard", 4, HOOG, GEMIDDELD, None, "Snelheidsbonus, lastig te raken in een gevecht"),
    ("Poema", 4, ZEER_HOOG, LAAG, None, "Bijna geruisloze jager, kleine kans op een ongeschonden overwinning"),
    ("Krokodil", 4, HOOG, LAAG, "Vijver", "Verpletterende bijtkracht, sterke verdediger op de Vijver"),
    ("Anaconda", 4, HOOG, LAAG, "Vijver", "Verstikkende greep vermindert de macht van de tegenstander"),
    ("Condor", 4, GEMIDDELD, GEMIDDELD, None, "Cirkelt hoog boven zijn kanaal, verhoogt de zeldzame spawnkans daar"),
    ("Gier", 4, LAAG, GEMIDDELD, None, "Herstelt sneller van een blessure dan andere pets"),
    ("Walrus", 4, HOOG, LAAG, "Vijver", "Dikke huid vermindert opgelopen schade in elk gevecht"),
    ("Zeekoe", 4, GEMIDDELD, LAAG, "Vijver", "Kalmerende reus, blijdschap-bonus voor het hele team"),
    ("Haai", 4, ZEER_HOOG, LAAG, "Vijver", "Ruikt zwakte: extra schade tegen een tegenstander onder de halve HP"),
    ("Veelvraat", 4, ZEER_HOOG, GEMIDDELD, None, "Vecht feller naarmate de eigen HP lager wordt"),
    ("Griffioen", 4, HOOGSTE, GEMIDDELD, None, "Mythisch roofdier, imponeert elk team van een lagere tier"),
    ("Nijlpaard", 4, ZEER_HOOG, LAAG, "Vijver", "Verrassend agressief ondanks de logge indruk"),
    ("Chaos Octopus", 4, GEMIDDELD, GEMIDDELD, "Vijver", "Onvoorspelbare stats die dagelijks licht wisselen, tentakel-verwarring op de Vijver"),
    ("Chaos Basilisk", 4, GEMIDDELD, GEMIDDELD, None, "Onvoorspelbare stats die dagelijks licht wisselen, verlammende blik houdt de tegenstander soms een ronde stil"),
]

# (naam, type, prijs, beschrijving)
ITEMS = [
    ("Basis brokjes", ItemType.voeding, 10, "Klein honger-herstel, goedkoop"),
    (
        "Graanvrije premium voeding",
        ItemType.voeding,
        35,
        "Groter honger-herstel + tijdelijke stat boost voor 1 match",
    ),
    ("Vers vlees/vis", ItemType.voeding, 60, "Volledig honger-herstel, duur"),
    ("Simpele voerbak", ItemType.overig, 100, "Klein passief energie herstel, eenmalige aankoop"),
    (
        "Slimme voerbak",
        ItemType.overig,
        250,
        "Beter passief herstel, vereist grondstoffen + Chaos Coins",
    ),
    (
        "Zelfreinigend systeem",
        ItemType.overig,
        300,
        "Verhoogt blijdschap automatisch, voorkomt stat verval bij afwezigheid",
    ),
    ("Focus drankje", ItemType.boost, 40, "Tijdelijke gevecht_genen boost voor 1 ranked match"),
    ("Werk-elixer", ItemType.boost, 40, "Tijdelijke werk_genen boost voor 1 werk cyclus"),
    (
        "Extra match token",
        ItemType.boost,
        50,
        "Koopt een ranked poging boven de dagelijkse gratis cooldown",
    ),
    ("Naamkaartje", ItemType.overig, 75, "Hernoem je pet"),
    ("Mysterie voedselzak", ItemType.voeding, 25, "Willekeurige voeding, goedkoper dan los kopen"),
    # Grondstoffen, verkregen via de werk-laag (sectie 6), niet los kopen in de shop.
    ("Groente", ItemType.grondstof, 0, "Grondstof, verkregen via werken in de Moestuin"),
    ("Algen", ItemType.grondstof, 0, "Grondstof, verkregen via werken bij de Vijver"),
    ("Schroot", ItemType.materiaal, 0, "Upgrade-materiaal, verkregen via werken op de Werkbank"),
    ("Takken", ItemType.grondstof, 0, "Grondstof, verkregen via werken in het Bos"),
    ("Maanschijnkristal", ItemType.grondstof, 0, "Grondstof, verkregen via werken bij de Nachtwacht"),
    ("Erts", ItemType.grondstof, 0, "Grondstof, verkregen via werken in de Mijnschacht"),
]

# Koppelt elke werkplek aan het grondstof-item dat hij oplevert.
WERKPLEK_OPBRENGSTEN = {
    "Moestuin": "Groente",
    "Vijver": "Algen",
    "Werkbank": "Schroot",
    "Bos": "Takken",
    "Nachtwacht": "Maanschijnkristal",
    "Mijnschacht": "Erts",
}

INSTELLINGEN = [
    ("vang_cooldown_seconden", "30", "Cooldown per speler na een succesvolle vangst"),
    ("ranked_gratis_per_dag", "3", "Aantal gratis ranked pogingen per dag"),
    ("spawn_interval_min_berichten", "25", "Ondergrens van de activiteit-trigger voor spawns"),
    ("spawn_interval_max_berichten", "40", "Bovengrens van de activiteit-trigger voor spawns"),
    ("max_werkende_pets_per_speler", "3", "Max aantal pets dat een speler tegelijk aan het werk kan hebben"),
]


async def seed() -> None:
    async with async_session() as session:
        await session.execute(
            insert(Tier).on_conflict_do_nothing(index_elements=["id"]), TIERS
        )
        # Tiers 1/3/5 bestonden al (INSERT ON CONFLICT raakt ze dus niet aan) en
        # kregen op 2026-07-24 nieuwe spawnkans-waardes i.v.m. de introductie
        # van tiers 2/4 (Uncommon/Epic) — expliciet bijwerken.
        for tier_data in TIERS:
            await session.execute(
                update(Tier)
                .where(Tier.id == tier_data["id"])
                .values(spawnkans=tier_data["spawnkans"], stat_multiplier=tier_data["stat_multiplier"])
            )
        await session.flush()

        await session.execute(
            insert(Werkplek).on_conflict_do_nothing(index_elements=["type"]), WERKPLEKKEN
        )
        await session.flush()

        werkplek_ids = {
            naam: id_
            for naam, id_ in (await session.execute(select(Werkplek.type, Werkplek.id))).all()
        }

        pet_soorten_rows = [
            {
                "naam": naam,
                "tier_id": tier_id,
                "gevecht_basis": gevecht,
                "werk_basis": werk,
                "werkplek_voorkeur_id": werkplek_ids[werkplek] if werkplek else None,
                "beschrijving": beschrijving,
            }
            for naam, tier_id, gevecht, werk, werkplek, beschrijving in PET_SOORTEN
        ]
        await session.execute(
            insert(PetSoort).on_conflict_do_nothing(index_elements=["naam"]), pet_soorten_rows
        )

        item_rows = [
            {"naam": naam, "type": type_, "prijs": prijs, "beschrijving": beschrijving}
            for naam, type_, prijs, beschrijving in ITEMS
        ]
        await session.execute(insert(Item).on_conflict_do_nothing(index_elements=["naam"]), item_rows)
        await session.flush()

        item_ids = {naam: id_ for naam, id_ in (await session.execute(select(Item.naam, Item.id))).all()}
        for werkplek_naam, item_naam in WERKPLEK_OPBRENGSTEN.items():
            await session.execute(
                update(Werkplek)
                .where(Werkplek.type == werkplek_naam)
                .values(opbrengst_item_id=item_ids[item_naam])
            )

        instelling_rows = [
            {"sleutel": sleutel, "waarde": waarde, "beschrijving": beschrijving}
            for sleutel, waarde, beschrijving in INSTELLINGEN
        ]
        await session.execute(
            insert(Instelling).on_conflict_do_nothing(index_elements=["sleutel"]), instelling_rows
        )

        await session.commit()

    print("Seed voltooid.")


if __name__ == "__main__":
    asyncio.run(seed())
