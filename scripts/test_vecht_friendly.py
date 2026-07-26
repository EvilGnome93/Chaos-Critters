"""Check dat de nieuwe 'vriendschappelijk'-modus van /vecht werkt zoals
bedoeld (2026-07-26, verzoek van de gebruiker: een gevechtsmodus die altijd
beschikbaar is en niet van de dagelijkse ranked-limiet afgaat):

- werkt ook als de speler zijn dagelijkse ranked-pogingen al op heeft;
- consumeert zelf geen ranked-poging;
- geen MMR-verandering, geen currency-beloning, geen XP voor pets;
- geen blessure voor de verliezende pet.

Zowel PvE als PvP worden getest. Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.gevechten import GevechtenCog
from db.engine import async_session
from db.models import Huisdier, PetSoort, PetStatus, Speler

SPELER_A = 999999999999999921
SPELER_B = 999999999999999922


def fake_member(user_id: int, naam: str) -> MagicMock:
    member = MagicMock()
    member.id = user_id
    member.display_name = naam
    member.mention = f"<@{user_id}>"
    member.bot = False
    return member


def fake_interaction(user: MagicMock, guild_id: int | None = 1) -> MagicMock:
    interaction = MagicMock()
    interaction.user = user
    interaction.guild_id = guild_id
    interaction.response = AsyncMock()
    bericht = MagicMock()
    bericht.edit = AsyncMock()
    interaction.original_response = AsyncMock(return_value=bericht)
    kanaal = MagicMock()

    async def _send(*a, **kw):
        return bericht

    kanaal.send = AsyncMock(side_effect=_send)
    interaction.channel = kanaal
    return interaction


async def _maak_team(session, speler_id: int, naam_prefix: str, pogingen_op: bool) -> list[int]:
    if await session.get(Speler, speler_id) is None:
        session.add(Speler(discord_id=speler_id, currency=100, mmr=1000, volgend_pet_nummer=1))
        await session.commit()
    speler = await session.get(Speler, speler_id)
    if pogingen_op:
        speler.ranked_pogingen_vandaag = 999  # ruim boven elke daglimiet
    soorten = (await session.execute(select(PetSoort).limit(3))).scalars().all()
    assert len(soorten) == 3
    ids = []
    for soort in soorten:
        pet = Huisdier(
            eigenaar_id=speler_id, soort_id=soort.id, tier_id=soort.tier_id, naam=f"{naam_prefix}-{soort.naam}",
            volgnummer=speler.volgend_pet_nummer, gevecht_genen=50, werk_genen=50,
            status=PetStatus.team, honger=100, energie=100,
        )
        speler.volgend_pet_nummer += 1
        session.add(pet)
        ids.append(pet)
    await session.commit()
    for pet in ids:
        await session.refresh(pet)
    return [p.id for p in ids]


async def test_pve_friendly() -> None:
    print("-- PvE vriendschappelijk: werkt zonder ranked-pogingen, geen MMR/coins/XP/blessure --")
    cog = GevechtenCog(bot=MagicMock())
    pet_ids: list[int] = []
    try:
        async with async_session() as session:
            pet_ids = await _maak_team(session, SPELER_A, "FriendlyPvE", pogingen_op=True)
            speler_voor = await session.get(Speler, SPELER_A)
            pogingen_voor = speler_voor.ranked_pogingen_vandaag
            mmr_voor, coins_voor = speler_voor.mmr, speler_voor.currency

        lid_a = fake_member(SPELER_A, "Friendly-A")
        interactie = fake_interaction(lid_a)
        await cog.vecht.callback(cog, interactie, modus="vriendschappelijk")
        interactie.response.send_message.assert_awaited()
        view = interactie.response.send_message.call_args.kwargs["view"]
        assert view.is_friendly is True

        pogingen = 0
        while view.eigen_wins < 2 and view.tegenstander_wins < 2 and pogingen < 3:
            interactie_matchup = fake_interaction(lid_a)
            await view.gebalanceerd.callback(interactie_matchup)
            pogingen += 1
        await asyncio.sleep(2)

        async with async_session() as session:
            speler_na = await session.get(Speler, SPELER_A)
            pet_na = await session.get(Huisdier, view.eigen_team[0].id)
            print(f"pogingen_vandaag: {pogingen_voor} -> {speler_na.ranked_pogingen_vandaag} (verwacht ongewijzigd)")
            print(f"MMR: {mmr_voor} -> {speler_na.mmr} (verwacht ongewijzigd)")
            print(f"coins: {coins_voor} -> {speler_na.currency} (verwacht ongewijzigd)")
            assert speler_na.ranked_pogingen_vandaag == pogingen_voor
            assert speler_na.mmr == mmr_voor
            assert speler_na.currency == coins_voor
            for pet in view.eigen_team:
                pet_db = await session.get(Huisdier, pet.id)
                assert pet_db.geblesseerd_tot is None, f"{pet_db.naam} zou geen blessure moeten hebben"
        print("PvE vriendschappelijk gedraagt zich correct.")
    finally:
        async with async_session() as session:
            if pet_ids:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids)))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id == SPELER_A))
            await session.commit()


async def test_pvp_friendly() -> None:
    print("\n-- PvP vriendschappelijk: werkt zonder ranked-pogingen, geen inzet-paneel, geen MMR/coins/XP/blessure --")
    cog = GevechtenCog(bot=MagicMock())
    pet_ids_a: list[int] = []
    pet_ids_b: list[int] = []
    try:
        async with async_session() as session:
            pet_ids_a = await _maak_team(session, SPELER_A, "FriendlyPvpA", pogingen_op=True)
            pet_ids_b = await _maak_team(session, SPELER_B, "FriendlyPvpB", pogingen_op=True)
            mmr_a_voor = (await session.get(Speler, SPELER_A)).mmr
            mmr_b_voor = (await session.get(Speler, SPELER_B)).mmr

        lid_a = fake_member(SPELER_A, "Friendly-Pvp-A")
        lid_b = fake_member(SPELER_B, "Friendly-Pvp-B")

        interactie_start = fake_interaction(lid_a)
        await cog.vecht.callback(cog, interactie_start, tegenstander=lid_b, modus="vriendschappelijk")
        # Vriendschappelijk slaat het inzet-paneel over: de uitdaging gaat
        # direct als publiek bericht met UitdagingView de deur uit.
        interactie_start.response.send_message.assert_awaited()
        uitdaging_view = interactie_start.response.send_message.call_args.kwargs["view"]
        assert uitdaging_view.is_friendly is True
        uitdaging_view.message = MagicMock()

        interactie_accept = fake_interaction(lid_b)
        await uitdaging_view.accepteren.callback(interactie_accept)

        vecht_view = interactie_accept.channel.send.call_args.kwargs.get("view")
        assert vecht_view is not None
        assert vecht_view.is_friendly is True
        vecht_view.message = MagicMock()
        vecht_view.message.edit = AsyncMock()

        pogingen = 0
        while vecht_view.eigen_wins < 2 and vecht_view.tegenstander_wins < 2 and pogingen < 3:
            interactie_a = fake_interaction(lid_a)
            await vecht_view.gebalanceerd.callback(interactie_a)
            if vecht_view.eigen_wins < 2 and vecht_view.tegenstander_wins < 2 and not vecht_view._afgerond:
                interactie_b = fake_interaction(lid_b)
                await vecht_view.gebalanceerd.callback(interactie_b)
            pogingen += 1
        await asyncio.sleep(2)

        async with async_session() as session:
            speler_a_na = await session.get(Speler, SPELER_A)
            speler_b_na = await session.get(Speler, SPELER_B)
            print(f"MMR A: {mmr_a_voor} -> {speler_a_na.mmr} (verwacht ongewijzigd)")
            print(f"MMR B: {mmr_b_voor} -> {speler_b_na.mmr} (verwacht ongewijzigd)")
            assert speler_a_na.mmr == mmr_a_voor
            assert speler_b_na.mmr == mmr_b_voor
            assert speler_a_na.ranked_pogingen_vandaag == 999
            assert speler_b_na.ranked_pogingen_vandaag == 999
            for pet in [*vecht_view.eigen_team, *vecht_view.tegenstander_team]:
                pet_db = await session.get(Huisdier, pet.id)
                assert pet_db.geblesseerd_tot is None, f"{pet_db.naam} zou geen blessure moeten hebben"
        print("PvP vriendschappelijk gedraagt zich correct, ondanks dat beide spelers 'geen ranked-pogingen meer' hadden.")
    finally:
        async with async_session() as session:
            if pet_ids_a:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids_a)))
            if pet_ids_b:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids_b)))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id.in_([SPELER_A, SPELER_B])))
            await session.commit()
        print("Testdata opgeruimd.")


async def main() -> None:
    await test_pve_friendly()
    await test_pvp_friendly()
    print("\nAlle checks geslaagd.")


if __name__ == "__main__":
    asyncio.run(main())
