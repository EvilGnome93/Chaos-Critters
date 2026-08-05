import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

import config
from db.engine import async_session
from db.models import Clan, Huisdier, Instelling, InventarisItem, Item, PetStatus, Speler, Werkplek
from utils import balans, opdrachten
from utils.discord_log import fmt_log, send_log
from utils.leveling import xp_per_effectieve_uur, voeg_xp_toe
from utils.stats import inzetbaarheid_probleem, sync_stats_met_voerbak

log = logging.getLogger("chaos_critters")


def _currency_per_grondstof() -> int:
    return balans.get_int("currency_per_grondstof", 2)


def _bonus_grondstof_aantal() -> int:
    return balans.get_int("bonus_grondstof_aantal", 1)


NOTIFICATIE_CHECK_INTERVAL_SECONDEN = 15 if config.ENVIRONMENT == "dev" else 120


# De cycli zelf staan sinds 2026-07-30 in de database (admin panel fase 2,
# blok 3): zie utils/balans.py:werk_cycli() en de WerkCyclus-tabel. Was een
# module-constante WERK_CYCLI die op import-tijd werd opgebouwd; als functie
# leest elke aanroep de actuele waarden uit de balans-cache.
#
# Historie van de output-multipliers (2026-07-28, Balans-audit, verzoek van
# de gebruiker): overnacht was met 4.5x tegenover korte's 1.0x veruit het
# efficiëntst per uur, waardoor korte/lange shifts weinig zin hadden. De
# huidige verhouding 2.0/2.3/2.6 behoudt een lichte voorkeur voor langere
# shifts (minder inlogmomenten nodig) zonder de kloof zo groot te maken.


def _format_duur(uren: float) -> str:
    if uren < 1:
        return f"{round(uren * 60)} minuten"
    return f"{uren:g} uur"


def _nu() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _voeg_toe_aan_inventaris(session, speler_id: int, item_id: int, aantal: int) -> None:
    stmt = insert(InventarisItem).values(speler_id=speler_id, item_id=item_id, aantal=aantal)
    stmt = stmt.on_conflict_do_update(
        index_elements=["speler_id", "item_id"],
        set_={"aantal": InventarisItem.aantal + aantal},
    )
    await session.execute(stmt)


async def _neem_uit_inventaris(session, speler_id: int, item_id: int, aantal: int) -> bool:
    """Trekt `aantal` van een item af. Geeft False (en boekt niets af) als de
    speler er niet genoeg van heeft.

    Bewust één atomische `UPDATE ... WHERE aantal >= n` i.p.v. de ORM-variant
    (`inv.aantal -= n`): die laatste is een read-modify-write, waardoor twee
    gelijktijdige transacties allebei dezelfde voorraad konden afboeken (lost
    update). Omdat de tegenhanger `_voeg_toe_aan_inventaris` wél atomisch
    optelt, leverde dat bij een dubbelklik op een ruil netto items uit het
    niets op (2026-07-28, gevonden bij de codebase-review)."""
    resultaat = await session.execute(
        update(InventarisItem)
        .where(
            InventarisItem.speler_id == speler_id,
            InventarisItem.item_id == item_id,
            InventarisItem.aantal >= aantal,
        )
        .values(aantal=InventarisItem.aantal - aantal)
    )
    return resultaat.rowcount > 0


async def _max_werkende_pets(session) -> int:
    waarde = await session.scalar(
        select(Instelling.waarde).where(Instelling.sleutel == "max_werkende_pets_per_speler")
    )
    return int(waarde or 3)


async def _aantal_werkende_pets(session, speler_id: int) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(Huisdier)
        .where(Huisdier.eigenaar_id == speler_id, Huisdier.status == PetStatus.werkplek)
    )


async def _aantal_werkend_op_werkplek(session, werkplek_id: int, clan_id: int | None) -> int:
    """Gedeelde capaciteit-telling (2026-07-26, verzoek van de gebruiker) —
    anders dan _aantal_werkende_pets, die per speler telt voor de
    persoonlijke max-3-limiet. Sinds het clan-systeem (2026-07-27) is dit
    geen ene globale pool meer: elke clan heeft zijn eigen pool per
    werkplek, los van clanloze spelers (die samen de "None"-pool delen,
    het oorspronkelijke gedrag)."""
    conditie = Speler.clan_id.is_(None) if clan_id is None else Speler.clan_id == clan_id
    return await session.scalar(
        select(func.count())
        .select_from(Huisdier)
        .join(Speler, Huisdier.eigenaar_id == Speler.discord_id)
        .where(Huisdier.werkplek_type_id == werkplek_id, Huisdier.status == PetStatus.werkplek, conditie)
    )


