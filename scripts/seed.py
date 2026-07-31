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
from db.models import Element, Instelling, Item, ItemType, PetSoort, Tier, Werkplek

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
    "Lama": Element.grond, "Kwartel": Element.grond, "Faisant": Element.grond, "Stokstaartje": Element.grond,
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
    # Lucht
    "Uil": Element.lucht, "Steenarend": Element.lucht, "Valk": Element.lucht, "Duif": Element.lucht,
    "Specht": Element.lucht, "Havik": Element.lucht, "Vleermuis": Element.lucht, "Pauw": Element.lucht,
    "Mus": Element.lucht, "Kraai": Element.lucht, "Kraanvogel": Element.lucht, "Parkiet": Element.lucht,
    "Gier": Element.lucht, "Vlinder": Element.lucht, "Kolibrie": Element.lucht, "Ekster": Element.lucht,
    "Libelle": Element.lucht, "Bij": Element.lucht, "Lieveheersbeestje": Element.lucht,
    "Mees": Element.lucht,
    # Vuur (felle/agressieve dieren)
    "Vos": Element.vuur, "Wolf": Element.vuur, "Lynx": Element.vuur, "Das": Element.vuur,
    "Tijger": Element.vuur, "Panter": Element.vuur, "Neushoorn": Element.vuur, "Luipaard": Element.vuur,
    "Poema": Element.vuur, "Hyena": Element.vuur, "Veelvraat": Element.vuur, "Nijlpaard": Element.vuur,
    "Vuurvis": Element.vuur, "Mantisgarnaal": Element.vuur,
    # Chaos (alle Chaos-soorten)
    "Chaos Kip": Element.chaos, "Chaos Eenhoorn": Element.chaos, "Chaos Rat": Element.chaos,
    "Chaos Bever": Element.chaos, "Chaos Zwijn": Element.chaos, "Chaos Mol": Element.chaos,
    "Chaos Reiger": Element.chaos, "Chaos Olifant": Element.chaos, "Chaos Spin": Element.chaos,
    "Chaos Kameleon": Element.chaos, "Chaos Giraffe": Element.chaos, "Chaos Kangoeroe": Element.chaos,
    "Chaos Toekan": Element.chaos, "Chaos Octopus": Element.chaos, "Chaos Stier": Element.chaos,
    "Chaos Sprinkhaan": Element.chaos, "Chaos Papegaai": Element.chaos, "Chaos Wasbeerhond": Element.chaos,
    "Blobvis": Element.chaos, "Pijlgifkikker": Element.chaos,
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
