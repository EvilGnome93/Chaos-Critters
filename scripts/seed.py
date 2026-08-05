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
from db.models import Element, Instelling, Item, ItemType, PetSoort, Recept, Tier, Werkplek, WerkCyclus

# Kwalitatieve schaal -> placeholder-getal, later bij te stellen via admin panel.
ZEER_LAAG, LAAG, GEMIDDELD, HOOG, ZEER_HOOG, HOOGSTE = 10, 20, 40, 60, 80, 95

# Element per pet-soort (2026-07-26, backlog "Elementen & contra's"), zelf
# toegewezen op thema: waterdieren -> water, vliegende dieren -> lucht,
# felle/agressieve roofdieren -> vuur, alle Chaos-soorten -> chaos, de rest
# -> grond. Zie utils/elementen.py voor de contra-cirkel.
ELEMENT_MAP: dict[str, Element] = {
    # Grond
    "Hond (Zwerfhond)": Element.grond, "Kat (Steegkat)": Element.grond, "Konijn": Element.grond,
    "Egel": Element.grond, "Wasbeer": Element.grond, "Marter": Element.grond, "Eekhoorn": Element.grond,
    "Hagedis": Element.grond, "Kever": Element.grond, "Hert": Element.grond, "Hermelijn": Element.grond,
    "Slang": Element.grond, "Cavia": Element.grond, "Mier": Element.grond, "Slak": Element.grond,
    "Beer": Element.grond, "Fret": Element.grond, "Schaap": Element.grond, "Geit": Element.grond,
    "Muis": Element.grond, "Stekelvarken": Element.grond, "Hamster": Element.grond, "Varken": Element.grond,
    "Ezel": Element.grond, "Wezel": Element.grond, "Bunzing": Element.grond, "Alpaca": Element.grond,
    "Lama": Element.grond, "Kwartel": Element.grond, "Fazant": Element.grond, "Stokstaartje": Element.grond,
    "Gorilla": Element.grond, "Krekel": Element.grond, "Worm": Element.grond, "Kakkerlak": Element.grond,
    "Vlo": Element.grond, "Stinkdier": Element.grond, "Buidelrat": Element.grond, "Struisvogel": Element.grond,
    "Luiaard": Element.grond, "Koala": Element.grond, "Kalkoen": Element.grond, "Gordeldier": Element.grond,
    "Chimpansee": Element.grond, "Antilope": Element.grond, "Kiwi": Element.grond, "Bizon": Element.grond,
    "Orang oetan": Element.grond, "Panda": Element.grond, "Rode Panda": Element.grond,
    # Achtste lichting (2026-07-27): 25 nieuwe soorten, verzoek van de
    # gebruiker (4 zelf aangedragen: Steur, Mees, Schotse hooglander,
    # Koi-Karper; Mol vervangen door Aardvarken om geen dubbele Mol-familie
    # naast de bestaande Chaos Mol te krijgen — Schotse hooglander bewust wél
    # toegevoegd ondanks overlap met Bizon/Chaos Stier, op verzoek).
    "Schotse hooglander": Element.grond, "Aardvarken": Element.grond, "Kameel": Element.grond,
    "Zebra": Element.grond, "Maki": Element.grond, "Kwokka": Element.grond, "Klipdas": Element.grond,
    "Neusaap": Element.grond, "Okapi": Element.grond, "Wombat": Element.grond, "Rendier": Element.grond,
    "Pissebed": Element.grond,
    # Negende lichting (2026-08-04)
    "Wolfspin": Element.grond, "Tapir": Element.grond, "Muntjak": Element.grond,
    "Komodovaraan": Element.grond, "Neushoornkever": Element.grond,
    "Reuzenschildpad": Element.grond, "Reuzenmiereneter": Element.grond, "Mammoet": Element.grond,
    # Water
    "Eend": Element.water, "Otter": Element.water, "Gans": Element.water, "Krab": Element.water,
    "Zeehond": Element.water, "Kikker": Element.water, "Goudvis": Element.water, "Pelikaan": Element.water,
    "Flamingo": Element.water, "Kwal": Element.water, "Zwaan": Element.water, "Zeepaardje": Element.water,
    "IJsbeer": Element.water, "Krokodil": Element.water, "Anaconda": Element.water, "Walrus": Element.water,
    "Zeekoe": Element.water, "Haai": Element.water, "Axolotl": Element.water, "Garnaal": Element.water,
    "Pinguin": Element.water, "Schildpad": Element.water, "Rog": Element.water, "Vogelbekdier": Element.water,
    "Dolfijn": Element.water, "Zwaardvis": Element.water,
    "Steur": Element.water, "Koi-Karper": Element.water, "Walvis": Element.water, "Piranha": Element.water,
    "Zeester": Element.water, "Zeekomkommer": Element.water, "Zeeleeuw": Element.water, "Anemoon": Element.water,
    # Negende lichting (2026-08-04)
    "Watervlo": Element.water, "Zeepaling": Element.water, "Zeekat": Element.water,
    "Zee-egel": Element.water, "Walvishaai": Element.water, "Zeeslak": Element.water,
    # Lucht
    "Uil": Element.lucht, "Steenarend": Element.lucht, "Valk": Element.lucht, "Duif": Element.lucht,
    "Specht": Element.lucht, "Havik": Element.lucht, "Vleermuis": Element.lucht, "Pauw": Element.lucht,
    "Mus": Element.lucht, "Kraai": Element.lucht, "Kraanvogel": Element.lucht, "Parkiet": Element.lucht,
    "Gier": Element.lucht, "Vlinder": Element.lucht, "Kolibrie": Element.lucht, "Ekster": Element.lucht,
    "Libelle": Element.lucht, "Bij": Element.lucht, "Lieveheersbeestje": Element.lucht,
    "Mees": Element.lucht,
    # Negende lichting (2026-08-04)
    "Zwaluw": Element.lucht, "IJsvogel": Element.lucht, "Vuurvlieg": Element.lucht,
    "Grutto": Element.lucht, "Kwikstaart": Element.lucht, "Vleermuisvos": Element.lucht,
    # Vuur (felle/agressieve dieren)
    "Vos": Element.vuur, "Wolf": Element.vuur, "Lynx": Element.vuur, "Das": Element.vuur,
    "Tijger": Element.vuur, "Panter": Element.vuur, "Neushoorn": Element.vuur, "Luipaard": Element.vuur,
    "Poema": Element.vuur, "Hyena": Element.vuur, "Veelvraat": Element.vuur, "Nijlpaard": Element.vuur,
    "Vuurvis": Element.vuur, "Mantisgarnaal": Element.vuur,
    # Negende lichting (2026-08-04): net als Vuurvis/Mantisgarnaal hierboven
    # zijn dit geen mammals maar wél "klein/aquatisch maar gevaarlijk"
    # (Schorpioen, Buideldas) of "agressieve waterjager" (Orka).
    "Schorpioen": Element.vuur, "Buideldas": Element.vuur, "Orka": Element.vuur,
    # Chaos (alle Chaos-soorten)
    "Chaos Kip": Element.chaos, "Chaos Eenhoorn": Element.chaos, "Chaos Rat": Element.chaos,
    "Chaos Bever": Element.chaos, "Chaos Zwijn": Element.chaos, "Chaos Mol": Element.chaos,
    "Chaos Reiger": Element.chaos, "Chaos Olifant": Element.chaos, "Chaos Spin": Element.chaos,
    "Chaos Kameleon": Element.chaos, "Chaos Giraffe": Element.chaos, "Chaos Kangoeroe": Element.chaos,
    "Chaos Toekan": Element.chaos, "Chaos Octopus": Element.chaos, "Chaos Stier": Element.chaos,
    "Chaos Sprinkhaan": Element.chaos, "Chaos Papegaai": Element.chaos, "Chaos Wasbeerhond": Element.chaos,
    "Blobvis": Element.chaos, "Pijlgifkikker": Element.chaos,
    # Negende lichting (2026-08-04): Griffioen en Feniks (mythische wezens)
    # zijn vervangen door deze twee echte dieren met een chaos-flavor, zelfde
    # reden als eerder Griffioen/Chaos Basilisk (2026-07-24): mythische
    # wezens passen niet tussen de verder allemaal echte dieren, ook niet als
    # Chaos-variant. Zie feedback_pet_design_variety.
    "Chaos Wandelende Tak": Element.chaos, "Chaos Casuaris": Element.chaos,
}

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
        # 2026-07-28, Balans-audit: was 1 (kleinste van alle werkplekken),
        # maar Maanschijnkristal (alleen hier) werd sinds de ranked-lek-fix
        # ook nodig voor Extra match token — dat legde onbedoeld extra druk
        # op precies de krapste werkplek.
        "capaciteit": 2,
    },
    {
        "type": "Mijnschacht",
        "vereiste_werk_genen": "Kracht/graafvermogen",
        "output_per_uur": 6.5,
        "capaciteit": 2,
    },
]

