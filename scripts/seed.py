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
LAAG, GEMIDDELD, HOOG, ZEER_HOOG, HOOGSTE = 20, 40, 60, 80, 95

TIERS = [
    {"id": 1, "naam": "Common", "spawnkans": 0.70, "stat_multiplier": 1.0},
    {"id": 3, "naam": "Rare", "spawnkans": 0.25, "stat_multiplier": 1.4},
    {"id": 5, "naam": "Legendary", "spawnkans": 0.05, "stat_multiplier": 2.0},
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
    ("Ringslang", 5, HOOG, GEMIDDELD, None, "Vrijwel onzichtbaar in het gras, glipt gemakkelijk voorbij vangpogingen"),
    ("Chaos Zwijn", 5, HOOGSTE, HOOGSTE, None, "Ontketent pure chaos zodra hij wordt losgelaten"),
]

# (naam, type, prijs, beschrijving)
ITEMS = [
    ("Basis brokjes", ItemType.voeding, 10, "Kleine energie boost, goedkoop"),
    (
        "Graanvrije premium voeding",
        ItemType.voeding,
        35,
        "Grotere energie boost + tijdelijke stat boost voor 1 match",
    ),
    ("Vers vlees/vis", ItemType.voeding, 60, "Volledige energie herstel, duur"),
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
]

# Koppelt elke werkplek aan het grondstof-item dat hij oplevert.
WERKPLEK_OPBRENGSTEN = {
    "Moestuin": "Groente",
    "Vijver": "Algen",
    "Werkbank": "Schroot",
    "Bos": "Takken",
    "Nachtwacht": "Maanschijnkristal",
}

INSTELLINGEN = [
    ("vang_cooldown_seconden", "30", "Cooldown per speler na een succesvolle vangst"),
    ("ranked_gratis_per_dag", "3", "Aantal gratis ranked pogingen per dag"),
    ("spawn_interval_min_berichten", "25", "Ondergrens van de activiteit-trigger voor spawns"),
    ("spawn_interval_max_berichten", "40", "Bovengrens van de activiteit-trigger voor spawns"),
]


async def seed() -> None:
    async with async_session() as session:
        await session.execute(
            insert(Tier).on_conflict_do_nothing(index_elements=["id"]), TIERS
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
