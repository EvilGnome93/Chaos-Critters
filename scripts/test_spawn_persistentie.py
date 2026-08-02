"""Check dat een actieve spawn een bot-herstart overleeft (2026-07-30,
verzoek van de gebruiker: "zorgen dat /vang door kan gaan na een restart").

De actieve spawn per kanaal stond alleen in het geheugen
(VangenCog.actieve_spawns), dus een redeploy maakte 'm onvangbaar: de embed
bleef in Discord staan maar /vang antwoordde "geen spawn actief". Nu
spiegelt de actieve_spawns-tabel die staat.

Een "herstart" wordt hier nagebootst door een tweede VangenCog-instantie te
maken en cog_load() te draaien — dat is precies wat er bij een deploy
gebeurt: nieuw proces, lege dicts, alleen de database blijft.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select

from cogs.vangen import VangenCog
from db.engine import async_session
from db.models import ActieveSpawn, Huisdier, PetSoort, Speler, Tier

SPELER = 999999999999999911
KANAAL = 888888888888888801
GUILD = 888888888888888800
BERICHT = 777777777777777701


def nep_bot(kanaal: MagicMock) -> MagicMock:
    bot = MagicMock()
    bot.get_channel = lambda cid: kanaal if cid == kanaal.id else None
    return bot


def nep_kanaal() -> MagicMock:
    """Kanaal dat een verstuurd bericht teruggeeft met een vast ID, en
    get_partial_message ondersteunt (dat is wat de cog gebruikt om een
    bestaande embed bij te werken zonder 'm eerst op te halen)."""
    kanaal = MagicMock()
    kanaal.id = KANAAL
    kanaal.guild = MagicMock()
    kanaal.guild.id = GUILD

    verstuurd = MagicMock()
    verstuurd.id = BERICHT
    kanaal.send = AsyncMock(return_value=verstuurd)

    partial = MagicMock()
    partial.edit = AsyncMock()
    kanaal.get_partial_message = MagicMock(return_value=partial)
    kanaal._partial = partial
    return kanaal


def fake_interaction(user_id: int, channel_id: int) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.user.mention = f"<@{user_id}>"
    interaction.channel_id = channel_id
    interaction.guild_id = GUILD
    interaction.response = AsyncMock()
    interaction.delete_original_response = AsyncMock()
    return interaction


async def _opruimen() -> None:
    async with async_session() as session:
        await session.execute(delete(ActieveSpawn).where(ActieveSpawn.channel_id == KANAAL))
        await session.execute(delete(Huisdier).where(Huisdier.eigenaar_id == SPELER))
        await session.execute(delete(Speler).where(Speler.discord_id == SPELER))
        await session.commit()


async def test_spawn_overleeft_herstart() -> None:
    print("-- Spawn blijft vangbaar na een herstart --")
    kanaal = nep_kanaal()
    cog = VangenCog(bot=nep_bot(kanaal))

    async with async_session() as session:
        soort = await session.scalar(select(PetSoort).limit(1))
        tier = await session.get(Tier, soort.tier_id)
        session.expunge_all()

    await cog._stuur_spawn_embed(kanaal, soort, tier)
    print(f"Spawn gestuurd: {soort.naam} (bericht {BERICHT})")
    assert cog.actieve_spawns[KANAAL] == (soort, BERICHT)

    async with async_session() as session:
        rij = await session.get(ActieveSpawn, KANAAL)
        assert rij is not None, "spawn is niet in de database gezet"
        print(f"In database: soort_id={rij.soort_id}, message_id={rij.message_id}, guild_id={rij.guild_id}")
        assert rij.soort_id == soort.id and rij.message_id == BERICHT and rij.guild_id == GUILD

    # De herstart: nieuw proces = nieuwe cog met lege dicts.
    nieuwe_cog = VangenCog(bot=nep_bot(kanaal))
    assert nieuwe_cog.actieve_spawns == {}, "verse cog hoort leeg te beginnen"
    await nieuwe_cog.cog_load()
    for taak in nieuwe_cog.tijd_taken.values():
        taak.cancel()

    hersteld = nieuwe_cog.actieve_spawns.get(KANAAL)
    assert hersteld is not None, "spawn is NIET hersteld na de herstart"
    herstelde_soort, herstelde_message_id = hersteld
    print(f"Na herstart hersteld: {herstelde_soort.naam} (bericht {herstelde_message_id})")
    assert herstelde_soort.id == soort.id and herstelde_message_id == BERICHT
    print("De spawn is na een herstart nog steeds bekend bij de bot.")


async def test_vangen_na_herstart_werkt_en_ruimt_op() -> None:
    print("\n-- /vang werkt na de herstart, en wist de databaserij --")
    kanaal = nep_kanaal()
    cog = VangenCog(bot=nep_bot(kanaal))
    await cog.cog_load()
    for taak in cog.tijd_taken.values():
        taak.cancel()

    soort, _ = cog.actieve_spawns[KANAAL]

    interactie = fake_interaction(SPELER, KANAAL)
    await cog.vang.callback(cog, interactie, naam=soort.naam)

    # De embed van het oude bericht is bijgewerkt via een PartialMessage —
    # precies het pad dat na een herstart als enige beschikbaar is.
    kanaal.get_partial_message.assert_called_with(BERICHT)
    kanaal._partial.edit.assert_awaited()
    embed = kanaal._partial.edit.call_args.kwargs["embed"]
    print(f"Embed bijgewerkt naar: {embed.title}")
    assert "gevangen" in embed.title.lower()

    async with async_session() as session:
        pet = await session.scalar(select(Huisdier).where(Huisdier.eigenaar_id == SPELER))
        assert pet is not None, "pet is niet aangemaakt"
        print(f"Pet aangemaakt: {pet.naam} (#{pet.volgnummer})")
        rij = await session.get(ActieveSpawn, KANAAL)
        assert rij is None, "databaserij had gewist moeten zijn na de vangst"
    assert KANAAL not in cog.actieve_spawns
    print("Vangst gelukt en de spawn is overal opgeruimd.")


async def test_nieuwe_spawn_vervangt_de_oude() -> None:
    print("\n-- Een nieuwe spawn vervangt de oude (ook in de database) --")
    kanaal = nep_kanaal()
    cog = VangenCog(bot=nep_bot(kanaal))

    async with async_session() as session:
        soorten = (await session.execute(select(PetSoort).limit(2))).scalars().all()
        tiers = {s.id: await session.get(Tier, s.tier_id) for s in soorten}
        session.expunge_all()

    await cog._stuur_spawn_embed(kanaal, soorten[0], tiers[soorten[0].id])
    tweede_bericht = MagicMock()
    tweede_bericht.id = BERICHT + 1
    kanaal.send = AsyncMock(return_value=tweede_bericht)
    await cog._stuur_spawn_embed(kanaal, soorten[1], tiers[soorten[1].id])

    # De oude embed is als "ontsnapt" gemarkeerd.
    embed = kanaal._partial.edit.call_args.kwargs["embed"]
    print(f"Oude spawn gemarkeerd als: {embed.title}")
    assert "ontsnapt" in embed.title.lower()

    async with async_session() as session:
        rij = await session.get(ActieveSpawn, KANAAL)
        print(f"Database wijst nu naar bericht {rij.message_id} (soort_id {rij.soort_id})")
        assert rij.message_id == BERICHT + 1 and rij.soort_id == soorten[1].id
    print("Eén rij per kanaal: de nieuwe spawn heeft de oude netjes vervangen.")


async def main() -> None:
    try:
        await _opruimen()
        await test_spawn_overleeft_herstart()
        await test_vangen_na_herstart_werkt_en_ruimt_op()
        await test_nieuwe_spawn_vervangt_de_oude()
        print("\nAlle checks geslaagd.")
    finally:
        await _opruimen()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
