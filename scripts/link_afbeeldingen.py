"""Koppelt afbeeldingen in docs/assets/ aan pet_soorten.afbeelding_url.

Zet een bestand in docs/assets/ met de exacte slug-naam hieronder (elke
gangbare extensie is prima: .png, .jpg, .jpeg, .webp, .gif) en draai dit
script. Het bouwt de raw.githubusercontent.com-URL op basis van de huidige
git-remote en branch, en zet die op de bijbehorende soort in de database.

Voorbeeld: docs/assets/vos.png -> gekoppeld aan pet-soort "Vos".
"""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from db.engine import async_session
from db.models import PetSoort

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "docs" / "assets"
TOEGESTANE_EXTENSIES = (".png", ".jpg", ".jpeg", ".webp", ".gif")

SOORT_SLUGS = {
    "Hond (Zwerfhond)": "hond",
    "Kat (Steegkat)": "kat",
    "Konijn": "konijn",
    "Eend": "eend",
    "Egel": "egel",
    "Vos": "vos",
    "Uil": "uil",
    "Wasbeer": "wasbeer",
    "Otter": "otter",
    "Chaos Kip": "chaos_kip",
    "Wolf": "wolf",
    "Steenarend": "steenarend",
    "Chaos Eenhoorn": "chaos_eenhoorn",
    "Gans": "gans",
    "Marter": "marter",
    "Chaos Rat": "chaos_rat",
    "Eekhoorn": "eekhoorn",
    "Hagedis": "hagedis",
    "Kever": "kever",
    "Valk": "valk",
    "Hert": "hert",
    "Chaos Bever": "chaos_bever",
    "Hermelijn": "hermelijn",
    "Lynx": "lynx",
    "Slang": "slang",
    "Chaos Zwijn": "chaos_zwijn",
    "Duif": "duif",
    "Cavia": "cavia",
    "Krab": "krab",
    "Mier": "mier",
    "Chaos Mol": "chaos_mol",
    "Specht": "specht",
    "Slak": "slak",
    "Das": "das",
    "Zeehond": "zeehond",
    "Havik": "havik",
    "Vleermuis": "vleermuis",
    "Chaos Reiger": "chaos_reiger",
    "Beer": "beer",
    "Chaos Olifant": "chaos_olifant",
    "Fret": "fret",
    "Schaap": "schaap",
    "Geit": "geit",
    "Kikker": "kikker",
    "Pauw": "pauw",
    "Goudvis": "goudvis",
    "Muis": "muis",
    "Mus": "mus",
    "Chaos Spin": "chaos_spin",
    "Kraai": "kraai",
    "Pelikaan": "pelikaan",
    "Flamingo": "flamingo",
    "Stekelvarken": "stekelvarken",
    "Kwal": "kwal",
    "Zwaan": "zwaan",
    "Chaos Kameleon": "chaos_kameleon",
    "Tijger": "tijger",
    "Panter": "panter",
    "Neushoorn": "neushoorn",
    "Chaos Giraffe": "chaos_giraffe",
    "Hamster": "hamster",
    "Varken": "varken",
    "Ezel": "ezel",
    "Wezel": "wezel",
    "Bunzing": "bunzing",
    "Zeepaardje": "zeepaardje",
    "Kraanvogel": "kraanvogel",
    "Alpaca": "alpaca",
    "Lama": "lama",
    "Kwartel": "kwartel",
    "Parkiet": "parkiet",
    "Fazant": "fazant",
    "Stokstaartje": "stokstaartje",
    "Chaos Kangoeroe": "chaos_kangoeroe",
    "Chaos Toekan": "chaos_toekan",
    "IJsbeer": "ijsbeer",
    "Luipaard": "luipaard",
    "Poema": "poema",
    "Krokodil": "krokodil",
    "Anaconda": "anaconda",
    "Hyena": "hyena",
    "Gier": "gier",
    "Walrus": "walrus",
    "Zeekoe": "zeekoe",
    "Haai": "haai",
    "Veelvraat": "veelvraat",
    "Gorilla": "gorilla",
    "Nijlpaard": "nijlpaard",
    "Chaos Octopus": "chaos_octopus",
    "Chaos Stier": "chaos_stier",
    "Krekel": "krekel",
    "Vlinder": "vlinder",
    "Worm": "worm",
    "Kakkerlak": "kakkerlak",
    "Vlo": "vlo",
    "Stinkdier": "stinkdier",
    "Kolibrie": "kolibrie",
    "Buidelrat": "buidelrat",
    "Axolotl": "axolotl",
    "Struisvogel": "struisvogel",
    "Luiaard": "luiaard",
    "Koala": "koala",
    "Kalkoen": "kalkoen",
    "Lieveheersbeestje": "lieveheersbeestje",
    "Ekster": "ekster",
    "Libelle": "libelle",
    "Bij": "bij",
    "Gordeldier": "gordeldier",
    "Chaos Sprinkhaan": "chaos_sprinkhaan",
    "Garnaal": "garnaal",
    "Pinguin": "pinguin",
    "Schildpad": "schildpad",
    "Rog": "rog",
    "Vogelbekdier": "vogelbekdier",
    "Chimpansee": "chimpansee",
    "Antilope": "antilope",
    "Kiwi": "kiwi",
    "Bizon": "bizon",
    "Dolfijn": "dolfijn",
    "Orang oetan": "orang_oetan",
    "Chaos Papegaai": "chaos_papegaai",
    "Panda": "panda",
    "Zwaardvis": "zwaardvis",
    "Chaos Wasbeerhond": "chaos_wasbeerhond",
    "Rode Panda": "rode_panda",
    "Steur": "steur",
    "Koi-Karper": "koi-karper",
    "Mees": "mees",
    "Schotse hooglander": "schotse_hooglander",
    "Aardvarken": "aardvarken",
    "Kameel": "kameel",
    "Zebra": "zebra",
    "Maki": "maki",
    "Walvis": "walvis",
    "Kwokka": "kwokka",
    "Klipdas": "klipdas",
    "Piranha": "piranha",
    "Zeester": "zeester",
    "Neusaap": "neusaap",
    "Okapi": "okapi",
    "Wombat": "wombat",
    "Zeekomkommer": "zeekomkommer",
    "Rendier": "rendier",
    "Zeeleeuw": "zeeleeuw",
    "Anemoon": "anemoon",
    "Pissebed": "pissebed",
    "Vuurvis": "vuurvis",
    "Blobvis": "blobvis",
    "Mantisgarnaal": "mantisgarnaal",
    "Pijlgifkikker": "pijlgifkikker",
    # Negende lichting (2026-08-04)
    "Zwaluw": "zwaluw",
    "IJsvogel": "ijsvogel",
    "Vuurvlieg": "vuurvlieg",
    "Schorpioen": "schorpioen",
    "Watervlo": "watervlo",
    "Zeepaling": "zeepaling",
    "Grutto": "grutto",
    "Kwikstaart": "kwikstaart",
    "Wolfspin": "wolfspin",
    "Zeekat": "zeekat",
    "Tapir": "tapir",
    "Zee-egel": "zee-egel",
    "Muntjak": "muntjak",
    "Komodovaraan": "komodovaraan",
    "Vleermuisvos": "vleermuisvos",
    "Buideldas": "buideldas",
    "Neushoornkever": "neushoornkever",
    "Walvishaai": "walvishaai",
    "Zeeslak": "zeeslak",
    "Orka": "orka",
    "Chaos Wandelende Tak": "chaos_wandelende_tak",
    "Reuzenschildpad": "reuzenschildpad",
    "Reuzenmiereneter": "reuzenmiereneter",
    "Mammoet": "mammoet",
    "Chaos Casuaris": "chaos_casuaris",
}


