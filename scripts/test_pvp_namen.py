"""End-to-end check dat een volledig PvP-gevecht via /vecht nergens meer een
kale @-tag (<@id>) toont — noch in de embeds/logs rond de uitdaging, noch in
de per-matchup rondelogs of de eindafhandeling. Dit was stuk doordat
`_weergavenaam()` afhing van de (niet ingeschakelde) members-intent en dan
terugviel op een ruwe mention; de fix legt weergavenamen vooraf vast vanuit
verse discord.Member-objecten en geeft ze door als strings.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.gevechten import GevechtenCog
from db.engine import async_session
from db.models import Huisdier, PetSoort, PetStatus, Speler

SPELER_A = 999999999999999911
SPELER_B = 999999999999999912
RUWE_MENTION = re.compile(r"<@!?\d+>")

alle_teksten: list[str] = []


def _vang_tekst(*args, **kwargs) -> None:
    for waarde in (*args, *kwargs.values()):
        if isinstance(waarde, str):
            alle_teksten.append(waarde)
        elif hasattr(waarde, "description") and isinstance(getattr(waarde, "description", None), str):
            alle_teksten.append(waarde.description)
            if getattr(waarde, "title", None):
                alle_teksten.append(waarde.title)


def fake_member(user_id: int, naam: str) -> MagicMock:
    member = MagicMock()
    member.id = user_id
    member.display_name = naam
    member.mention = f"<@{user_id}>"  # blijft een echte ping voor content=..., niet voor leesbare tekst
    member.bot = False
    return member


def fake_interaction(user: MagicMock, guild_id: int | None = 1) -> MagicMock:
    interaction = MagicMock()
    interaction.user = user
    interaction.guild_id = guild_id
    interaction.response = AsyncMock(side_effect=lambda *a, **kw: _vang_tekst(*a, **kw))
    interaction.response.send_message = AsyncMock(side_effect=_vang_tekst)
    interaction.response.edit_message = AsyncMock(side_effect=_vang_tekst)
    interaction.response.defer = AsyncMock()
    bericht = MagicMock()
    bericht.edit = AsyncMock(side_effect=_vang_tekst)
    interaction.original_response = AsyncMock(return_value=bericht)
    kanaal = MagicMock()

    async def _send(*a, **kw):
        _vang_tekst(*a, **kw)
        return bericht

    kanaal.send = AsyncMock(side_effect=_send)
    interaction.channel = kanaal
    return interaction


async def _maak_team(session, speler_id: int, naam_prefix: str) -> list[int]:
    if await session.get(Speler, speler_id) is None:
        session.add(Speler(discord_id=speler_id, currency=100, mmr=1000, volgend_pet_nummer=1))
        await session.commit()
    soorten = (await session.execute(select(PetSoort).limit(3))).scalars().all()
    assert len(soorten) == 3
    speler = await session.get(Speler, speler_id)
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


async def main() -> None:
    cog = GevechtenCog(bot=MagicMock())
    pet_ids_a: list[int] = []
    pet_ids_b: list[int] = []

    try:
        async with async_session() as session:
            pet_ids_a = await _maak_team(session, SPELER_A, "PvpA")
            pet_ids_b = await _maak_team(session, SPELER_B, "PvpB")

        lid_a = fake_member(SPELER_A, "Chaos-Agent-A")
        lid_b = fake_member(SPELER_B, "Chaos-Agent-B")

        interactie_start = fake_interaction(lid_a)
        await cog.vecht.callback(cog, interactie_start, tegenstander=lid_b)
        inzet_view = interactie_start.response.send_message.call_args.kwargs["view"]

        interactie_uitdagen = fake_interaction(lid_a)
        await inzet_view._uitdagen(interactie_uitdagen)

        uitdaging_view = interactie_uitdagen.channel.send.call_args.kwargs.get("view")
        assert uitdaging_view is not None, "UitdagingView niet gevonden in channel.send-call"
        uitdaging_view.message = MagicMock()

        interactie_accept = fake_interaction(lid_b)
        await uitdaging_view.accepteren.callback(interactie_accept)

        vecht_view = interactie_accept.channel.send.call_args.kwargs.get("view")
        assert vecht_view is not None, "VechtView niet gevonden na accepteren"
        vecht_view.message = MagicMock()
        vecht_view.message.edit = AsyncMock(side_effect=_vang_tekst)

        pogingen = 0
        while vecht_view.eigen_wins < 2 and vecht_view.tegenstander_wins < 2 and pogingen < 3:
            interactie_a = fake_interaction(lid_a)
            await vecht_view.gebalanceerd.callback(interactie_a)
            if vecht_view.eigen_wins < 2 and vecht_view.tegenstander_wins < 2 and not vecht_view._afgerond:
                interactie_b = fake_interaction(lid_b)
                await vecht_view.gebalanceerd.callback(interactie_b)
            pogingen += 1
        await asyncio.sleep(2)

        print(f"Gevecht afgerond na {pogingen} matchup(s): {vecht_view.eigen_wins}-{vecht_view.tegenstander_wins}")
        print(f"Aantal opgevangen tekstfragmenten: {len(alle_teksten)}")

        # Een `content=`-ping die *uitsluitend* uit een kale mention bestaat is
        # bewust: dat is de daadwerkelijke @-notificatie aan de tegenstander,
        # geen leesbare tekst. Alleen mentions die tussen/naast andere tekst
        # staan (dus duidelijk bedoeld als leesbare naam) zijn een bug.
        rauwe_mentions = [
            t for t in alle_teksten if RUWE_MENTION.search(t) and not RUWE_MENTION.fullmatch(t.strip())
        ]
        if rauwe_mentions:
            print("GEVONDEN RUWE MENTIONS:")
            for t in rauwe_mentions:
                print(f"  - {t!r}")
        assert not rauwe_mentions, "Er staan nog kale @-tags in de gevangen teksten"

        for naam in ("Chaos-Agent-A", "Chaos-Agent-B"):
            assert any(naam in t for t in alle_teksten), f"Weergavenaam {naam!r} kwam nergens voor"
        print("Weergavenamen komen overal voor, geen enkele kale @-tag gevonden.")

    finally:
        async with async_session() as session:
            if pet_ids_a:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids_a)))
            if pet_ids_b:
                await session.execute(Huisdier.__table__.delete().where(Huisdier.id.in_(pet_ids_b)))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id.in_([SPELER_A, SPELER_B])))
            await session.commit()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