# De shift-varianten van /werk (2026-07-30, admin panel fase 2 blok 3: waren
# hardcoded in cogs/werk.py). `duur_uren` is altijd de ECHTE duur; de
# dev-versnelling wordt pas toegepast in utils/balans.py:werk_cycli().
# Ook al ingevoegd door migratie b16522d16fa3 (de bot draait wel migraties
# maar niet de seed bij opstart) — hier voor een verse database.
WERK_CYCLI_RIJEN = [
    {"sleutel": "korte", "label": "Korte shift", "duur_uren": 2, "energie_kost": 20,
     "output_multiplier": 2.0, "volgorde": 1},
    {"sleutel": "lange", "label": "Lange shift", "duur_uren": 6, "energie_kost": 50,
     "output_multiplier": 2.3, "volgorde": 2},
    {"sleutel": "overnacht", "label": "Overnacht", "duur_uren": 10, "energie_kost": 70,
     "output_multiplier": 2.6, "volgorde": 3},
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
    ("Fazant", 2, LAAG, GEMIDDELD, "Bos", "Kleurrijke grondbewoner, houdt zich schuil in het Bos"),
    ("Stokstaartje", 2, LAAG, GEMIDDELD, None, "Altijd op wacht, kleine kans om een ontsnapping te voorkomen bij vangst"),
    ("Chaos Kangoeroe", 2, GEMIDDELD, GEMIDDELD, None, "Onvoorspelbare stats die dagelijks licht wisselen, onberekenbare trapaanval"),
    ("Chaos Toekan", 2, GEMIDDELD, GEMIDDELD, "Bos", "Onvoorspelbare stats die dagelijks licht wisselen, opvallende kleuren in het Bos"),
    ("IJsbeer", 4, ZEER_HOOG, LAAG, None, "Ongenaakbare kracht, imposant en moeilijk te stoppen in gevechten"),
    ("Luipaard", 4, HOOG, GEMIDDELD, None, "Snelheidsbonus, lastig te raken in een gevecht"),
    ("Poema", 4, ZEER_HOOG, LAAG, None, "Bijna geruisloze jager, kleine kans op een ongeschonden overwinning"),
    ("Krokodil", 4, HOOG, LAAG, "Vijver", "Verpletterende bijtkracht, sterke verdediger op de Vijver"),
    ("Anaconda", 4, HOOG, LAAG, "Vijver", "Verstikkende greep vermindert de macht van de tegenstander"),
    ("Hyena", 4, HOOG, GEMIDDELD, None, "Jaagt in groepen, wordt sterker wanneer meerdere Hyena's tegelijk vechten"),
    ("Gier", 4, LAAG, GEMIDDELD, None, "Herstelt sneller van een blessure dan andere pets"),
    ("Walrus", 4, HOOG, LAAG, "Vijver", "Dikke huid vermindert opgelopen schade in elk gevecht"),
    ("Zeekoe", 4, GEMIDDELD, LAAG, "Vijver", "Kalmerende reus, blijdschap-bonus voor het hele team"),
    ("Haai", 4, ZEER_HOOG, LAAG, "Vijver", "Ruikt zwakte: extra schade tegen een tegenstander onder de halve HP"),
    ("Veelvraat", 4, ZEER_HOOG, GEMIDDELD, None, "Vecht feller naarmate de eigen HP lager wordt"),
    ("Gorilla", 4, HOOGSTE, GEMIDDELD, None, "Slaat zich op de borst vóór het gevecht, verzwakt de tegenstander in de eerste ronde"),
    ("Nijlpaard", 4, ZEER_HOOG, LAAG, "Vijver", "Verrassend agressief ondanks de logge indruk"),
    ("Chaos Octopus", 4, GEMIDDELD, GEMIDDELD, "Vijver", "Onvoorspelbare stats die dagelijks licht wisselen, tentakel-verwarring op de Vijver"),
    ("Chaos Stier", 4, GEMIDDELD, GEMIDDELD, None, "Onvoorspelbare stats die dagelijks licht wisselen, charge-aanval met wisselende kracht"),
    # Zesde lichting (2026-07-24): 10 soorten om van 90 naar 100 te gaan,
    # verdeeld als 5 Common/3 Uncommon/1 Rare/1 Epic om de kans-per-soort
    # tussen tiers iets gelijkmatiger te maken (was een knik tussen Uncommon
    # ~1,67% en Rare ~0,86% per soort). Bewust een nieuwe dierhoek (insecten/
    # ongedierte) voor Common, geen overlap met bestaande dierfamilies.
    ("Krekel", 1, ZEER_LAAG, LAAG, "Moestuin", "Onopvallend en makkelijk over het hoofd te zien, kleine ontsnappingskans bij vangst"),
    ("Vlinder", 1, ZEER_LAAG, LAAG, "Moestuin", "Fladdert vrolijk rond, kleine blijdschap-bonus voor het team"),
    ("Worm", 1, ZEER_LAAG, GEMIDDELD, "Moestuin", "Onopvallende bodembewoner, moeilijk te vangen tussen de aarde"),
    ("Kakkerlak", 1, LAAG, HOOG, "Werkbank", "Overleeft bijna alles, nooit ziek en zelden vermoeid"),
    ("Vlo", 1, ZEER_LAAG, LAAG, None, "Piepklein en lastig te vangen, springt weg bij de minste beweging"),
    ("Stinkdier", 2, GEMIDDELD, LAAG, None, "Verspreidt een afschrikkende geur, verkleint de kans op een tweede aanval van de tegenstander"),
    ("Kolibrie", 2, LAAG, GEMIDDELD, "Moestuin", "Razendsnelle vleugelslag, bijna nooit als eerste geraakt in een gevecht"),
    ("Buidelrat", 2, LAAG, GEMIDDELD, "Bos", "Speelt dood bij gevaar, kleine kans om een verloren gevecht toch te overleven"),
    ("Axolotl", 3, GEMIDDELD, LAAG, "Vijver", "Regenereert razendsnel, kortere blessure-duur na een gevecht"),
    ("Struisvogel", 4, HOOG, GEMIDDELD, None, "Krachtige trap-aanval en indrukwekkende snelheid ondanks het formaat"),
    # Zevende lichting (2026-07-24): 19 namen van de gebruiker, zelf verdeeld
    # over tiers + 6 eigen soorten aangevuld tot 25 (Walvis, Antilope,
    # Zwaardvis, Garnaal, Kiwi, Wasbeerhond). De gebruikerslijst heeft zelf
    # wat familie-overlap met bestaand werk (Panda/Beer/IJsbeer,
    # Orang oetan+Chimpansee/Gorilla, Papegaai/Parkiet, Naaktslak/Slak) —
    # bewust niet gecorrigeerd op expliciet verzoek, wel over verschillende
    # tiers verdeeld om het iets te verzachten.
    ("Luiaard", 1, ZEER_LAAG, ZEER_LAAG, None, "Trager dan traag, doet het minimale en dat met plezier"),
    ("Koala", 1, ZEER_LAAG, LAAG, "Bos", "Slaapt het grootste deel van de dag in de boomtoppen"),
    ("Kalkoen", 1, LAAG, GEMIDDELD, "Moestuin", "Statige boerenerf-bewoner, laat zich niet gek maken"),
    ("Lieveheersbeestje", 1, ZEER_LAAG, LAAG, "Moestuin", "Eet ongedierte op, geliefd bij tuiniers"),
    ("Ekster", 1, LAAG, GEMIDDELD, None, "Steelt graag glimmende spulletjes, kleine kans op een bonus-item bij het werk"),
    ("Libelle", 1, LAAG, LAAG, "Vijver", "Zweeft en schiet vliegensvlug heen en weer boven het water"),
    ("Bij", 1, LAAG, HOOG, "Moestuin", "Onvermoeibare bestuiver, harde werker ondanks het formaat"),
    ("Gordeldier", 1, LAAG, LAAG, None, "Rolt zich op tot een bal bij gevaar, verrassend goede verdediging voor zijn tier"),
    ("Chaos Sprinkhaan", 1, GEMIDDELD, GEMIDDELD, "Moestuin", "Onvoorspelbare stats die dagelijks licht wisselen, springt onvoorspelbaar door het veld"),
    ("Garnaal", 1, ZEER_LAAG, LAAG, "Vijver", "Piepklein bewonertje van de Vijver, bijna onzichtbaar"),
    ("Pinguin", 2, LAAG, GEMIDDELD, "Vijver", "Onhandig op het land, verrassend soepel in het water"),
    ("Schildpad", 2, GEMIDDELD, LAAG, None, "Trage maar taaie verdediger, kruipt bij gevaar in zijn schild"),
    ("Rog", 2, LAAG, GEMIDDELD, "Vijver", "Glijdt sierlijk over de bodem van de Vijver"),
    ("Vogelbekdier", 2, LAAG, GEMIDDELD, "Vijver", "Uniek en moeilijk te categoriseren, verrassend behendig"),
    ("Chimpansee", 2, GEMIDDELD, HOOG, "Bos", "Slim en behendig, gebruikt gereedschap om efficiënter te werken"),
    ("Antilope", 2, LAAG, HOOG, "Bos", "Razendsnelle hardloper, moeilijk bij te houden"),
    ("Kiwi", 2, LAAG, GEMIDDELD, None, "Schuwe nachtdier, vliegt niet maar is verrassend rap te voet"),
    ("Bizon", 3, HOOG, GEMIDDELD, None, "Fors en onverzettelijk, moeilijk om tegen te houden"),
    ("Dolfijn", 3, GEMIDDELD, HOOG, "Vijver", "Intelligent en snel, geniet zichtbaar van het werk in de Vijver"),
    ("Orang oetan", 3, GEMIDDELD, HOOG, "Bos", "Slimme boombewoner, lost problemen vindingrijk op"),
    ("Chaos Papegaai", 3, GEMIDDELD, GEMIDDELD, None, "Onvoorspelbare stats die dagelijks licht wisselen, praat de tegenstander in de war tijdens een gevecht"),
    ("Panda", 3, GEMIDDELD, LAAG, "Bos", "Ontspannen en sterk, maar het liefst zo min mogelijk moeite doen"),
    ("Zwaardvis", 3, HOOG, LAAG, "Vijver", "Scherpe, snelle aanvaller met een gevaarlijke punt"),
    ("Chaos Wasbeerhond", 3, GEMIDDELD, GEMIDDELD, "Bos", "Onvoorspelbare stats die dagelijks licht wisselen, sluwe bosbewoner met een ondoorgrondelijke uitstraling"),
    ("Rode Panda", 4, HOOG, GEMIDDELD, "Bos", "Behendige klimmer met verrassend scherpe klauwen, moeilijker te raken dan het uiterlijk doet vermoeden"),
    # Achtste lichting (2026-07-27): 25 nieuwe soorten, verzoek van de
    # gebruiker. Mol vervangen door Aardvarken (dubbele familie met de
    # bestaande Chaos Mol); Schotse hooglander bewust wél gehouden ondanks
    # overlap met Bizon/Chaos Stier, op expliciet verzoek van de gebruiker.
    ("Steur", 3, LAAG, GEMIDDELD, "Vijver", "Oeroude reuzenvis, geduldig en moeilijk onder de indruk te krijgen"),
    ("Koi-Karper", 2, ZEER_LAAG, GEMIDDELD, "Vijver", "Sierlijke vijvervis in felle kleuren, brengt geluk volgens de overlevering"),
    ("Mees", 1, LAAG, HOOG, "Moestuin", "Klein en energiek, foerageert de hele dag door tussen de planten"),
    ("Schotse hooglander", 2, GEMIDDELD, HOOG, "Moestuin", "Ruige vacht en indrukwekkende hoorns, onverstoorbaar hard werkend"),
    ("Aardvarken", 3, LAAG, HOOG, "Mijnschacht", "Gravende specialist, wroet moeiteloos door de hardste grond"),
    ("Kameel", 3, GEMIDDELD, HOOG, "Bos", "Kan dagenlang doorwerken zonder klagen"),
    ("Zebra", 3, GEMIDDELD, GEMIDDELD, "Bos", "Verwarrend strepenpatroon, lastig scherp te krijgen voor een tegenstander"),
    ("Maki", 3, LAAG, HOOG, "Bos", "Behendige klimmer met een opvallend geringde staart"),
    ("Walvis", 5, ZEER_HOOG, LAAG, "Vijver", "Kolossale reus van de Vijver, macht die alles overstemt"),
    ("Kwokka", 2, LAAG, GEMIDDELD, "Bos", "Altijd vrolijk ogend, verrassend veerkrachtig in een gevecht"),
    ("Klipdas", 1, LAAG, GEMIDDELD, "Mijnschacht", "Klein rotsbewonertje, verrassend nauw verwant aan iets veel groters"),
    ("Piranha", 2, HOOG, LAAG, "Vijver", "Scherpe tandjes en weinig geduld, gevaarlijk in groepsverband"),
    ("Zeester", 1, ZEER_LAAG, LAAG, "Vijver", "Regenereert een verloren arm zonder enige moeite"),
    ("Neusaap", 4, GEMIDDELD, HOOG, "Bos", "Opvallende verschijning, zwemt verrassend goed voor een aap"),
    ("Okapi", 4, GEMIDDELD, HOOG, "Bos", "Schuwe bosbewoner, met de gestreepte poten bijna onzichtbaar tussen het gebladerte"),
    ("Wombat", 2, LAAG, HOOG, "Mijnschacht", "Graaft indrukwekkende tunnels, verdedigt zich met een keiharde achterkant"),
    ("Zeekomkommer", 1, ZEER_LAAG, LAAG, "Vijver", "Onopvallende bodembewoner, doet nooit haastig"),
    ("Rendier", 3, GEMIDDELD, HOOG, "Bos", "Hardnekkige doorzetter, trekt zwaar werk zonder ooit te vermoeien"),
    ("Zeeleeuw", 3, GEMIDDELD, GEMIDDELD, "Vijver", "Speelse acrobaat in het water, verrassend snelle aanvaller"),
    ("Anemoon", 1, LAAG, ZEER_LAAG, "Vijver", "Blijft het liefst op één plek, prikt onverwacht fel terug"),
    ("Pissebed", 1, ZEER_LAAG, GEMIDDELD, "Bos", "Rolt zich op tot een balletje bij gevaar, ijverige opruimer van de bosbodem"),
    ("Vuurvis", 4, HOOG, LAAG, "Vijver", "Giftige stekels en felle kleuren, een gewaarschuwde tegenstander telt voor twee"),
    ("Blobvis", 5, ZEER_LAAG, ZEER_LAAG, "Vijver", "Ziet er allesbehalve indrukwekkend uit, en toch..."),
    ("Mantisgarnaal", 4, ZEER_HOOG, GEMIDDELD, "Vijver", "Verpletterende klauwslag, een van de snelste aanvallen die er zijn"),
    ("Pijlgifkikker", 2, GEMIDDELD, LAAG, "Bos", "Piepklein maar levensgevaarlijk fel gekleurd"),
    # Negende lichting (2026-08-04): 25 nieuwe soorten, zelf verzonnen op
    # verzoek van de gebruiker (verzoek: "verzin deze zelf"). Bewust
    # uiteenlopende dierhoeken gekozen om niet op bestaande families te
    # stapelen (zie feedback_pet_design_variety): geen extra vossen/honden/
    # katachtigen/primaten/berenbovine's, wél frisse hoeken als spinachtigen
    # (Wolfspin, naast de al bestaande Schorpioen), cephalopoden (Zeekat
    # naast de bestaande Chaos Octopus) en twee niet-Chaos mythische wezens
    # (Feniks, Griffioen) als tegenhanger van de Chaos Eenhoorn.
    ("Zwaluw", 1, LAAG, GEMIDDELD, "Moestuin", "Snelle vlieger die insecten wegvangt boven de akkers"),
    ("IJsvogel", 1, LAAG, GEMIDDELD, "Vijver", "Feilloze duiker met een felgekleurd verenkleed, vangt vis in één beweging"),
    ("Vuurvlieg", 1, ZEER_LAAG, LAAG, "Nachtwacht", "Verlicht de nacht met een zachte gloed, onmisbaar gezelschap tijdens de overnacht-shift"),
    ("Schorpioen", 1, GEMIDDELD, LAAG, None, "Giftige angel in de staart, verrassend gevaarlijk voor zo'n klein tier"),
    ("Watervlo", 1, ZEER_LAAG, ZEER_LAAG, "Vijver", "Piepklein bewonertje van de vijver, bijna microscopisch klein"),
    ("Zeepaling", 1, LAAG, HOOG, "Vijver", "Glad en glibberig, bijna onmogelijk vast te houden"),
    ("Grutto", 1, LAAG, GEMIDDELD, "Moestuin", "Trekvogel die moeiteloos lange afstanden aflegt, thuis in het open veld"),
    ("Kwikstaart", 1, ZEER_LAAG, LAAG, "Vijver", "Wipt onophoudelijk met zijn staart, foerageert langs de waterkant"),
    ("Wolfspin", 2, GEMIDDELD, LAAG, None, "Jaagt actief zonder web, snel en doeltreffend"),
    ("Zeekat", 2, LAAG, GEMIDDELD, "Vijver", "Verandert moeiteloos van kleur, een sluwe illusionist onder water"),
    ("Tapir", 2, GEMIDDELD, HOOG, "Bos", "Verlegen bosbewoner met een opvallende snuit, ook een sterke zwemmer"),
    ("Zee-egel", 2, GEMIDDELD, ZEER_LAAG, "Vijver", "Bedekt met scherpe stekels, onaangenaam om zomaar op te pakken"),
    ("Muntjak", 2, LAAG, GEMIDDELD, "Bos", "Piepklein hertje met opvallende slagtandjes, verrassend om tegen te komen in het bos"),
    ("Komodovaraan", 3, HOOG, LAAG, None, "Reusachtige varaan met een giftige beet, de onbetwiste topjager van zijn eiland"),
    ("Vleermuisvos", 3, GEMIDDELD, GEMIDDELD, "Nachtwacht", "Vleermuis met een spanwijdte van een meter, foerageert 's nachts op fruit"),
    ("Buideldas", 3, HOOG, LAAG, None, "Berucht buideldier met een angstaanjagend gebrul en een verrassend felle bijtkracht"),
    ("Neushoornkever", 3, HOOG, LAAG, None, "Piepklein lichaam, enorme kracht: kan tot 850 keer zijn eigen gewicht dragen"),
    ("Walvishaai", 3, GEMIDDELD, HOOG, "Vijver", "Grootste vis ter wereld, een vreedzame reus die simpelweg water filtert voor voedsel"),
    ("Zeeslak", 3, ZEER_LAAG, GEMIDDELD, "Vijver", "Feloranje zeeslak zonder schelp, giftig voor wie het toch waagt te happen"),
    ("Orka", 4, ZEER_HOOG, LAAG, "Vijver", "Meedogenloze jager van de oceaan, jaagt slim en genadeloos in groepsverband"),
    ("Chaos Wandelende Tak", 4, GEMIDDELD, GEMIDDELD, "Bos", "Onvoorspelbare stats die dagelijks licht wisselen, vermomt zich zo goed dat niemand hem ooit ziet aankomen"),
    ("Reuzenschildpad", 4, GEMIDDELD, LAAG, None, "Kan honderden jaren oud worden, een ongelooflijk taaie verdediger ondanks het trage tempo"),
    ("Reuzenmiereneter", 4, HOOG, GEMIDDELD, "Bos", "Enorme klauwen en een kilometerslange tong, vernietigt mierenhopen moeiteloos"),
    ("Mammoet", 5, ZEER_HOOG, LAAG, None, "Uitgestorven reus uit een vergeten tijdperk, ongeëvenaarde kracht en een dikke vacht tegen de kou"),
    ("Chaos Casuaris", 5, HOOGSTE, HOOGSTE, None, "Onvoorspelbare stats die dagelijks licht wisselen, berucht als een van de gevaarlijkste vogels ter wereld met een dodelijke trap-aanval"),
]

