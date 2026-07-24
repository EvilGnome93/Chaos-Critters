"""Handmatige check van de trading-flow (paneel samenstellen -> voorstel ->
accepteren -> definitief bevestigen) en de release-flow, met gesimuleerde
Discord-interacties, zonder de bot te starten. Ruimt zijn eigen testdata
op aan het eind.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from cogs.release import ReleaseCog, _release_beloning
from cogs.trading import AantalCoinsModal, TradingCog
from cogs.werk import _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, PetSoort, PetStatus, Speler, Tier

SPELER_A = 999999999999999901
SPELER_B = 999999999999999902


def fake_interaction(user_id: int, guild_id: int | None = None) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.guild_id = guild_id
    interaction.response = AsyncMock()
    bericht = MagicMock()
    bericht.edit = AsyncMock()
    interaction.original_response = AsyncMock(return_value=bericht)
    interaction.channel = MagicMock()
    interaction.channel.send = AsyncMock(return_value=MagicMock())
    return interaction


def fake_member(user_id: int) -> MagicMock:
    member = MagicMock()
    member.id = user_id
    member.bot = False
    member.mention = f"<@{user_id}>"
    return member


async def stel_voor_via_paneel(
    cog: TradingCog, van_id: int, naar_id: int,
    geef_waarde: str | None, geef_aantal: int, geef_coins: int,
    vraag_waarde: str | None, vraag_aantal: int, vraag_coins: int,
):
    """Simuleert het hele /trade-paneel: command -> dropdowns kiezen ->
    aantal/coins via modal -> versturen. Geeft de verstuurde
    TradeVoorstelView terug."""
    open_interactie = fake_interaction(van_id)
    await cog.trade.callback(cog, open_interactie, fake_member(naar_id))
    view = open_interactie.response.send_message.call_args.kwargs["view"]

    if geef_waarde is not None:
        view.geef_select._values = [geef_waarde]
        await view._on_geef_select(fake_interaction(van_id))
    if vraag_waarde is not None:
        view.vraag_select._values = [vraag_waarde]
        await view._on_vraag_select(fake_interaction(van_id))

    modal_geef = AantalCoinsModal(view, "geef")
    modal_geef.aantal_input._value = str(geef_aantal)
    modal_geef.coins_input._value = str(geef_coins)
    await modal_geef.on_submit(fake_interaction(van_id))

    modal_vraag = AantalCoinsModal(view, "vraag")
    modal_vraag.aantal_input._value = str(vraag_aantal)
    modal_vraag.coins_input._value = str(vraag_coins)
    await modal_vraag.on_submit(fake_interaction(van_id))

    verstuur_interactie = fake_interaction(van_id)
    await view._versturen(verstuur_interactie)
    return verstuur_interactie.channel.send.call_args.kwargs["view"]


async def main() -> None:
    cog = TradingCog(bot=MagicMock())

    async with async_session() as session:
        for speler_id in (SPELER_A, SPELER_B):
            if await session.get(Speler, speler_id) is None:
                session.add(Speler(discord_id=speler_id, currency=100, volgend_pet_nummer=1))
        await session.commit()

        item = await session.scalar(select(Item).where(Item.naam == "Basis brokjes"))
        await _voeg_toe_aan_inventaris(session, SPELER_A, item.id, 5)

        soort = await session.scalar(select(PetSoort).limit(1))
        pet_b = Huisdier(
            eigenaar_id=SPELER_B, soort_id=soort.id, tier_id=soort.tier_id, naam="Ruiltest",
            volgnummer=1, gevecht_genen=10, werk_genen=10, status=PetStatus.rust,
        )
        session.add(pet_b)
        await session.commit()
        await session.refresh(pet_b)
        pet_b_volgnummer = pet_b.volgnummer

    try:
        # -- Test 1: paneel, item-voor-coins ruil, volledig geaccepteerd --
        print("-- Test 1: item-voor-coins via paneel --")
        voorstel_view = await stel_voor_via_paneel(
            cog, SPELER_A, SPELER_B,
            geef_waarde="item::Basis brokjes", geef_aantal=3, geef_coins=0,
            vraag_waarde=None, vraag_aantal=1, vraag_coins=20,
        )
        assert voorstel_view.geef == ("Basis brokjes", 3, None, 0, None)
        assert voorstel_view.vraag == (None, 1, None, 20, None)

        interaction2 = fake_interaction(SPELER_B)
        await voorstel_view.accepteren.callback(interaction2)
        interaction2.response.edit_message.assert_awaited()
        bevestig_view = interaction2.response.edit_message.call_args.kwargs["view"]

        interaction3 = fake_interaction(SPELER_A)
        await bevestig_view.bevestigen.callback(interaction3)

        async with async_session() as session:
            speler_a = await session.get(Speler, SPELER_A)
            speler_b = await session.get(Speler, SPELER_B)
            inv_a = await session.scalar(
                select(InventarisItem).where(InventarisItem.speler_id == SPELER_A, InventarisItem.item_id == item.id)
            )
            inv_b = await session.scalar(
                select(InventarisItem).where(InventarisItem.speler_id == SPELER_B, InventarisItem.item_id == item.id)
            )
            print(f"A: coins={speler_a.currency} (verwacht 120), brokjes over={inv_a.aantal} (verwacht 2)")
            print(f"B: coins={speler_b.currency} (verwacht 80), brokjes ontvangen={inv_b.aantal} (verwacht 3)")
            assert speler_a.currency == 120
            assert inv_a.aantal == 2
            assert speler_b.currency == 80
            assert inv_b.aantal == 3

        # -- Test 2: paneel, pet-voor-coins ruil (pet van B naar A) --
        print("\n-- Test 2: pet-voor-coins via paneel --")
        voorstel_view2 = await stel_voor_via_paneel(
            cog, SPELER_B, SPELER_A,
            geef_waarde=f"pet::{pet_b_volgnummer}", geef_aantal=1, geef_coins=0,
            vraag_waarde=None, vraag_aantal=1, vraag_coins=15,
        )
        assert voorstel_view2.geef == (None, 1, pet_b_volgnummer, 0, "Ruiltest")

        interaction5 = fake_interaction(SPELER_A)
        await voorstel_view2.accepteren.callback(interaction5)
        bevestig_view2 = interaction5.response.edit_message.call_args.kwargs["view"]

        interaction6 = fake_interaction(SPELER_B)
        await bevestig_view2.bevestigen.callback(interaction6)

        async with async_session() as session:
            verplaatste_pet = await session.get(Huisdier, pet_b.id)
            speler_a = await session.get(Speler, SPELER_A)
            speler_b = await session.get(Speler, SPELER_B)
            print(f"pet eigenaar: {verplaatste_pet.eigenaar_id} (verwacht {SPELER_A}), nieuw volgnummer: {verplaatste_pet.volgnummer} (verwacht 1, A's eerste pet)")
            print(f"A coins={speler_a.currency} (verwacht 105), B coins={speler_b.currency} (verwacht 95)")
            assert verplaatste_pet.eigenaar_id == SPELER_A
            assert verplaatste_pet.status == PetStatus.rust
            assert speler_a.currency == 105
            assert speler_b.currency == 95

        # -- Test 2b: pet-voor-pet ruil moet een samengestelde afbeelding meesturen --
        print("\n-- Test 2b: pet-voor-pet met ruil-afbeelding --")
        async with async_session() as session:
            soort_met_afbeelding = await session.scalar(
                select(PetSoort).where(PetSoort.afbeelding_url.isnot(None)).limit(1)
            )
            speler_a_ref = await session.get(Speler, SPELER_A)
            speler_b_ref = await session.get(Speler, SPELER_B)
            pet_a2 = Huisdier(
                eigenaar_id=SPELER_A, soort_id=soort_met_afbeelding.id, tier_id=soort_met_afbeelding.tier_id,
                naam="RuilAfbeeldingA", volgnummer=speler_a_ref.volgend_pet_nummer,
                gevecht_genen=10, werk_genen=10, status=PetStatus.rust,
            )
            speler_a_ref.volgend_pet_nummer += 1
            pet_b2 = Huisdier(
                eigenaar_id=SPELER_B, soort_id=soort_met_afbeelding.id, tier_id=soort_met_afbeelding.tier_id,
                naam="RuilAfbeeldingB", volgnummer=speler_b_ref.volgend_pet_nummer,
                gevecht_genen=10, werk_genen=10, status=PetStatus.rust,
            )
            speler_b_ref.volgend_pet_nummer += 1
            session.add_all([pet_a2, pet_b2])
            await session.commit()
            await session.refresh(pet_a2)
            await session.refresh(pet_b2)
            pet_a2_volgnummer = pet_a2.volgnummer
            pet_b2_volgnummer = pet_b2.volgnummer

        open_interactie = fake_interaction(SPELER_A)
        await cog.trade.callback(cog, open_interactie, fake_member(SPELER_B))
        builder_view = open_interactie.response.send_message.call_args.kwargs["view"]
        builder_view.geef_select._values = [f"pet::{pet_a2_volgnummer}"]
        await builder_view._on_geef_select(fake_interaction(SPELER_A))
        builder_view.vraag_select._values = [f"pet::{pet_b2_volgnummer}"]
        await builder_view._on_vraag_select(fake_interaction(SPELER_A))
        verstuur_interactie = fake_interaction(SPELER_A)
        await builder_view._versturen(verstuur_interactie)
        stuur_kwargs = verstuur_interactie.channel.send.call_args.kwargs
        print(f"file meegestuurd: {'file' in stuur_kwargs}")
        assert "file" in stuur_kwargs

        # -- Test 3: weigeren --
        print("\n-- Test 3: weigeren --")
        voorstel_view3 = await stel_voor_via_paneel(
            cog, SPELER_A, SPELER_B,
            geef_waarde=None, geef_aantal=1, geef_coins=10,
            vraag_waarde=None, vraag_aantal=1, vraag_coins=10,
        )
        interaction8 = fake_interaction(SPELER_B)
        await voorstel_view3.weigeren.callback(interaction8)
        interaction8.response.edit_message.assert_awaited_with(content="❌ Ruilvoorstel geweigerd.", embed=None, view=voorstel_view3)
        print("Weigeren werkt.")

        # -- Test 4: accepteren zonder voldoende coins moet falen --
        print("\n-- Test 4: accepteren met te weinig coins --")
        voorstel_view4 = await stel_voor_via_paneel(
            cog, SPELER_A, SPELER_B,
            geef_waarde=None, geef_aantal=1, geef_coins=1,
            vraag_waarde=None, vraag_aantal=1, vraag_coins=99999,
        )
        interaction10 = fake_interaction(SPELER_B)
        await voorstel_view4.accepteren.callback(interaction10)
        content = interaction10.response.edit_message.call_args.kwargs["content"]
        print(content)
        assert "niet (meer) genoeg" in content or "Chaos Coins" in content

        # -- Test 5: release bevestigen, coins + pet weg --
        print("\n-- Test 5: release bevestigen --")
        release_cog = ReleaseCog(bot=MagicMock())
        async with async_session() as session:
            speler_a_voor = await session.get(Speler, SPELER_A)
            coins_voor = speler_a_voor.currency
            soort = await session.scalar(select(PetSoort).limit(1))
            tier = await session.get(Tier, soort.tier_id)
            releasetest_pet = Huisdier(
                eigenaar_id=SPELER_A, soort_id=soort.id, tier_id=soort.tier_id, naam="Vrijlaattest",
                volgnummer=speler_a_voor.volgend_pet_nummer, gevecht_genen=10, werk_genen=10,
                status=PetStatus.rust, level=3,
            )
            speler_a_voor.volgend_pet_nummer += 1
            session.add(releasetest_pet)
            await session.commit()
            await session.refresh(releasetest_pet)
            release_pet_id = releasetest_pet.volgnummer
            verwachte_coins = _release_beloning(tier, releasetest_pet.level)

        interaction11 = fake_interaction(SPELER_A)
        await release_cog.release.callback(release_cog, interaction11, release_pet_id)
        release_view = interaction11.response.send_message.call_args.kwargs["view"]

        interaction12 = fake_interaction(SPELER_A)
        await release_view.bevestigen.callback(interaction12)

        async with async_session() as session:
            weg = await session.get(Huisdier, releasetest_pet.id)
            speler_a_na = await session.get(Speler, SPELER_A)
            print(f"pet weg: {weg is None} (verwacht True), coins {coins_voor} -> {speler_a_na.currency} (verwacht +{verwachte_coins})")
            assert weg is None
            assert speler_a_na.currency == coins_voor + verwachte_coins

        # -- Test 6: release van een werkende pet moet geweigerd worden --
        print("\n-- Test 6: release van werkende pet --")
        async with async_session() as session:
            werkende_pet = Huisdier(
                eigenaar_id=SPELER_A, soort_id=soort.id, tier_id=soort.tier_id, naam="Werktest",
                volgnummer=(await session.get(Speler, SPELER_A)).volgend_pet_nummer,
                gevecht_genen=10, werk_genen=10, status=PetStatus.werkplek,
            )
            (await session.get(Speler, SPELER_A)).volgend_pet_nummer += 1
            session.add(werkende_pet)
            await session.commit()
            werkende_pet_id = werkende_pet.volgnummer

        interaction13 = fake_interaction(SPELER_A)
        await release_cog.release.callback(release_cog, interaction13, werkende_pet_id)
        print(interaction13.response.send_message.call_args)
        interaction13.response.send_message.assert_awaited_once()
        assert "aan het werk" in str(interaction13.response.send_message.call_args)

        print("\nAlle checks geslaagd.")
    finally:
        async with async_session() as session:
            await session.execute(InventarisItem.__table__.delete().where(InventarisItem.speler_id.in_([SPELER_A, SPELER_B])))
            await session.execute(Huisdier.__table__.delete().where(Huisdier.eigenaar_id.in_([SPELER_A, SPELER_B])))
            await session.execute(Speler.__table__.delete().where(Speler.discord_id.in_([SPELER_A, SPELER_B])))
            await session.commit()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
