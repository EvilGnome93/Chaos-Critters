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
    "Chaos Eenhoorn-Ratrace-hybride": "chaos_eenhoorn",
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