def _repo_en_branch() -> tuple[str, str]:
    remote = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True, cwd=REPO_ROOT).strip()
    repo = remote.removeprefix("https://github.com/").removesuffix(".git")
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, cwd=REPO_ROOT
    ).strip()
    return repo, branch


async def main() -> None:
    repo, branch = _repo_en_branch()
    gekoppeld: dict[str, str] = {}
    ontbrekend: list[str] = []

    for naam, slug in SOORT_SLUGS.items():
        bestand = next(
            (ASSETS_DIR / f"{slug}{ext}" for ext in TOEGESTANE_EXTENSIES if (ASSETS_DIR / f"{slug}{ext}").exists()),
            None,
        )
        if bestand is None:
            ontbrekend.append(f"{naam}  (verwacht: docs/assets/{slug}.png)")
            continue
        relatief = bestand.relative_to(REPO_ROOT).as_posix()
        gekoppeld[naam] = f"https://raw.githubusercontent.com/{repo}/{branch}/{relatief}"

    async with async_session() as session:
        for naam, url in gekoppeld.items():
            soort = await session.scalar(select(PetSoort).where(PetSoort.naam == naam))
            if soort is not None:
                soort.afbeelding_url = url
        await session.commit()

    print(f"Gekoppeld: {len(gekoppeld)}/{len(SOORT_SLUGS)}")
    for naam, url in gekoppeld.items():
        print(f"  {naam} -> {url}")

    if ontbrekend:
        print(f"\nNog ontbrekend ({len(ontbrekend)}):")
        for regel in ontbrekend:
            print(f"  {regel}")


if __name__ == "__main__":
    asyncio.run(main())