# (itemnaam, honger_herstel, voerbak_vanaf) — welk item hoeveel honger
# aanvult en vanaf welk voerbak-niveau een voerbak het automatisch mag
# pakken ("simpel" = beide voerbakken, "slim" = alleen de Slimme). Items die
# hier niet in staan zijn geen voer; de Mysterie voedselzak hoort daar
# bewust bij, die simuleert bij gebruik een willekeurig ánder voedingsitem.
# 100 = volledig herstel, want honger wordt op 100 geklemd.
VOER_EFFECTEN = [
    ("Basis brokjes", 15, "simpel"),
    ("Graanvrije premium voeding", 40, "slim"),
    ("Vers vlees/vis", 100, "slim"),
]

# (naam, type, prijs, beschrijving)
ITEMS = [
    ("Basis brokjes", ItemType.voeding, 10, "Klein honger-herstel, goedkoop"),
    (
        "Graanvrije premium voeding",
        ItemType.voeding,
        35,
        "Groter honger-herstel + tijdelijke stat boost voor 1 match. Kost ook 12x Groente + 1x Water",
    ),
    ("Vers vlees/vis", ItemType.voeding, 60, "Volledig honger-herstel, duur. Kost ook 15x Algen + 8x Takken"),
    (
        "Simpele voerbak",
        ItemType.overig,
        100,
        "Per pet uit te rusten met /uitrusten. Voert de pet automatisch met Basis brokjes uit je "
        "inventaris (op = geen effect meer). Kost ook 2x Water + 2x Fruit",
    ),
    (
        "Slimme voerbak",
        ItemType.overig,
        250,
        "Per pet uit te rusten met /uitrusten. Voert de pet automatisch met je goedkoopste beschikbare "
        "voer (op = geen effect meer). Kost ook 40x Schroot + 20x Erts",
    ),
    (
        "Zelfreinigend systeem",
        ItemType.overig,
        300,
        "Per pet uit te rusten met /uitrusten. Energie herstelt ook buiten rust (bijv. tijdens werk). Kost ook 3x Sterrenstof + 20x Schroot",
    ),
    ("Focus drankje", ItemType.boost, 40, "Tijdelijke gevecht_genen boost voor 1 ranked match. Kost ook 2x Bladeren + 1x Edelsteen"),
    ("Werk-elixer", ItemType.boost, 40, "Tijdelijke werk_genen boost voor 1 werk cyclus. Kost ook 12x Erts + 2x Spijker"),
    (
        "Extra match token",
        ItemType.boost,
        150,
        "Koopt een ranked poging boven de dagelijkse gratis cooldown. Kost ook 30x Maanschijnkristal + 2x Edelsteen",
    ),
    ("Naamkaartje", ItemType.overig, 75, "Hernoem je pet. Kost ook 15x Takken + 1x Spijker"),
    ("Mysterie voedselzak", ItemType.voeding, 25, "Willekeurige voeding, goedkoper dan los kopen. Kost ook 1x Fruit + 1x Bladeren"),
    # Grondstoffen, verkregen via de werk-laag (sectie 6), niet los kopen in de shop.
    ("Groente", ItemType.grondstof, 0, "Grondstof, verkregen via werken in de Moestuin"),
    ("Algen", ItemType.grondstof, 0, "Grondstof, verkregen via werken bij de Vijver"),
    ("Schroot", ItemType.materiaal, 0, "Upgrade-materiaal, verkregen via werken op de Werkbank"),
    ("Takken", ItemType.grondstof, 0, "Grondstof, verkregen via werken in het Bos"),
    ("Maanschijnkristal", ItemType.grondstof, 0, "Grondstof, verkregen via werken bij de Nachtwacht"),
    ("Erts", ItemType.grondstof, 0, "Grondstof, verkregen via werken in de Mijnschacht"),
    # Tweede, zeldzamere grondstof per werkplek (2026-07-26, verzoek van de
    # gebruiker): kleine kans per voltooide shift, los van de hoofdgrondstof.
    ("Fruit", ItemType.grondstof, 0, "Zeldzame bonus-grondstof, kleine kans via werken in de Moestuin"),
    ("Water", ItemType.grondstof, 0, "Zeldzame bonus-grondstof, kleine kans via werken bij de Vijver"),
    ("Spijker", ItemType.grondstof, 0, "Zeldzame bonus-grondstof, kleine kans via werken op de Werkbank"),
    ("Bladeren", ItemType.grondstof, 0, "Zeldzame bonus-grondstof, kleine kans via werken in het Bos"),
    ("Sterrenstof", ItemType.grondstof, 0, "Zeldzame bonus-grondstof, kleine kans via werken bij de Nachtwacht"),
    ("Edelsteen", ItemType.grondstof, 0, "Zeldzame bonus-grondstof, kleine kans via werken in de Mijnschacht"),
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

# Tweede grondstof per werkplek, met een kleine kans per voltooide shift
# (Werkplek.opbrengst_2_kans, placeholder-waarde 0.25 voor iedereen — later
# bij te stellen, zie "Bekende balans-issues" in docs/dev-status.md).
WERKPLEK_BONUS_OPBRENGSTEN = {
    "Moestuin": "Fruit",
    "Vijver": "Water",
    "Werkbank": "Spijker",
    "Bos": "Bladeren",
    "Nachtwacht": "Sterrenstof",
    "Mijnschacht": "Edelsteen",
}

# Grondstofkosten bovenop de Chaos Coins-prijs, per craftbaar item
# (2026-07-30, admin panel fase 2 blok 4: waren de hardcoded RECEPT_KOSTEN-
# dict in cogs/verzorging.py, staan nu in de `recepten`-tabel met FK's).
# Ook al ingevoegd door migratie 584df3c7d2a4 — hier voor een verse database.
#
# Balans-achtergrond (2026-07-28, audit): elk recept vereist minstens 2
# verschillende grondstoffen uit 2 verschillende werkplekken.
# Hoofdgrondstoffen (gegarandeerd per shift) zijn de belangrijkste knop en
# dus fors hoger; bonus-grondstoffen (25%-kans per shift) blijven bewust
# klein, want die zijn door hun zeldzaamheid al traag genoeg.
RECEPTEN = {
    "Graanvrije premium voeding": [("Groente", 12), ("Water", 1)],
    "Vers vlees/vis": [("Algen", 15), ("Takken", 8)],
    "Mysterie voedselzak": [("Fruit", 1), ("Bladeren", 1)],
    "Naamkaartje": [("Takken", 15), ("Spijker", 1)],
    "Focus drankje": [("Bladeren", 2), ("Edelsteen", 1)],
    "Werk-elixer": [("Erts", 12), ("Spijker", 2)],
    "Extra match token": [("Maanschijnkristal", 30), ("Edelsteen", 2)],
    "Simpele voerbak": [("Water", 2), ("Fruit", 2)],
    "Slimme voerbak": [("Schroot", 40), ("Erts", 20)],
    "Zelfreinigend systeem": [("Sterrenstof", 3), ("Schroot", 20)],
}

INSTELLINGEN = [
    # LET OP: nog niet geïmplementeerd — cogs/vangen.py leest deze waarde
    # nergens, dus er is op dit moment geen vang-cooldown. De brief (sectie 1)
    # noemt 'm wel; blijft staan tot dat gebouwd is (2026-07-28, review).
    ("vang_cooldown_seconden", "30", "Cooldown per speler na een succesvolle vangst (NOG NIET ACTIEF)"),
    ("ranked_gratis_per_dag", "3", "Aantal gratis ranked pogingen per dag"),
    ("spawn_interval_min_berichten", "25", "Ondergrens van de activiteit-trigger voor spawns"),
    ("spawn_interval_max_berichten", "40", "Bovengrens van de activiteit-trigger voor spawns"),
    # 2026-07-28, Balans-audit: was 3, gelijk aan Moestuin's capaciteit (3) —
    # 1 speler kon zo in z'n eentje een hele gedeelde werkplek volledig
    # bezet houden. Op 2 kan dat nergens meer volledig.
    ("max_werkende_pets_per_speler", "2", "Max aantal pets dat een speler tegelijk aan het werk kan hebben"),
    # 2026-07-30, /changelog: rol die getagd wordt bij een goedgekeurde
    # changelog-aankondiging (leeg = geen tag). Losse instelling i.p.v.
    # hardcoded ID, want die verschilt per server (Botv3 hardcodet 'm wel,
    # maar die bot draait maar op één server).
    ("changelog_rol_id", "", "Rol-ID die getagd wordt bij een goedgekeurde changelog-aankondiging (leeg = geen tag)"),
    # 2026-07-30, admin panel fase 2, bewijs-blok voor utils/balans.py:
    # eerste twee losse balansconstanten verhuisd van hardcoded Python
    # (utils/elementen.py) naar hier, zodat de portal ze kan aanpassen.
    ("elementen_bonus", "1.15", "Machtsvermenigvuldiger bij een gunstig element in een gevecht-matchup"),
    ("elementen_malus", "0.90", "Machtsvermenigvuldiger bij een ongunstig element in een gevecht-matchup"),

    # 2026-07-30, admin panel fase 2, blok 2: resterende losse balans-
    # constanten verhuisd van hardcoded Python naar hier (zie utils/balans.py
    # en de per-bestand functies in utils/gevechten.py, utils/stats.py,
    # utils/leveling.py, cogs/werk.py, cogs/release.py).
    ("dev_versnelling", "120", "Compressiefactor voor tijdgebonden waarden in dev (honger/energie/slaap/blessure/ranked-reset)"),

    # utils/leveling.py
    ("xp_per_effectieve_uur", "180", "XP per effectief gewerkt uur (bepaalt het leveltempo)"),
    ("max_level", "50", "Maximumlevel voor pets"),
    ("genen_groei_per_level", "0.02", "Samengestelde groei op gevecht-/werk-genen per level-up (0.02 = 2%)"),
    ("level_xp_basis", "2000", "Vaste basis-XP die elk level kost, los van het levelnummer"),
    ("level_xp_per_level", "20", "Extra XP per level bovenop de basis (level x dit getal)"),

    # cogs/werk.py
    ("currency_per_grondstof", "2", "Chaos Coins per opgehaalde grondstof bij het afronden van een werk-shift"),
    ("bonus_grondstof_aantal", "1", "Aantal bonus-grondstof bij een geslaagde 2e-grondstof-roll"),

    # utils/stats.py
    ("honger_verval_minuten_echt", "20", "Echte minuten (buiten dev) voor -1 honger"),
    ("energie_herstel_minuten_echt", "10", "Echte minuten (buiten dev) voor +1 energie in rust"),
    ("energie_minimum", "20", "Onder dit energieniveau kan een pet niet ingezet worden"),
    ("slaap_cooldown_uur_echt", "24", "Echte uren (buiten dev) tussen twee /slaap-beurten per pet"),
    ("slaap_honger_kost", "20", "Hongerkosten van /slaap (instant volle energie)"),
    ("blessure_duur_uur_echt", "2", "Echte uren (buiten dev) dat een pet geblesseerd blijft na een verloren matchup"),

    # utils/gevechten.py
    ("max_interne_rondes", "5", "Maximum aantal interne rondes per gevecht-matchup"),
    ("schade_fractie", "0.35", "Aandeel van de macht-die-ronde dat als schade wordt toegebracht"),
    ("elo_k", "32", "Elo K-factor voor MMR-aanpassing na een ranked-gevecht"),
    ("currency_basis_winst", "20", "Vaste basis Chaos Coins bij het winnen van een ranked-gevecht"),
    ("currency_bonus_per_100_mmr", "2", "Extra Chaos Coins per 100 MMR van de verslagen tegenstander"),
    ("xp_winst", "30", "XP voor het hele team bij het winnen van een gevecht"),
    ("xp_verlies", "10", "XP voor het hele team bij het verliezen van een gevecht"),
    ("energie_kost_min", "10", "Minimale energiekosten per pet, per gevecht"),
    ("energie_kost_max", "20", "Maximale energiekosten per pet, per gevecht"),
    ("ranked_reset_uur_echt", "24", "Echte uren (buiten dev) tot de dagelijkse ranked-pogingen resetten"),
    # Willekeurige machtsvariatie per tactiek, als fractie: -0.25 = tot 25%
    # minder macht die ronde, 0.35 = tot 35% meer. Aggressief gokt hard,
    # voorzichtig speelt op safe. De drie tactieken liggen vast in de
    # keuzemenu's van /pvp en /pve, alleen deze zes getallen zijn zinvol
    # aanpasbaar (daarom losse sleutels en geen eigen tabel).
    ("tactiek_aggressief_variantie_min", "-0.25", "Aggressief: ondergrens van de machtsvariatie per ronde"),
    ("tactiek_aggressief_variantie_max", "0.35", "Aggressief: bovengrens van de machtsvariatie per ronde"),
    ("tactiek_gebalanceerd_variantie_min", "-0.15", "Gebalanceerd: ondergrens van de machtsvariatie per ronde"),
    ("tactiek_gebalanceerd_variantie_max", "0.15", "Gebalanceerd: bovengrens van de machtsvariatie per ronde"),
    ("tactiek_voorzichtig_variantie_min", "-0.10", "Voorzichtig: ondergrens van de machtsvariatie per ronde"),
    ("tactiek_voorzichtig_variantie_max", "0.10", "Voorzichtig: bovengrens van de machtsvariatie per ronde"),

    # cogs/release.py
    ("release_basis_coins", "15", "Basis Chaos Coins bij /release, vóór de tier-/level-vermenigvuldiging"),
    ("bonus_item_kans", "0.15", "Kans op een bonus-grondstof bij /release"),

    # utils/opdrachten.py — dagelijkse opdrachten (2026-08-05). De
    # opdracht-types zelf liggen vast in code (elk type heeft een eigen
    # verhoog()-aanroep op de juiste plek nodig), dus alleen deze doelen en
    # beloningen zijn zinvol aanpasbaar.
    ("opdracht_reset_uur", "4", "Uur (Europe/Amsterdam) waarop de dagelijkse opdrachten voor iedereen resetten"),
    ("opdracht_bonus_alle_drie", "150", "Extra Chaos Coins wanneer alle drie de dagopdrachten af zijn"),
    ("opdracht_vangen_doel", "3", "Dagopdracht 'vang critters': aantal te vangen critters"),
    ("opdracht_vangen_beloning", "60", "Dagopdracht 'vang critters': Chaos Coins bij voltooiing"),
    ("opdracht_werken_doel", "2", "Dagopdracht 'voltooi shifts': aantal af te ronden werk-cycli"),
    ("opdracht_werken_beloning", "70", "Dagopdracht 'voltooi shifts': Chaos Coins bij voltooiing"),
    ("opdracht_winnen_doel", "1", "Dagopdracht 'win gevechten': aantal te winnen gevechten"),
    ("opdracht_winnen_beloning", "80", "Dagopdracht 'win gevechten': Chaos Coins bij voltooiing"),
    ("opdracht_voeren_doel", "3", "Dagopdracht 'voer je pets': aantal keer voeren via /verzorg"),
    ("opdracht_voeren_beloning", "40", "Dagopdracht 'voer je pets': Chaos Coins bij voltooiing"),
    ("opdracht_craften_doel", "1", "Dagopdracht 'craft items': aantal te craften items"),
    ("opdracht_craften_beloning", "70", "Dagopdracht 'craft items': Chaos Coins bij voltooiing"),
    ("opdracht_zeldzaam_vangen_doel", "1", "Dagopdracht 'vang iets zeldzaams': aantal critters van Rare of hoger"),
    ("opdracht_zeldzaam_vangen_beloning", "90", "Dagopdracht 'vang iets zeldzaams': Chaos Coins bij voltooiing"),
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
        await session.execute(
            insert(WerkCyclus).on_conflict_do_nothing(index_elements=["sleutel"]), WERK_CYCLI_RIJEN
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
                "element": ELEMENT_MAP.get(naam),
            }
            for naam, tier_id, gevecht, werk, werkplek, beschrijving in PET_SOORTEN
        ]
        await session.execute(
            insert(PetSoort).on_conflict_do_nothing(index_elements=["naam"]), pet_soorten_rows
        )
        # Bestaande soorten (INSERT ON CONFLICT raakt ze niet aan) kregen op
        # 2026-07-26 voor het eerst een element toegewezen — expliciet bijwerken.
        for naam, element in ELEMENT_MAP.items():
            await session.execute(update(PetSoort).where(PetSoort.naam == naam).values(element=element))

        item_rows = [
            {"naam": naam, "type": type_, "prijs": prijs, "beschrijving": beschrijving}
            for naam, type_, prijs, beschrijving in ITEMS
        ]
        await session.execute(insert(Item).on_conflict_do_nothing(index_elements=["naam"]), item_rows)
        await session.flush()
        # Bestaande items (INSERT ON CONFLICT raakt ze niet aan) kregen op
        # 2026-07-27 scherpere beschrijvingen (voerbakken/zelfreinigend systeem
        # effect, recept-kosten) en een prijsupdate (Extra match token, zie
        # "Bekende balans-issues") — expliciet bijwerken.
        for naam, _type_, prijs, beschrijving in ITEMS:
            await session.execute(
                update(Item).where(Item.naam == naam).values(beschrijving=beschrijving, prijs=prijs)
            )

        # Voer-effecten (2026-07-30, admin panel fase 2 blok 5: waren de
        # hardcoded HONGER_HERSTEL_WAARDEN / VOLLEDIG_HERSTEL_ITEMS /
        # VOERBAK_ITEMS_PER_NIVEAU in utils/stats.py). Net als prijs en
        # beschrijving hierboven expliciet bijgewerkt, want de items zelf
        # bestaan al en worden door ON CONFLICT DO NOTHING niet geraakt.
        for naam, honger_herstel, voerbak_vanaf in VOER_EFFECTEN:
            await session.execute(
                update(Item)
                .where(Item.naam == naam)
                .values(honger_herstel=honger_herstel, voerbak_vanaf=voerbak_vanaf)
            )

        item_ids = {naam: id_ for naam, id_ in (await session.execute(select(Item.naam, Item.id))).all()}
        for werkplek_naam, item_naam in WERKPLEK_OPBRENGSTEN.items():
            await session.execute(
                update(Werkplek)
                .where(Werkplek.type == werkplek_naam)
                .values(opbrengst_item_id=item_ids[item_naam])
            )
        for werkplek_naam, item_naam in WERKPLEK_BONUS_OPBRENGSTEN.items():
            await session.execute(
                update(Werkplek)
                .where(Werkplek.type == werkplek_naam)
                .values(opbrengst_item_2_id=item_ids[item_naam])
            )

        # Recepten (2026-07-30, admin panel fase 2 blok 4: waren de hardcoded
        # RECEPT_KOSTEN-dict in cogs/verzorging.py). ON CONFLICT DO NOTHING op
        # (item, grondstof), dus een via de portal aangepast aantal blijft bij
        # een herrun staan — net als bij de andere seed-data.
        recept_rows = [
            {
                "item_id": item_ids[item_naam],
                "grondstof_id": item_ids[grondstof_naam],
                "aantal": aantal,
            }
            for item_naam, ingredienten in RECEPTEN.items()
            for grondstof_naam, aantal in ingredienten
            if item_naam in item_ids and grondstof_naam in item_ids
        ]
        if recept_rows:
            await session.execute(
                insert(Recept).on_conflict_do_nothing(index_elements=["item_id", "grondstof_id"]),
                recept_rows,
            )

        instelling_rows = [
            {"sleutel": sleutel, "waarde": waarde, "beschrijving": beschrijving}
            for sleutel, waarde, beschrijving in INSTELLINGEN
        ]
        await session.execute(
            insert(Instelling).on_conflict_do_nothing(index_elements=["sleutel"]), instelling_rows
        )
        # De *waarde* van een bestaande instelling blijft bewust staan (die
        # kan via het admin panel afgestemd zijn), maar de beschrijving is
        # puur documentatie voor de beheerder — die mag wel meelopen met de
        # code, net als bij de items hierboven (2026-07-28).
        for sleutel, _waarde, beschrijving in INSTELLINGEN:
            await session.execute(
                update(Instelling).where(Instelling.sleutel == sleutel).values(beschrijving=beschrijving)
            )

        await session.commit()

    print("Seed voltooid.")


if __name__ == "__main__":
    asyncio.run(seed())
