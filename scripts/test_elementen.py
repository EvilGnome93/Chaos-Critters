"""Handmatige check van elementen & contra's: de pure modifier-logica, en
een volledig PvE-gevecht via gesimuleerde Discord-interacties (echte
netwerk-downloads voor de VS-afbeelding, tegen GitHub's raw-CDN). Ruimt
zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.gevechten import GevechtenCog
from db.engine import async_session
from db.models import Element, Huisdier, PetSoort, PetStatus, Speler
from utils.elementen import elementen_modifier, emoji

SPELER_A = 999999999999999903


def fake_interaction(user_id: int, guild_id: int | None = None) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.guild_id = guild_id
    interaction.response = AsyncMock()
    bericht = MagicMock()
    bericht.edit = AsyncMock()
    interaction.original_response = AsyncMock(return_value=bericht)
    return interaction


def test_modifier_logica() -> None:
    print("-- elementen_modifier: vaste contra-cirkel --")
    assert elementen_modifier(Element.vuur, Element.lucht) == 1.15
    assert elementen_modifier(Element.lucht, Element.vuur) == 0.90
    assert elementen_modifier(Element.lucht, Element.grond) == 1.15
    assert elementen_modifier(Element.grond, Element.lucht) == 0.90
    assert elementen_modifier(Element.grond, Element.water) == 1.15
    assert elementen_modifier(Element.water, Element.grond) == 0.90
    assert elementen_modifier(Element.water, Element.vuur) == 1.15
    assert elementen_modifier(Element.vuur, Element.water) == 0.90
    assert elementen_modifier(Element.vuur, Element.grond) == 1.0
    assert elementen_modifier(Element.grond, Element.vuur) == 1.0
    print("Contra-cirkel klopt (Vuur > Lucht > Grond > Water > Vuur, neutraal op 2 stappen afstand).")

    print("\n-- elementen_modifier: chaos is willekeurig --")
    uitkomsten = {elementen_modifier(Element.chaos, Element.vuur) for _ in range(200)}
    print(f"uitkomsten over 200 pogingen: {uitkomsten} (verwacht: subset van 0.9/1.0/1.15)")
    assert uitkomsten <= {0.90, 1.0, 1.15}

    print("\n-- emoji-mapping --")
    for el in Element:
        print(f"{el.value}: {emoji(el)}")
    assert emoji(None) == "❓"


async def test_pve_gevecht() -> None:
    print("\n-- PvE-gevecht end-to-end met elementen + VS-afbeelding-code --")
    cog = GevechtenCog(bot=MagicMock())

    async with async_session() as session:
        if await session.get(Speler, SPELER_A) is None:
            session.add(Speler(discord_id=SPELER_A, currency=100, mmr=1000, volgend_pet_nummer=1))
            await session.commit()

        soorten = (
            await session.execute(select(PetSoort).where(PetSoort.element.isnot(None)).limit(3))
        ).scalars().all()
        assert len(soorten) == 3
        speler = await session.get(Speler, SPELER_A)
        pets = []
        for soort in soorten:
            pet = Huisdier(
                eigenaar_id=SPELER_A, soort_id=soort.id, tier_id=soort.tier_id, naam=f"Elementtest-{soort.naam}",
                volgnummer=speler.volgend_pet_nummer, gevecht_genen=50, werk_genen=50,
                status=PetStatus.team, honger=100, energie=100,
            )
            speler.volgend_pet_nummer += 1
            session.add(pet)
            pets.append(pet)
        await session.commit()
        for pet in pets:
            await session.refresh(pet)
        pet_ids = [p.id for p in pets]

    try:
        interactie = fake_interaction(SPELER_A)
        await cog.vecht.callback(cog, interactie)
        interactie.response.send_message.assert_awaited()
        view = interactie.response.send_message.call_args.kwargs["view"]
        print(f"intro-titel: {view.message}")  # message is de mock, alleen om te bevestigen dat start() liep

        # Los tot 3 matchups op met "gebalanceerd", ongeacht win/verlies.
        pogingen = 0
        while view.eigen_wins < 2 and view.tegenstander_wins < 2 and pogingen < 3:
            interactie_matchup = fake_interaction(SPELER_A)
            await view.gebalanceerd.callback(interactie_matchup)
            pogingen += 1
        print(f"gevecht afgerond na {pogingen} matchup(s): {view.eigen_wins}-{view.tegenstander_wins}")
        assert pogingen <= 3

        async with async_session() as session:
            speler_na = await session.get(Speler, SPELER_A)
            print(f"MMR na afloop: {speler_na.mmr} (was 1000), coins: {speler_na.currency}")

        print("Geen crashes tijdens PvE-gevecht met elementen + afbeeldingscode.")
    finally:
        async with async_session() as session:
            await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids)))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == SPELER_A))
            await session.commit()
        print("Testdata opgeruimd.")


async def main() -> None:
    test_modifier_logica()
    await test_pve_gevecht()
    print("\nAlle checks geslaagd.")


if __name__ == "__main__":
    asyncio.run(main())