async def _cyclus_autocomplete(
    interaction: discord.Interaction, huidig: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete i.p.v. een vaste `app_commands.Choice`-lijst (2026-07-30,
    fase 2 blok 3): de duur/energie-kost staan nu in de database en zijn via
    de portal aanpasbaar, terwijl Choice-namen op command-sync-tijd worden
    vastgelegd. Een hardcoded "Korte shift (2 uur)" zou dus stilletjes
    verouderen zodra iemand de duur bijstelt; deze lijst leest elke keer de
    actuele waarden. Werkplek blijft wél een Choice-lijst: daar is alleen de
    naam relevant, en die is niet aanpasbaar."""
    huidig = huidig.lower()
    opties = []
    for sleutel, cyclus in balans.werk_cycli().items():
        if huidig and huidig not in sleutel.lower() and huidig not in cyclus.label.lower():
            continue
        label = f"{cyclus.label} ({_format_duur(cyclus.duur_uren)}, -{cyclus.energie_kost} energie)"
        opties.append(app_commands.Choice(name=label[:100], value=sleutel))
    return opties[:25]


class WerkCog(commands.Cog):
    """De passieve werk-laag op werkplekken. Zie projectbrief sectie 4 en 6.

    Werkplek-capaciteit (Werkplek.capaciteit) is gedeeld over alle spelers
    heen en wordt afgedwongen bij het starten van een nieuwe shift (2026-07-
    26, verzoek van de gebruiker). Energie wordt volledig afgetrokken bij
    start van de shift, niet geleidelijk.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.notificatie_taak: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self.notificatie_taak = asyncio.create_task(self._notificatie_loop())

    async def cog_unload(self) -> None:
        if self.notificatie_taak:
            self.notificatie_taak.cancel()

    async def _notificatie_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(NOTIFICATIE_CHECK_INTERVAL_SECONDEN)
                await self._stuur_klaar_notificaties()
        except asyncio.CancelledError:
            pass

    async def _stuur_klaar_notificaties(self) -> None:
        async with async_session() as session:
            kandidaten = (
                await session.execute(
                    select(Huisdier).where(
                        Huisdier.status == PetStatus.werkplek,
                        Huisdier.werk_notificatie_verstuurd.is_(False),
                    )
                )
            ).scalars().all()

            cycli = balans.werk_cycli()
            for huisdier in kandidaten:
                # .get() i.p.v. [] : dit is een achtergrondtaak, dus een
                # KeyError op een onbekende cyclus (handmatig uit de DB
                # verwijderd) zou de loop permanent stilleggen voor iedereen.
                cyclus_info = cycli.get(huisdier.werk_cyclus)
                if cyclus_info is None:
                    log.warning(
                        "Pet %s heeft onbekende werk_cyclus '%s', notificatie overgeslagen",
                        huisdier.id, huisdier.werk_cyclus,
                    )
                    continue
                if _nu() - huisdier.werk_gestart_op < timedelta(hours=cyclus_info.duur_uren):
                    continue

                huisdier.werk_notificatie_verstuurd = True
                if huisdier.werk_kanaal_id is None:
                    continue
                try:
                    kanaal = self.bot.get_channel(huisdier.werk_kanaal_id) or await self.bot.fetch_channel(
                        huisdier.werk_kanaal_id
                    )
                    await kanaal.send(
                        f"🧺 <@{huisdier.eigenaar_id}> **{huisdier.naam}** is klaar met werken! "
                        f"Gebruik `/werk pet_id:{huisdier.volgnummer}` om de opbrengst op te halen."
                    )
                except discord.HTTPException as e:
                    log.warning(
                        "Kon werk-notificatie niet sturen naar kanaal %s: %s", huisdier.werk_kanaal_id, e
                    )

            await session.commit()

    @app_commands.command(
        name="werk", description="Zet een pet aan het werk, of haal de opbrengst op als de shift klaar is"
    )
    @app_commands.describe(
        pet_id="Het ID van je pet",
        werkplek="De werkplek (alleen nodig om een nieuwe shift te starten)",
        cyclus="De shift-duur (alleen nodig om een nieuwe shift te starten)",
    )
    @app_commands.choices(
        werkplek=[
            app_commands.Choice(name="Moestuin", value="Moestuin"),
            app_commands.Choice(name="Vijver", value="Vijver"),
            app_commands.Choice(name="Werkbank", value="Werkbank"),
            app_commands.Choice(name="Bos", value="Bos"),
            app_commands.Choice(name="Nachtwacht", value="Nachtwacht"),
            app_commands.Choice(name="Mijnschacht", value="Mijnschacht"),
        ],
    )
    @app_commands.autocomplete(cyclus=_cyclus_autocomplete)
    async def werk(
        self,
        interaction: discord.Interaction,
        pet_id: int,
        werkplek: app_commands.Choice[str] | None = None,
        cyclus: str | None = None,
    ) -> None:
        async with async_session() as session:
            huisdier = await session.scalar(
                select(Huisdier).where(
                    Huisdier.eigenaar_id == interaction.user.id, Huisdier.volgnummer == pet_id
                )
            )
            if huisdier is None:
                await interaction.response.send_message(
                    "Je hebt geen pet met dat ID.", ephemeral=True
                )
                return

            await sync_stats_met_voerbak(session, huisdier)

            if huisdier.status == PetStatus.werkplek:
                await self._verwerk_lopende_shift(session, interaction, huisdier)
                return

            if huisdier.status == PetStatus.team:
                await interaction.response.send_message(
                    f"**{huisdier.naam}** zit in je team en kan niet ook werken.", ephemeral=True
                )
                return

            if werkplek is None or cyclus is None:
                await interaction.response.send_message(
                    "Geef zowel `werkplek` als `cyclus` op om een nieuwe shift te starten.",
                    ephemeral=True,
                )
                return

            # `cyclus` komt uit autocomplete i.p.v. een vaste Choice-lijst, dus
            # Discord dwingt hier geen geldige waarde af: een speler kan vrije
            # tekst intypen en versturen zonder een suggestie te kiezen.
            beschikbare_cycli = balans.werk_cycli()
            if cyclus not in beschikbare_cycli:
                keuzes = ", ".join(f"`{s}`" for s in beschikbare_cycli)
                await interaction.response.send_message(
                    f"Onbekende cyclus `{cyclus}`. Kies er een uit de lijst: {keuzes}.", ephemeral=True
                )
                return

            probleem = inzetbaarheid_probleem(huisdier)
            if probleem is not None:
                await interaction.response.send_message(probleem, ephemeral=True)
                return

            max_pets = await _max_werkende_pets(session)
            aantal_werkend = await _aantal_werkende_pets(session, interaction.user.id)
            if aantal_werkend >= max_pets:
                await interaction.response.send_message(
                    f"Je hebt al {max_pets} pets tegelijk aan het werk (het maximum). "
                    "Haal er eerst een op met `/werk pet_id`.",
                    ephemeral=True,
                )
                return

            werkplek_obj = await session.scalar(select(Werkplek).where(Werkplek.type == werkplek.value))
            cyclus_info = beschikbare_cycli[cyclus]

            speler = await session.get(Speler, interaction.user.id)
            clan_id = speler.clan_id if speler else None
            aantal_op_werkplek = await _aantal_werkend_op_werkplek(session, werkplek_obj.id, clan_id)
            if aantal_op_werkplek >= werkplek_obj.capaciteit:
                pool_tekst = "binnen je clan" if clan_id is not None else "onder spelers zonder clan"
                await interaction.response.send_message(
                    f"**{werkplek_obj.type}** zit vol ({aantal_op_werkplek}/{werkplek_obj.capaciteit} bezet, "
                    f"{pool_tekst}). Probeer het straks nog eens.",
                    ephemeral=True,
                )
                return

            huisdier.status = PetStatus.werkplek
            huisdier.werkplek_type_id = werkplek_obj.id
            huisdier.werk_cyclus = cyclus
            huisdier.werk_gestart_op = _nu()
            huisdier.werk_notificatie_verstuurd = False
            huisdier.werk_kanaal_id = interaction.channel_id
            huisdier.energie = max(0, huisdier.energie - cyclus_info.energie_kost)
            await session.commit()

            await interaction.response.send_message(
                f"👷 **{huisdier.naam}** is aan het werk gezet in **{werkplek_obj.type}** "
                f"({cyclus_info.label}, klaar over {_format_duur(cyclus_info.duur_uren)}).",
                ephemeral=True,
            )
            await send_log(
                self.bot,
                interaction.guild_id,
                "werk",
                fmt_log(
                    "🟡",
                    "werk",
                    f"{interaction.user.mention} zette **{huisdier.naam}** aan het werk "
                    f"in {werkplek_obj.type} ({cyclus_info.label})",
                ),
            )

    async def _verwerk_lopende_shift(self, session, interaction: discord.Interaction, huisdier: Huisdier) -> None:
        cyclus_info = balans.werk_cycli().get(huisdier.werk_cyclus)
        if cyclus_info is None:
            # Kan alleen als een cyclus handmatig uit de database verdween
            # terwijl er nog een shift op liep. Nette melding i.p.v. een
            # KeyError, en de pet blijft gewoon aan het werk staan.
            await interaction.response.send_message(
                f"De shift-soort van **{huisdier.naam}** (`{huisdier.werk_cyclus}`) bestaat niet meer. "
                "Meld dit even bij een admin.",
                ephemeral=True,
            )
            return
        verstreken = _nu() - huisdier.werk_gestart_op
        resterend = timedelta(hours=cyclus_info.duur_uren) - verstreken

        if resterend > timedelta(0):
            await interaction.response.send_message(
                f"**{huisdier.naam}** is nog aan het werk. Nog ongeveer {_format_duur(resterend.total_seconds() / 3600)} te gaan.",
                ephemeral=True,
            )
            return

        werkplek_obj = await session.get(Werkplek, huisdier.werkplek_type_id)
        item = await session.get(Item, werkplek_obj.opbrengst_item_id)

        effectieve_uren = cyclus_info.reward_duur_uren * cyclus_info.output_multiplier
        grondstof_aantal = max(
            1, round(float(werkplek_obj.output_per_uur) * effectieve_uren * (float(huisdier.werk_genen) / 100))
        )
        currency_aantal = round(grondstof_aantal * _currency_per_grondstof())

        speler = await session.get(Speler, interaction.user.id)
        speler.currency += currency_aantal
        speler.shiften_voltooid += 1
        if speler.clan_id is not None:
            clan = await session.get(Clan, speler.clan_id)
            clan.totale_werk_opbrengst += currency_aantal
        await _voeg_toe_aan_inventaris(session, interaction.user.id, item.id, grondstof_aantal)

        # Tweede, zeldzamere grondstof met een kleine kans per shift
        # (2026-07-26, verzoek van de gebruiker), los van de hoofdgrondstof.
        bonus_item = None
        if werkplek_obj.opbrengst_item_2_id and random.random() < float(werkplek_obj.opbrengst_2_kans):
            bonus_item = await session.get(Item, werkplek_obj.opbrengst_item_2_id)
            await _voeg_toe_aan_inventaris(session, interaction.user.id, bonus_item.id, _bonus_grondstof_aantal())

        xp_gewonnen = round(effectieve_uren * xp_per_effectieve_uur())
        nieuwe_levels = voeg_xp_toe(huisdier, xp_gewonnen)

        huisdier.status = PetStatus.rust
        huisdier.werkplek_type_id = None
        huisdier.werk_cyclus = None
        huisdier.werk_gestart_op = None
        huisdier.werk_kanaal_id = None
        # In dezelfde transactie als de opbrengst: "de shift is afgerond" en
        # "de dagopdracht telde mee" horen bij elkaar (2026-08-05).
        voltooid = await opdrachten.verhoog(session, interaction.user.id, "werken")
        await session.commit()

        level_up_tekst = ""
        if nieuwe_levels:
            level_up_tekst = f"\n✨ **{huisdier.naam}** bereikte level {nieuwe_levels[-1]}!"
        bonus_tekst = f"\n🍀 Bonus: {_bonus_grondstof_aantal()}x {bonus_item.naam}!" if bonus_item else ""
        opdracht_tekst = "".join(opdrachten.voltooiing_tekst(o, bedrag) for o, bedrag in voltooid)

        await interaction.response.send_message(
            f"🧺 **{huisdier.naam}** is klaar met werken in {werkplek_obj.type}! "
            f"Opbrengst: {grondstof_aantal}x {item.naam}, {currency_aantal} Chaos Coins, {xp_gewonnen} XP."
            f"{bonus_tekst}{level_up_tekst}{opdracht_tekst}",
            ephemeral=True,
        )
        await send_log(
            self.bot,
            interaction.guild_id,
            "werk",
            fmt_log(
                "🟢",
                "werk",
                f"{interaction.user.mention} haalde opbrengst op van **{huisdier.naam}** "
                f"({werkplek_obj.type}): {grondstof_aantal}x {item.naam}, {currency_aantal} Chaos Coins, {xp_gewonnen} XP"
                + (f", bonus {_bonus_grondstof_aantal()}x {bonus_item.naam}" if bonus_item else "")
                + (f", level-up naar {nieuwe_levels[-1]}" if nieuwe_levels else ""),
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WerkCog(bot))
