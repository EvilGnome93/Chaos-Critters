"""Check van de dagelijkse opdrachten (2026-08-05, verzoek van de gebruiker).

Wat hier bewaakt wordt:
1. Een speler krijgt precies drie opdrachten per dag, en dezelfde dag
   opnieuw ophalen geeft dezelfde drie (geen herrolling per aanroep).
2. Voortgang loopt op tot het doel en blijft daar staan; de beloning wordt
   precies één keer uitbetaald.
3. De "alle drie af"-bonus komt exact één keer, bij de laatste opdracht.
4. Een nieuwe opdracht-dag geeft nieuwe opdrachten, met de oude nog intact.
5. De dag draait om het ingestelde resetuur, niet om middernacht.
6. Een onbekende sleutel is een harde fout, geen stille no-op.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select

from db.engine import async_session
from db.models import SpelerOpdracht, Speler
from utils import balans, opdrachten

SPELER = 999999999999999955


async def _opruimen() -> None:
    async with async_session() as session:
        await session.execute(delete(SpelerOpdracht).where(SpelerOpdracht.speler_id == SPELER))
        await session.execute(delete(Speler).where(Speler.discord_id == SPELER))
        await session.commit()


async def _saldo() -> int:
    async with async_session() as session:
        speler = await session.get(Speler, SPELER)
        return speler.currency if speler else 0


async def test_drie_opdrachten_per_dag() -> None:
    print("-- Drie opdrachten per dag, stabiel bij herhaald ophalen --")
    async with async_session() as session:
        eerste = await opdrachten.zorg_voor_opdrachten(session, SPELER)
        await session.commit()
    print(f"Toegewezen: {sorted(o.sleutel for o in eerste)}")
    assert len(eerste) == opdrachten.OPDRACHTEN_PER_DAG

    async with async_session() as session:
        tweede = await opdrachten.zorg_voor_opdrachten(session, SPELER)
        await session.commit()
    assert sorted(o.sleutel for o in eerste) == sorted(o.sleutel for o in tweede), (
        "tweede aanroep gaf andere opdrachten — dan zou je door /opdrachten te spammen "
        "net zo lang kunnen herrollen tot je een makkelijke set hebt"
    )
    print("Tweede aanroep geeft exact dezelfde drie opdrachten.")

    # De speler bestond nog niet: zorg_voor_opdrachten hoort 'm aan te maken
    # voor de foreign key.
    async with async_session() as session:
        assert await session.get(Speler, SPELER) is not None
    print("Speler-rij is automatisch aangemaakt.")


async def test_voortgang_en_uitbetaling() -> None:
    print("\n-- Voortgang, uitbetaling en de bonus bij alle drie --")
    async with async_session() as session:
        mijn = await opdrachten.zorg_voor_opdrachten(session, SPELER)
        sleutels = [o.sleutel for o in mijn]
        doelen = {o.sleutel: o.doel for o in mijn}
        beloningen = {o.sleutel: o.beloning for o in mijn}
        await session.commit()

    saldo_voor = await _saldo()
    bonus = opdrachten.bonus_alle_drie()
    verwacht_totaal = sum(beloningen.values()) + bonus

    for index, sleutel in enumerate(sleutels):
        doel = doelen[sleutel]
        laatste = index == len(sleutels) - 1

        # Eén stap te weinig: nog niet af, dus nog geen uitbetaling.
        if doel > 1:
            async with async_session() as session:
                voltooid = await opdrachten.verhoog(session, SPELER, sleutel, doel - 1)
                await session.commit()
            assert voltooid == [], f"'{sleutel}' werd te vroeg als voltooid gemeld"

        async with async_session() as session:
            voltooid = await opdrachten.verhoog(session, SPELER, sleutel)
            await session.commit()
        assert len(voltooid) == 1, f"'{sleutel}' had precies nu voltooid moeten worden"
        opdracht, uitbetaald = voltooid[0]
        verwacht = beloningen[sleutel] + (bonus if laatste else 0)
        print(f"  {sleutel}: {opdracht.voortgang}/{opdracht.doel} -> +{uitbetaald} Chaos Coins")
        assert uitbetaald == verwacht, f"'{sleutel}' betaalde {uitbetaald} uit, verwacht {verwacht}"

        # Nog een keer ophogen mag niets meer opleveren.
        async with async_session() as session:
            nogmaals = await opdrachten.verhoog(session, SPELER, sleutel, 5)
            await session.commit()
        assert nogmaals == [], f"'{sleutel}' betaalde een tweede keer uit"

    saldo_na = await _saldo()
    print(f"Saldo: {saldo_voor} -> {saldo_na} (verwacht +{verwacht_totaal})")
    assert saldo_na - saldo_voor == verwacht_totaal

    # Voortgang loopt niet door boven het doel: dat zou in /opdrachten
    # "5/3" laten zien.
    async with async_session() as session:
        rijen = (
            await session.execute(
                select(SpelerOpdracht).where(SpelerOpdracht.speler_id == SPELER)
            )
        ).scalars().all()
    for rij in rijen:
        assert rij.voortgang == rij.doel, f"'{rij.sleutel}' staat op {rij.voortgang}/{rij.doel}"
    print("Voortgang is nergens over het doel heen gelopen.")


async def test_nieuwe_dag_geeft_nieuwe_opdrachten() -> None:
    print("\n-- Een nieuwe opdracht-dag geeft een verse set --")
    morgen = opdrachten.huidige_dag() + timedelta(days=1)
    async with async_session() as session:
        nieuw = await opdrachten.zorg_voor_opdrachten(session, SPELER, dag=morgen)
        await session.commit()
    assert len(nieuw) == opdrachten.OPDRACHTEN_PER_DAG
    assert all(o.voltooid_op is None and o.voortgang == 0 for o in nieuw)
    print(f"Morgen: {sorted(o.sleutel for o in nieuw)} (alles op 0)")

    async with async_session() as session:
        totaal = (
            await session.execute(
                select(SpelerOpdracht).where(SpelerOpdracht.speler_id == SPELER)
            )
        ).scalars().all()
    dagen = {o.dag for o in totaal}
    print(f"Rijen in de database: {len(totaal)} over {len(dagen)} dagen")
    assert len(dagen) == 2, "de opdrachten van gisteren horen te blijven staan"
    assert len(totaal) == 2 * opdrachten.OPDRACHTEN_PER_DAG


def test_dag_draait_om_het_resetuur() -> None:
    print("\n-- De dag draait om het resetuur, niet om middernacht --")
    reset_uur = balans.get_int("opdracht_reset_uur", 4)
    tz = opdrachten.AMSTERDAM_TZ

    # Vlak vóór de reset hoor je nog bij de vorige dag.
    net_voor = datetime(2026, 8, 5, reset_uur, 0, tzinfo=tz) - timedelta(minutes=1)
    net_na = datetime(2026, 8, 5, reset_uur, 1, tzinfo=tz)
    print(f"  {net_voor:%d-%m %H:%M} -> dag {opdrachten.huidige_dag(net_voor)}")
    print(f"  {net_na:%d-%m %H:%M} -> dag {opdrachten.huidige_dag(net_na)}")
    assert opdrachten.huidige_dag(net_voor) != opdrachten.huidige_dag(net_na)

    # Middernacht mag juist géén grens zijn: wie 's avonds laat speelt raakt
    # z'n voortgang niet kwijt.
    voor_middernacht = datetime(2026, 8, 5, 23, 59, tzinfo=tz)
    na_middernacht = datetime(2026, 8, 6, 0, 30, tzinfo=tz)
    print(f"  {voor_middernacht:%d-%m %H:%M} en {na_middernacht:%d-%m %H:%M} horen bij dezelfde dag")
    assert opdrachten.huidige_dag(voor_middernacht) == opdrachten.huidige_dag(na_middernacht)


async def test_onbekende_sleutel_is_een_fout() -> None:
    print("\n-- Een onbekende sleutel is een harde fout --")
    async with async_session() as session:
        try:
            await opdrachten.verhoog(session, SPELER, "bestaat-niet")
        except ValueError as e:
            print(f"Geweigerd: {e}")
        else:
            raise AssertionError(
                "onbekende sleutel werd geaccepteerd — een typefout in een aanroep "
                "zou dan een stille no-op zijn"
            )


async def test_commando_toont_voortgang() -> None:
    """De cog zelf, niet alleen de logica: /opdrachten moet een embed
    opleveren met een regel per opdracht en de juiste voortgang."""
    print("\n-- /opdrachten rendert een bruikbare embed --")
    from cogs.opdrachten import OpdrachtenCog

    cog = OpdrachtenCog(bot=MagicMock())
    interactie = MagicMock()
    interactie.user.id = SPELER
    interactie.response = AsyncMock()

    await cog.opdrachten_bekijken.callback(cog, interactie)
    interactie.response.send_message.assert_awaited()
    embed = interactie.response.send_message.call_args.kwargs["embed"]
    print(f"Titel: {embed.title}")
    print(embed.description)

    async with async_session() as session:
        mijn = await opdrachten.zorg_voor_opdrachten(session, SPELER)
        await session.commit()
    assert len(mijn) == opdrachten.OPDRACHTEN_PER_DAG
    for opdracht in mijn:
        type_ = opdrachten.TYPES[opdracht.sleutel]
        assert type_.tekst(opdracht.doel) in embed.description, (
            f"'{opdracht.sleutel}' ontbreekt in de embed"
        )
    velden = {veld.name for veld in embed.fields}
    print(f"Velden: {velden}")
    assert "Bonus" in velden and "Nieuwe opdrachten" in velden

    # Voortgang moet ook echt zichtbaar zijn, niet alleen de titel.
    async with async_session() as session:
        await opdrachten.verhoog(session, SPELER, mijn[0].sleutel)
        await session.commit()
    interactie.response = AsyncMock()
    await cog.opdrachten_bekijken.callback(cog, interactie)
    embed = interactie.response.send_message.call_args.kwargs["embed"]
    async with async_session() as session:
        bijgewerkt = await session.get(SpelerOpdracht, mijn[0].id)
        voortgang, doel = bijgewerkt.voortgang, bijgewerkt.doel
    if voortgang < doel:
        assert f"{voortgang}/{doel}" in embed.description, "voortgang staat niet in de embed"
        print(f"Voortgang {voortgang}/{doel} is zichtbaar in de embed.")
    else:
        assert "✅" in embed.description
        print("Opdracht is meteen afgerond en wordt als voltooid getoond.")


async def main() -> None:
    await balans.laad()
    try:
        await _opruimen()
        await test_drie_opdrachten_per_dag()
        await test_voortgang_en_uitbetaling()
        await test_nieuwe_dag_geeft_nieuwe_opdrachten()
        test_dag_draait_om_het_resetuur()
        await test_onbekende_sleutel_is_een_fout()
        await _opruimen()
        await test_commando_toont_voortgang()
        print("\nAlle checks geslaagd.")
    finally:
        await _opruimen()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
