"""Check van /critter-stats (2026-07-30, verzoek van de gebruiker: een
persoonlijk statistieken-overzicht zoals Botv3's /mystats).

Test de nieuwe lifetime-tellers op Speler (shiften_voltooid, pvp/pve
gewonnen/verloren) en dat /critter-stats de juiste, actuele cijfers toont
(pets/critterdex-percentage worden live berekend, de tellers gelezen).

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from cogs.critterstats import CritterStatsCog
from db.engine import async_session
from db.models import Huisdier, PetSoort, Speler

SPELER = 999999999999999991
ANDERE_SPELER = 999999999999999992


def fake_interaction(user_id: int) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.user.bot = False
    interaction.user.display_name = "Statstester"
    interaction.user.display_avatar.url = "https://example.invalid/avatar.png"
    interaction.response = AsyncMock()
    return interaction


def fake_member(user_id: int, naam: str) -> MagicMock:
    member = MagicMock()
    member.id = user_id
    member.bot = False
    member.display_name = naam
    member.display_avatar.url = "https://example.invalid/avatar.png"
    return member


async def _opruimen() -> None:
    async with async_session() as session:
        await session.execute(Huisdier.__table__.delete().where(Huisdier.eigenaar_id.in_([SPELER, ANDERE_SPELER])))
        await session.execute(Speler.__table__.delete().where(Speler.discord_id.in_([SPELER, ANDERE_SPELER])))
        await session.commit()


async def _maak_pet(session, speler_id: int, soort: PetSoort) -> None:
    speler = await session.get(Speler, speler_id)
    session.add(
        Huisdier(
            volgnummer=speler.volgend_pet_nummer,
            eigenaar_id=speler_id,
            soort_id=soort.id,
            tier_id=soort.tier_id,
            naam=soort.naam,
            gevecht_genen=50,
            werk_genen=50,
        )
    )
    speler.volgend_pet_nummer += 1


async def test_geen_speler() -> None:
    print("-- /critter-stats voor iemand die nog nooit gespeeld heeft --")
    cog = CritterStatsCog(bot=MagicMock())
    interactie = fake_interaction(SPELER)
    await cog.critter_stats.callback(cog, interactie, speler=None)
    bericht = interactie.response.send_message.call_args[0][0]
    print(f"Bericht: {bericht}")
    assert "nog niet gespeeld" in bericht
    print("Nette melding i.p.v. een crash.")


async def test_stats_kloppen() -> None:
    print("\n-- /critter-stats toont de juiste cijfers --")
    cog = CritterStatsCog(bot=MagicMock())

    async with async_session() as session:
        session.add(
            Speler(
                discord_id=SPELER,
                currency=750,
                mmr=1080,
                volgend_pet_nummer=1,
                shiften_voltooid=12,
                pvp_gewonnen=5,
                pvp_verloren=2,
                pve_gewonnen=8,
                pve_verloren=3,
            )
        )
        await session.commit()

        soorten = (await session.execute(select(PetSoort).limit(2))).scalars().all()
        await _maak_pet(session, SPELER, soorten[0])
        await _maak_pet(session, SPELER, soorten[0])  # zelfde soort nogmaals
        await _maak_pet(session, SPELER, soorten[1])
        await session.commit()

        totaal_soorten = await session.scalar(select(func.count()).select_from(PetSoort))

    interactie = fake_interaction(SPELER)
    await cog.critter_stats.callback(cog, interactie, speler=None)
    embed = interactie.response.send_message.call_args.kwargs["embed"]
    velden = {f.name: f.value for f in embed.fields}
    print(f"Velden: {velden}")

    assert "3" in velden["🐾 Pets"] and "3" in velden["🐾 Pets"]  # 3 huidig, 3 ooit (nog niets geruild/geleased)
    verwacht_pct = round(2 / totaal_soorten * 100, 1)  # 2 unieke soorten (soort[0] dubbel telt als 1)
    assert f"{verwacht_pct}%" in velden["📖 Critterdex"], velden["📖 Critterdex"]
    assert "2/" in velden["📖 Critterdex"]
    assert "12" in velden["👷 Werken"]
    assert "5" in velden["⚔️ PvP (ranked)"] and "2" in velden["⚔️ PvP (ranked)"] and "1080" in velden["⚔️ PvP (ranked)"]
    assert "8" in velden["🐺 PvE"] and "3" in velden["🐺 PvE"]
    assert "750" in velden["💰 Chaos Coins"]
    print("Alle velden tonen de juiste, actuele cijfers.")


async def test_andere_speler_en_bot() -> None:
    print("\n-- /critter-stats speler:<iemand anders>, en een bot geweigerd --")
    cog = CritterStatsCog(bot=MagicMock())

    async with async_session() as session:
        session.add(Speler(discord_id=ANDERE_SPELER, currency=100, mmr=1000, volgend_pet_nummer=1))
        await session.commit()

    interactie = fake_interaction(SPELER)
    doel = fake_member(ANDERE_SPELER, "Ander Lid")
    await cog.critter_stats.callback(cog, interactie, speler=doel)
    embed = interactie.response.send_message.call_args.kwargs["embed"]
    assert "Ander Lid" in embed.title
    print(f"Titel: {embed.title}")

    interactie_bot = fake_interaction(SPELER)
    bot_doel = fake_member(999999999999999993, "EenBot")
    bot_doel.bot = True
    await cog.critter_stats.callback(cog, interactie_bot, speler=bot_doel)
    bericht = interactie_bot.response.send_message.call_args[0][0]
    assert "Bots" in bericht
    print("Bot-doelwit netjes geweigerd.")


async def main() -> None:
    try:
        await _opruimen()
        await test_geen_speler()
        await test_stats_kloppen()
        await test_andere_speler_en_bot()
        print("\nAlle checks geslaagd.")
    finally:
        await _opruimen()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
