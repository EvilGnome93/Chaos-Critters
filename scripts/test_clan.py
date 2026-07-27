"""Check van het clan-systeem (2026-07-27, verzoek van de gebruiker; heette
eerst "gilde", hernoemd naar "clan" om een naam-botsing met discord.py's
Guild-concept te voorkomen): aanmaken/joinen/verlaten/ontbinden, gedeelde
werkplek-capaciteit PER CLAN (los van andere clans en van clanloze
spelers), en het leaderboard op cumulatieve werk-opbrengst.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.clan import ClanCog
from cogs.werk import WerkCog, _nu
from db.engine import async_session
from db.models import Clan, Huisdier, InventarisItem, PetSoort, PetStatus, Speler

SPELERS = [999999999999999961, 999999999999999962, 999999999999999963, 999999999999999964]
CLAN_NAAM_A = "TestclanAlpha"
CLAN_NAAM_B = "TestclanBeta"


def fake_interaction(user_id: int, guild_id: int | None = 1) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.user.mention = f"<@{user_id}>"
    interaction.guild_id = guild_id
    interaction.response = AsyncMock()
    return interaction


def fake_choice(value: str) -> MagicMock:
    choice = MagicMock()
    choice.value = value
    return choice


async def _maak_pet(session, speler_id: int, naam: str) -> int:
    if await session.get(Speler, speler_id) is None:
        session.add(Speler(discord_id=speler_id, currency=0, mmr=1000, volgend_pet_nummer=1))
        await session.commit()
    speler = await session.get(Speler, speler_id)
    soort = await session.scalar(select(PetSoort).limit(1))
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


async def _cleanup() -> None:
    async with async_session() as session:
        await session.execute(Huisdier.__table__.delete().where(Huisdier.eigenaar_id.in_(SPELERS)))
        await session.execute(InventarisItem.__table__.delete().where(InventarisItem.speler_id.in_(SPELERS)))
        await session.execute(Speler.__table__.update().where(Speler.discord_id.in_(SPELERS)).values(clan_id=None))
        await session.commit()
        await session.execute(Clan.__table__.delete().where(Clan.naam.in_([CLAN_NAAM_A, CLAN_NAAM_B])))
        await session.execute(Speler.__table__.delete().where(Speler.discord_id.in_(SPELERS)))
        await session.commit()


async def test_aanmaken_joinen_dubbele_naam() -> None:
    print("-- Clan aanmaken, joinen, dubbele naam weigeren --")
    cog = ClanCog(bot=MagicMock())

    interactie1 = fake_interaction(SPELERS[0])
    await cog.clan_aanmaken.callback(cog, interactie1, naam=CLAN_NAAM_A)
    bericht1 = interactie1.response.send_message.call_args[0][0]
    print(f"Speler 0 richt clan op: {bericht1}")
    assert "opgericht" in bericht1

    interactie2 = fake_interaction(SPELERS[1])
    await cog.clan_aanmaken.callback(cog, interactie2, naam=CLAN_NAAM_A)
    bericht2 = interactie2.response.send_message.call_args[0][0]
    print(f"Speler 1 probeert zelfde naam: {bericht2}")
    assert "bestaat al" in bericht2

    interactie3 = fake_interaction(SPELERS[1])
    await cog.clan_join.callback(cog, interactie3, naam=CLAN_NAAM_A)
    bericht3 = interactie3.response.send_message.call_args[0][0]
    print(f"Speler 1 joint in plaats daarvan: {bericht3}")
    assert "lid" in bericht3

    async with async_session() as session:
        s0 = await session.get(Speler, SPELERS[0])
        s1 = await session.get(Speler, SPELERS[1])
        assert s0.clan_id is not None
        assert s0.clan_id == s1.clan_id
    print("Aanmaken/joinen/dubbele-naam-check werkt correct.")


async def test_gedeelde_capaciteit_per_clan() -> None:
    print("\n-- Gedeelde werkplek-capaciteit is PER CLAN, niet meer globaal --")
    werk_cog = WerkCog(bot=MagicMock())
    clan_cog = ClanCog(bot=MagicMock())

    async with async_session() as session:
        for speler_id in SPELERS:
            await _maak_pet(session, speler_id, f"Pet{speler_id}")

    # Speler 2 sticht een TWEEDE clan (B) — zonder dit zou speler 2 gewoon
    # clanloos zijn en niet aantonen dat clan A/B elk hun eigen pool hebben.
    interactie_b = fake_interaction(SPELERS[2])
    await clan_cog.clan_aanmaken.callback(clan_cog, interactie_b, naam=CLAN_NAAM_B)
    bericht_b = interactie_b.response.send_message.call_args[0][0]
    print(f"Speler 2 richt clan B op: {bericht_b}")
    assert "opgericht" in bericht_b

    # Speler 0 (clan A) zet Nachtwacht (capaciteit 1) vol binnen clan A.
    interactie0 = fake_interaction(SPELERS[0])
    await werk_cog.werk.callback(
        werk_cog, interactie0, pet_id=1, werkplek=fake_choice("Nachtwacht"), cyclus=fake_choice("korte")
    )
    bericht0 = interactie0.response.send_message.call_args[0][0]
    print(f"Speler 0 (clan A): {bericht0}")
    assert "aan het werk gezet" in bericht0

    # Speler 1 zit ook in clan A -> zelfde pool, moet geweigerd worden.
    interactie1 = fake_interaction(SPELERS[1])
    await werk_cog.werk.callback(
        werk_cog, interactie1, pet_id=1, werkplek=fake_choice("Nachtwacht"), cyclus=fake_choice("korte")
    )
    bericht1 = interactie1.response.send_message.call_args[0][0]
    print(f"Speler 1 (zelfde clan A): {bericht1}")
    assert "zit vol" in bericht1 and "binnen je clan" in bericht1

    # Speler 2 zit in clan B -> eigen pool, moet gewoon lukken.
    interactie2 = fake_interaction(SPELERS[2])
    await werk_cog.werk.callback(
        werk_cog, interactie2, pet_id=1, werkplek=fake_choice("Nachtwacht"), cyclus=fake_choice("korte")
    )
    bericht2 = interactie2.response.send_message.call_args[0][0]
    print(f"Speler 2 (andere clan B): {bericht2}")
    assert "aan het werk gezet" in bericht2

    # Speler 3 is clanloos -> weer een eigen pool, los van clan A/B. Dit is
    # de gedeelde live dev-DB, dus die clanloze pool kan in theorie al
    # bezet zijn door een echte tester — Werkbank (capaciteit 2) gebruiken
    # i.p.v. Nachtwacht (capaciteit 1) om die kans te verkleinen, en anders
    # de aanname expliciet overslaan i.p.v. een valse test-failure te geven.
    from cogs.werk import _aantal_werkend_op_werkplek
    from db.models import Werkplek as _Werkplek

    async with async_session() as session:
        werkbank = await session.scalar(select(_Werkplek).where(_Werkplek.type == "Werkbank"))
        bezet_vooraf = await _aantal_werkend_op_werkplek(session, werkbank.id, None)

    interactie3 = fake_interaction(SPELERS[3])
    await werk_cog.werk.callback(
        werk_cog, interactie3, pet_id=1, werkplek=fake_choice("Werkbank"), cyclus=fake_choice("korte")
    )
    bericht3 = interactie3.response.send_message.call_args[0][0]
    print(f"Speler 3 (clanloos, vooraf {bezet_vooraf}/{werkbank.capaciteit} bezet in die pool): {bericht3}")
    if bezet_vooraf < werkbank.capaciteit:
        assert "aan het werk gezet" in bericht3
    else:
        print("(clanloze pool was al vol door externe/live data, sla de succes-assertie over)")

    print("Capaciteit is correct geïsoleerd per clan (en clanloze pool).")


async def test_werk_opbrengst_en_leaderboard() -> None:
    print("\n-- Clan-werk-opbrengst optellen + leaderboard --")
    werk_cog = WerkCog(bot=MagicMock())
    clan_cog = ClanCog(bot=MagicMock())

    async with async_session() as session:
        s0 = await session.get(Speler, SPELERS[0])
        clan_a_id = s0.clan_id
        clan_voor = await session.get(Clan, clan_a_id)
        opbrengst_voor = clan_voor.totale_werk_opbrengst

        pet = await session.scalar(
            select(Huisdier).where(Huisdier.eigenaar_id == SPELERS[0], Huisdier.status == PetStatus.werkplek)
        )
        pet.werk_gestart_op = _nu() - timedelta(hours=999)
        await session.commit()

    interactie = fake_interaction(SPELERS[0])
    await werk_cog.werk.callback(werk_cog, interactie, pet_id=1)
    bericht = interactie.response.send_message.call_args[0][0]
    print(f"Opbrengst opgehaald: {bericht}")

    async with async_session() as session:
        clan_na = await session.get(Clan, clan_a_id)
        print(f"Clan-opbrengst: {opbrengst_voor} -> {clan_na.totale_werk_opbrengst} (verwacht hoger)")
        assert clan_na.totale_werk_opbrengst > opbrengst_voor

    interactie_lb = fake_interaction(SPELERS[0])
    await clan_cog.clan_leaderboard.callback(clan_cog, interactie_lb)
    embed = interactie_lb.response.send_message.call_args.kwargs["embed"]
    print(f"Leaderboard: {embed.description}")
    assert CLAN_NAAM_A in embed.description
    print("Werk-opbrengst wordt correct bijgehouden en verschijnt op het leaderboard.")


async def test_verlaten_en_ontbinden() -> None:
    print("\n-- Clan verlaten (auto-ontbinden bij leegloop) + expliciet ontbinden --")
    clan_cog = ClanCog(bot=MagicMock())

    # Speler 2 is de enige in clan B -> verlaten moet 'm automatisch ontbinden.
    interactie = fake_interaction(SPELERS[2])
    await clan_cog.clan_verlaten.callback(clan_cog, interactie)
    bericht = interactie.response.send_message.call_args[0][0]
    print(f"Speler 2 verlaat (enige lid van) clan B: {bericht}")
    assert "automatisch ontbonden" in bericht

    async with async_session() as session:
        clan_b = await session.scalar(select(Clan).where(Clan.naam == CLAN_NAAM_B))
        assert clan_b is None
    print("Auto-ontbinden bij leegloop werkt.")

    # Clan A heeft nog speler 0 (oprichter) en speler 1.
    interactie_niet_oprichter = fake_interaction(SPELERS[1])
    await clan_cog.clan_ontbinden.callback(clan_cog, interactie_niet_oprichter)
    bericht_niet_oprichter = interactie_niet_oprichter.response.send_message.call_args[0][0]
    print(f"Niet-oprichter probeert te ontbinden: {bericht_niet_oprichter}")
    assert "Alleen de oprichter" in bericht_niet_oprichter

    interactie_oprichter = fake_interaction(SPELERS[0])
    await clan_cog.clan_ontbinden.callback(clan_cog, interactie_oprichter)
    bericht_oprichter = interactie_oprichter.response.send_message.call_args[0][0]
    print(f"Oprichter ontbindt clan A: {bericht_oprichter}")
    assert "ontbonden" in bericht_oprichter

    async with async_session() as session:
        s0 = await session.get(Speler, SPELERS[0])
        s1 = await session.get(Speler, SPELERS[1])
        assert s0.clan_id is None
        assert s1.clan_id is None
    print("Ontbinden door de oprichter verwijdert de clan en alle leden komen weer clanloos.")


async def main() -> None:
    try:
        await test_aanmaken_joinen_dubbele_naam()
        await test_gedeelde_capaciteit_per_clan()
        await test_werk_opbrengst_en_leaderboard()
        await test_verlaten_en_ontbinden()
        print("\nAlle checks geslaagd.")
    finally:
        await _cleanup()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
