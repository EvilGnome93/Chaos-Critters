"""Check van /critterdex + /info (2026-07-28, verzoek van de gebruiker):
gepagineerd overzicht van alle pet-soorten met tier/element-filter en
"gevangen"-status, plus een losse soort-lookup met kwalitatieve
gevecht/werk-stats, werkplek-voorkeur en eigen vangst-aantal.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from cogs.critterdex import CritterdexCog, PET_SOORTEN_PER_PAGINA, _stat_label
from db.engine import async_session
from db.models import Huisdier, PetSoort, PetStatus, Speler

SPELER = 999999999999999971


def fake_interaction(user_id: int) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    bericht = MagicMock()
    interaction.original_response = AsyncMock(return_value=bericht)
    return interaction


def test_stat_label() -> None:
    print("-- _stat_label: kwalitatieve schaal --")
    assert _stat_label(10) == "Zeer laag"
    assert _stat_label(20) == "Laag"
    assert _stat_label(40) == "Gemiddeld"
    assert _stat_label(60) == "Hoog"
    assert _stat_label(80) == "Zeer hoog"
    assert _stat_label(95) == "Hoogste"
    print("Labels kloppen op de grenzen van de schaal.")


async def _maak_pet(session, speler_id: int, soort: PetSoort, naam: str) -> int:
    if await session.get(Speler, speler_id) is None:
        session.add(Speler(discord_id=speler_id, currency=0, mmr=1000, volgend_pet_nummer=1))
        await session.commit()
    speler = await session.get(Speler, speler_id)
    pet = Huisdier(
        eigenaar_id=speler_id, soort_id=soort.id, tier_id=soort.tier_id, naam=naam,
        volgnummer=speler.volgend_pet_nummer, gevecht_genen=50, werk_genen=50,
        status=PetStatus.rust, honger=100, energie=100,
    )
    speler.volgend_pet_nummer += 1
    session.add(pet)
    await session.commit()
    await session.refresh(pet)
    return pet.id


async def test_critterdex_paginering_en_filters() -> None:
    print("\n-- /critterdex: paginering + tier/element-filter + gevangen-status --")
    cog = CritterdexCog(bot=MagicMock())
    pet_ids: list[int] = []
    try:
        async with async_session() as session:
            vos = await session.scalar(select(PetSoort).where(PetSoort.naam == "Vos"))
            pet_ids.append(await _maak_pet(session, SPELER, vos, "TestVos"))

        async with async_session() as session:
            totaal_soorten = await session.scalar(select(func.count()).select_from(PetSoort))

        interactie = fake_interaction(SPELER)
        await cog.critterdex.callback(cog, interactie)
        interactie.response.send_message.assert_awaited()
        view = interactie.response.send_message.call_args.kwargs["view"]
        print(f"Totaal soorten: {len(view.alle_soorten)} (verwacht {totaal_soorten})")
        assert len(view.alle_soorten) == totaal_soorten
        assert view.max_pagina == (totaal_soorten - 1) // PET_SOORTEN_PER_PAGINA

        embed_pagina1 = view.huidige_embed()
        namen_pagina1 = [f.name for f in embed_pagina1.fields]
        print(f"Eerste pagina, {len(embed_pagina1.fields)} velden (verwacht {PET_SOORTEN_PER_PAGINA})")
        assert len(embed_pagina1.fields) == PET_SOORTEN_PER_PAGINA

        # Vos is gevangen -> zoek 'm op een pagina en check de "Gevangen"-tekst.
        vos_veld = next((f for f in _alle_velden(view) if f.name.endswith(" Vos")), None)
        assert vos_veld is not None
        print(f"Vos-veld: {vos_veld.name} -> {vos_veld.value}")
        assert "✅ Gevangen: 1x" in vos_veld.value

        # Tier-filter: alleen Legendary (id 5).
        view.tier_select._values = ["5"]
        await view.tier_select.callback(interactie)
        gefilterd = view.gefilterd
        print(f"Tier-filter Legendary: {len(gefilterd)} soorten, allemaal tier 5: {all(s.tier_id == 5 for s in gefilterd)}")
        assert gefilterd and all(s.tier_id == 5 for s in gefilterd)

        # Element-filter erbovenop: Legendary + Water.
        view.element_select._values = ["water"]
        await view.element_select.callback(interactie)
        gefilterd2 = view.gefilterd
        print(f"+ Element-filter Water: {len(gefilterd2)} soorten")
        assert all(s.tier_id == 5 and s.element.value == "water" for s in gefilterd2)
        print("Paginering en filters werken correct.")
    finally:
        async with async_session() as session:
            if pet_ids:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids)))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == SPELER))
            await session.commit()
        print("Testdata opgeruimd.")


def _alle_velden(view):
    """Doorloopt alle pagina's van de ongefilterde lijst en verzamelt de
    embed-velden, zodat we een specifieke soort kunnen terugvinden ongeacht
    op welke pagina die staat."""
    velden = []
    oorspronkelijke_pagina = view.pagina
    for pagina in range(view.max_pagina + 1):
        view.pagina = pagina
        velden.extend(view.huidige_embed().fields)
    view.pagina = oorspronkelijke_pagina
    return velden


async def test_info() -> None:
    print("\n-- /info: soort-lookup --")
    cog = CritterdexCog(bot=MagicMock())
    pet_ids: list[int] = []
    try:
        async with async_session() as session:
            vos = await session.scalar(select(PetSoort).where(PetSoort.naam == "Vos"))
            pet_ids.append(await _maak_pet(session, SPELER, vos, "TestVos"))

        interactie = fake_interaction(SPELER)
        await cog.info.callback(cog, interactie, soort="Vos")
        embed = interactie.response.send_message.call_args.kwargs["embed"]
        veld_waarden = {f.name: f.value for f in embed.fields}
        print(f"Titel: {embed.title}")
        print(f"Velden: {veld_waarden}")
        assert "Vos" in embed.title
        assert veld_waarden["Zelf gevangen"] == "✅ 1x"
        assert veld_waarden["Werkplek-voorkeur"] == "Bos"

        interactie_onbekend = fake_interaction(SPELER)
        await cog.info.callback(cog, interactie_onbekend, soort="Nietbestaanddier")
        bericht = interactie_onbekend.response.send_message.call_args[0][0]
        print(f"Onbekende soort: {bericht}")
        assert "Onbekende pet-soort" in bericht
        print("/info toont de juiste stats en behandelt een onbekende soort netjes.")
    finally:
        async with async_session() as session:
            if pet_ids:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids)))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == SPELER))
            await session.commit()
        print("Testdata opgeruimd.")


async def main() -> None:
    test_stat_label()
    await test_critterdex_paginering_en_filters()
    await test_info()
    print("\nAlle checks geslaagd.")


if __name__ == "__main__":
    asyncio.run(main())
