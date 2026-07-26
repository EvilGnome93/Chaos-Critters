import asyncio
import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.werk import _format_duur, _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Huisdier, Instelling, InventarisItem, Item, PetSoort, PetStatus, Speler, Tier
from utils.afbeeldingen import soort_afbeeldingen
from utils.discord_log import fmt_log, send_log
from utils.elementen import elementen_modifier, emoji as element_emoji, soort_element_emojis, soort_elementen
from utils.vecht_afbeelding import bouw_vs_afbeelding
from utils.gevechten import (
    ENERGIE_KOST_MAX,
    ENERGIE_KOST_MIN,
    RANKED_RESET_UUR,
    XP_VERLIES,
    XP_WINST,
    currency_beloning,
    elo_delta,
    pet_power,
    speel_matchup,
    synthetische_tegenstander_macht,
)
from utils.leveling import voeg_xp_toe
from utils.stats import BLESSURE_DUUR_UUR, inzetbaarheid_probleem, sync_stats

TACTIEK_LABELS = {"aggressief": "🗡️ Aggressief", "gebalanceerd": "⚖️ Gebalanceerd", "voorzichtig": "🛡️ Voorzichtig"}

# Namen voor de PvE-"gesimuleerde tegenstander" (2026-07-26, verzoek van de
# gebruiker: eerlijker/duidelijker dan een naamloze tegenstander — je ziet nu
# wélk wild dier je bevecht, met zijn echte element en afbeelding). Allemaal
# bestaande soorten uit scripts/seed.py, verspreid over tiers/families.
WILDE_NAMEN = [
    "Wolf", "Vos", "Beer", "Das", "IJsbeer", "Neushoorn", "Krokodil", "Haai",
    "Tijger", "Panter", "Poema", "Luipaard", "Hyena", "Wasbeer", "Otter", "Uil",
    "Valk", "Havik", "Steenarend", "Slang", "Anaconda", "Lynx", "Gorilla",
    "Chimpansee", "Bizon", "Nijlpaard", "Walrus", "Zwaardvis", "Struisvogel", "Kraai",
]


async def _kies_wilde_tegenstanders(session, aantal: int) -> list[PetSoort]:
    """Kiest `aantal` unieke wilde tegenstanders (voor de PvE-matchups) uit
    WILDE_NAMEN, met hun echte element + afbeelding erbij."""
    namen = random.sample(WILDE_NAMEN, aantal)
    soorten = (await session.execute(select(PetSoort).where(PetSoort.naam.in_(namen)))).scalars().all()
    soorten_bij_naam = {s.naam: s for s in soorten}
    return [soorten_bij_naam[naam] for naam in namen if naam in soorten_bij_naam]


def _nu():
    from utils.stats import _nu as stats_nu

    return stats_nu()


async def _haal_team_op(session, speler_id: int) -> list[Huisdier]:
    stmt = select(Huisdier).where(Huisdier.eigenaar_id == speler_id, Huisdier.status == PetStatus.team)
    return (await session.execute(stmt)).scalars().all()


async def _team_macht_lijst(session, team: list[Huisdier]) -> list[float]:
    machten = []
    for pet in team:
        tier = await session.get(Tier, pet.tier_id)
        machten.append(pet_power(pet, tier))
    return machten


async def _ranked_gratis_per_dag(session) -> int:
    waarde = await session.scalar(select(Instelling.waarde).where(Instelling.sleutel == "ranked_gratis_per_dag"))
    return int(waarde or 3)


def _reset_ranked_indien_nodig(speler: Speler) -> None:
    nu = _nu()
    if speler.ranked_reset_op is None or (nu - speler.ranked_reset_op) >= timedelta(hours=RANKED_RESET_UUR):
        speler.ranked_reset_op = nu
        speler.ranked_pogingen_vandaag = 0


async def _heeft_ranked_poging(session, speler: Speler) -> tuple[bool, str | None]:
    _reset_ranked_indien_nodig(speler)
    limiet = await _ranked_gratis_per_dag(session)
    if speler.ranked_pogingen_vandaag < limiet:
        return True, None
    token = await session.scalar(select(Item).where(Item.naam == "Extra match token"))
    inv = (
        await session.scalar(
            select(InventarisItem).where(
                InventarisItem.speler_id == speler.discord_id, InventarisItem.item_id == token.id
            )
        )
        if token
        else None
    )
    if inv and inv.aantal >= 1:
        return True, None
    resterend = timedelta(hours=RANKED_RESET_UUR) - (_nu() - speler.ranked_reset_op)
    return False, (
        f"Je hebt je {limiet} gratis ranked pogingen van vandaag gebruikt (reset over "
        f"{_format_duur(resterend.total_seconds() / 3600)}), en geen Extra match token. Koop er een via `/shop`."
    )


async def _verbruik_ranked_poging(session, speler: Speler) -> None:
    _reset_ranked_indien_nodig(speler)
    limiet = await _ranked_gratis_per_dag(session)
    if speler.ranked_pogingen_vandaag < limiet:
        speler.ranked_pogingen_vandaag += 1
        return
    token = await session.scalar(select(Item).where(Item.naam == "Extra match token"))
    inv = await session.scalar(
        select(InventarisItem).where(
            InventarisItem.speler_id == speler.discord_id, InventarisItem.item_id == token.id
        )
    )
    inv.aantal -= 1


async def _inzet_item_opties(session, speler_id: int) -> list[discord.SelectOption]:
    """Dropdown-opties voor het item dat je optioneel inzet bij een
    /vecht-uitdaging: eigen items met voorraad, plus 'Geen item'."""
    opties = [discord.SelectOption(label="Geen item", value="none", default=True)]
    inv_rows = (
        await session.execute(
            select(InventarisItem).where(InventarisItem.speler_id == speler_id, InventarisItem.aantal > 0)
        )
    ).scalars().all()
    if inv_rows:
        item_ids = [r.item_id for r in inv_rows]
        items_bij_id = {
            i.id: i for i in (await session.execute(select(Item).where(Item.id.in_(item_ids)))).scalars().all()
        }
        for r in inv_rows:
            item = items_bij_id[r.item_id]
            opties.append(
                discord.SelectOption(label=f"{item.naam} ({r.aantal}x in bezit)"[:100], value=item.naam[:100])
            )
    return opties[:25]


class VechtAantalModal(discord.ui.Modal):
    def __init__(self, view: "VechtInzetView"):
        super().__init__(title="Aantal instellen")
        self.view_ref = view
        self.aantal_input = discord.ui.TextInput(
            label="Aantal (alleen relevant bij een item)", default=str(view.aantal), required=False, max_length=5
        )
        self.add_item(self.aantal_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            aantal = max(1, int(self.aantal_input.value or 1))
        except ValueError:
            aantal = 1
        self.view_ref.aantal = aantal
        await interaction.response.edit_message(embed=self.view_ref._bouw_embed(), view=self.view_ref)


class VechtCoinsModal(discord.ui.Modal):
    def __init__(self, view: "VechtInzetView"):
        super().__init__(title="Chaos Coins instellen")
        self.view_ref = view
        self.coins_input = discord.ui.TextInput(
            label="Chaos Coins", default=str(view.coins), required=False, max_length=8
        )
        self.add_item(self.coins_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            coins = max(0, int(self.coins_input.value or 0))
        except ValueError:
            coins = 0
        self.view_ref.coins = coins
        await interaction.response.edit_message(embed=self.view_ref._bouw_embed(), view=self.view_ref)


class VechtInzetView(discord.ui.View):
    """Paneel om de inzet (item + Chaos Coins) voor een PvP-uitdaging samen
    te stellen, i.p.v. losse command-parameters (2026-07-26, feedback van de
    gebruiker: zelfde reden als de /trade-herbouw naar een paneel)."""

    def __init__(
        self,
        cog: "GevechtenCog",
        uitdager_id: int,
        tegenstander: discord.Member,
        guild_id: int | None,
        item_opties: list[discord.SelectOption],
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.uitdager_id = uitdager_id
        self.tegenstander = tegenstander
        self.guild_id = guild_id
        self.item_waarde: str | None = None
        self.aantal = 1
        self.coins = 0
        self.message: discord.Message | None = None

        self.item_select = discord.ui.Select(placeholder="Item inzetten? (optioneel)", options=item_opties, row=0)
        self.item_select.callback = self._on_item_select
        self.add_item(self.item_select)

        aantal_knop = discord.ui.Button(label="🔢 Aantal instellen", style=discord.ButtonStyle.secondary, row=1)
        aantal_knop.callback = self._open_aantal_modal
        self.add_item(aantal_knop)

        coins_knop = discord.ui.Button(label="💰 Coins instellen", style=discord.ButtonStyle.secondary, row=1)
        coins_knop.callback = self._open_coins_modal
        self.add_item(coins_knop)

        uitdagen_knop = discord.ui.Button(label="⚔️ Uitdagen", style=discord.ButtonStyle.success, row=2)
        uitdagen_knop.callback = self._uitdagen
        self.add_item(uitdagen_knop)

        annuleren_knop = discord.ui.Button(label="❌ Annuleren", style=discord.ButtonStyle.danger, row=2)
        annuleren_knop.callback = self._annuleren
        self.add_item(annuleren_knop)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.uitdager_id:
            await interaction.response.send_message("Dit is niet jouw uitdaging om samen te stellen.", ephemeral=True)
            return False
        return True

    def _inzet_tekst(self) -> str:
        delen = []
        if self.item_waarde:
            delen.append(f"{self.aantal}x {self.item_waarde}")
        if self.coins:
            delen.append(f"{self.coins} Chaos Coins")
        return " + ".join(delen) if delen else "geen inzet"

    def _bouw_embed(self) -> discord.Embed:
        return discord.Embed(
            title="⚔️ Uitdaging voorbereiden",
            description=f"Tegenstander: {self.tegenstander.mention}\nInzet: {self._inzet_tekst()}",
            color=discord.Color.blurple(),
        )

    async def _on_item_select(self, interaction: discord.Interaction) -> None:
        waarde = self.item_select.values[0]
        self.item_waarde = None if waarde == "none" else waarde
        await interaction.response.edit_message(embed=self._bouw_embed(), view=self)

    async def _open_aantal_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(VechtAantalModal(self))

    async def _open_coins_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(VechtCoinsModal(self))

    async def _uitdagen(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            speler = await session.get(Speler, self.uitdager_id)
            if self.item_waarde:
                item_obj = await session.scalar(select(Item).where(Item.naam == self.item_waarde))
                if item_obj is None:
                    await interaction.response.send_message(f"Onbekend item: **{self.item_waarde}**.", ephemeral=True)
                    return
                eigen_inv = await session.scalar(
                    select(InventarisItem).where(
                        InventarisItem.speler_id == self.uitdager_id, InventarisItem.item_id == item_obj.id
                    )
                )
                if eigen_inv is None or eigen_inv.aantal < self.aantal:
                    await interaction.response.send_message(
                        f"Je hebt geen {self.aantal}x **{self.item_waarde}** (meer) om in te zetten.", ephemeral=True
                    )
                    return
            if self.coins and (speler is None or speler.currency < self.coins):
                await interaction.response.send_message(
                    "Je hebt niet (meer) genoeg Chaos Coins voor die inzet.", ephemeral=True
                )
                return

        inzet_item_getal = (self.item_waarde, self.aantal) if self.item_waarde else None

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Uitdaging verstuurd.", embed=None, view=self)

        inzet_tekst = ""
        if self.coins:
            inzet_tekst += f"\n💰 Inzet: {self.coins} Chaos Coins"
        if inzet_item_getal:
            inzet_tekst += f"\n📦 Inzet: {inzet_item_getal[1]}x {inzet_item_getal[0]}"

        uitdaging_view = UitdagingView(
            self.cog, self.uitdager_id, self.tegenstander.id, self.coins, inzet_item_getal, self.guild_id
        )
        embed = discord.Embed(
            title="⚔️ Ranked uitdaging!",
            description=(
                f"<@{self.uitdager_id}> daagt {self.tegenstander.mention} uit voor een gevecht.{inzet_tekst}\n\n"
                "Beide teams moeten een volledig team van 3 hebben. Accepteren of weigeren?"
            ),
            color=discord.Color.orange(),
        )
        bericht = await interaction.channel.send(content=self.tegenstander.mention, embed=embed, view=uitdaging_view)
        uitdaging_view.message = bericht
        await send_log(
            self.cog.bot, self.guild_id, "gevecht",
            fmt_log(
                "🟡", "vecht",
                f"<@{self.uitdager_id}> daagde {self.tegenstander.mention} uit voor een gevecht"
                + (inzet_tekst.replace("\n", ", ") if inzet_tekst else ""),
            ),
        )

    async def _annuleren(self, interaction: discord.Interaction) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Geannuleerd.", embed=None, view=self)

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(content="⌛ Uitdaging-opbouw verlopen.", embed=None, view=self)
        except discord.HTTPException:
            pass


class TeamSelectView(discord.ui.View):
    def __init__(
        self, eigenaar_id: int, opties: list[Huisdier], huidige_team_ids: set[int], soort_elementen: dict[int, str]
    ):
        super().__init__(timeout=120)
        self.eigenaar_id = eigenaar_id
        self.message: discord.Message | None = None

        select_opties = [
            discord.SelectOption(
                label=f"{soort_elementen.get(p.soort_id, '❓')} #{p.volgnummer} {p.naam} (lvl {p.level})",
                value=str(p.id), default=p.id in huidige_team_ids,
            )
            for p in opties[:25]
        ]
        self.select = discord.ui.Select(
            placeholder="Kies max 3 pets voor je team",
            min_values=0,
            max_values=min(3, len(select_opties)) if select_opties else 1,
            options=select_opties or [discord.SelectOption(label="(geen beschikbare pets)", value="0")],
            disabled=not select_opties,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.eigenaar_id:
            await interaction.response.send_message("Dit is niet jouw team-selectie.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        gekozen_ids = {int(v) for v in self.select.values}
        async with async_session() as session:
            pets = (
                await session.execute(select(Huisdier).where(Huisdier.eigenaar_id == self.eigenaar_id))
            ).scalars().all()
            namen = []
            for pet in pets:
                if pet.id in gekozen_ids:
                    pet.status = PetStatus.team
                    namen.append(pet.naam)
                elif pet.status == PetStatus.team:
                    pet.status = PetStatus.rust
            await session.commit()

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Team ingesteld: {', '.join(namen) if namen else '(leeg)'}", view=self
        )


class UitdagingView(discord.ui.View):
    def __init__(
        self,
        cog: "GevechtenCog",
        uitdager_id: int,
        tegenstander_id: int,
        inzet_coins: int,
        inzet_item,
        guild_id: int | None,
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.uitdager_id = uitdager_id
        self.tegenstander_id = tegenstander_id
        self.inzet_coins = inzet_coins
        self.inzet_item = inzet_item
        self.guild_id = guild_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.tegenstander_id:
            await interaction.response.send_message("Deze uitdaging is niet voor jou.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Accepteren", style=discord.ButtonStyle.success)
    async def accepteren(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await send_log(
            self.cog.bot,
            self.guild_id,
            "gevecht",
            fmt_log("🟢", "vecht", f"<@{self.tegenstander_id}> accepteerde de uitdaging van <@{self.uitdager_id}>"),
        )
        await self.cog.start_pvp_gevecht(interaction, self)

    @discord.ui.button(label="❌ Weigeren", style=discord.ButtonStyle.danger)
    async def weigeren(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Uitdaging geweigerd.", embed=None, view=self)
        await send_log(
            self.cog.bot,
            self.guild_id,
            "gevecht",
            fmt_log("🔴", "vecht", f"<@{self.tegenstander_id}> weigerde de uitdaging van <@{self.uitdager_id}>"),
        )

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(content="⌛ Uitdaging verlopen.", view=self)
        except discord.HTTPException:
            pass
        await send_log(
            self.cog.bot,
            self.guild_id,
            "gevecht",
            fmt_log("🔴", "vecht", f"Uitdaging van <@{self.uitdager_id}> aan <@{self.tegenstander_id}> verliep zonder reactie"),
        )


class VechtView(discord.ui.View):
    """Speelt een best-of-3 van opeenvolgende 1v1-matchups. Per matchup kiest
    elke kant een tactiek (of vlucht): bij PvE kiest alleen de speler (de
    tegenstander is een simulatie), bij PvP kiezen beide spelers en wordt de
    matchup pas opgelost zodra allebei gekozen hebben."""

    def __init__(
        self,
        bot,
        eigen_id: int,
        eigen_team: list[Huisdier],
        eigen_macht: list[float],
        eigen_mmr: int,
        tegenstander_naam: str,
        tegenstander_team: list[Huisdier] | None,
        tegenstander_macht: list[float],
        tegenstander_mmr: int,
        guild_id: int | None,
        inzet_coins: int,
        inzet_item: tuple[str, int] | None,
        tegenstander_id: int | None,
        eigen_elementen: list,
        tegenstander_elementen: list,
        eigen_afbeeldingen: list,
        tegenstander_afbeeldingen: list,
        tegenstander_namen: list[str] | None = None,
    ):
        super().__init__(timeout=180)
        self.bot = bot
        self.eigen_id = eigen_id
        self.eigen_team = eigen_team
        self.eigen_macht = eigen_macht
        self.eigen_mmr = eigen_mmr
        self.tegenstander_naam = tegenstander_naam
        self.tegenstander_team = tegenstander_team
        self.tegenstander_macht = tegenstander_macht
        self.tegenstander_mmr = tegenstander_mmr
        self.guild_id = guild_id
        self.inzet_coins = inzet_coins
        self.inzet_item = inzet_item
        self.tegenstander_id = tegenstander_id
        self.eigen_elementen = eigen_elementen
        self.tegenstander_elementen = tegenstander_elementen
        self.eigen_afbeeldingen = eigen_afbeeldingen
        self.tegenstander_afbeeldingen = tegenstander_afbeeldingen
        # Per-matchup naam voor de PvE-tegenstander ("Wilde Wolf" i.p.v. het
        # oude, naamloze "gesimuleerde tegenstander"). Bij PvP altijd de echte
        # pet-naam (self.tegenstander_team), dus deze lijst blijft dan None.
        self.tegenstander_namen = tegenstander_namen

        self.matchup_index = 0
        self.eigen_wins = 0
        self.tegenstander_wins = 0
        self.eigen_tactiek: str | None = None
        self.tegenstander_tactiek: str | None = None
        self.message: discord.Message | None = None

    @property
    def is_pvp(self) -> bool:
        return self.tegenstander_id is not None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.eigen_id, self.tegenstander_id):
            await interaction.response.send_message("Dit is niet jouw gevecht.", ephemeral=True)
            return False
        return True

    async def _bouw_intro(self) -> tuple[discord.Embed, discord.File | None]:
        eigen_pet = self.eigen_team[self.matchup_index]
        eigen_el = self.eigen_elementen[self.matchup_index]
        tegen_el = self.tegenstander_elementen[self.matchup_index]
        tegen_naam = (
            self.tegenstander_team[self.matchup_index].naam
            if self.tegenstander_team
            else f"Wilde {self.tegenstander_namen[self.matchup_index]}"
        )
        instructie = (
            f"Beide spelers kiezen een tactiek (of vluchten) — <@{self.eigen_id}> en <@{self.tegenstander_id}>:"
            if self.is_pvp
            else "Kies een tactiek voor deze matchup:"
        )
        embed = discord.Embed(
            title=(
                f"⚔️ Matchup {self.matchup_index + 1}/3: "
                f"{element_emoji(eigen_el)} {eigen_pet.naam} vs {element_emoji(tegen_el)} {tegen_naam}"
            ),
            description=(
                f"Stand: jij {self.eigen_wins} - {self.tegenstander_wins} {self.tegenstander_naam}\n{instructie}"
            ),
            color=discord.Color.orange(),
        )

        bestand = None
        eigen_url = self.eigen_afbeeldingen[self.matchup_index]
        tegen_url = self.tegenstander_afbeeldingen[self.matchup_index]
        if eigen_url and tegen_url:
            buffer = await bouw_vs_afbeelding(eigen_url, tegen_url)
            if buffer is not None:
                bestand = discord.File(buffer, filename="vs.png")
                embed.set_image(url="attachment://vs.png")
        elif eigen_url:
            embed.set_image(url=eigen_url)

        return embed, bestand

    def _wacht_embed(self) -> discord.Embed:
        wie = f"<@{self.eigen_id}>" if self.eigen_tactiek is not None else f"<@{self.tegenstander_id}>"
        return discord.Embed(
            title=f"⏳ Matchup {self.matchup_index + 1}/3 — wachten...",
            description=f"{wie} heeft gekozen. Wachten op de andere speler.",
            color=discord.Color.orange(),
        )

    async def start(self, interaction: discord.Interaction) -> None:
        embed, bestand = await self._bouw_intro()
        if bestand is not None:
            await interaction.response.send_message(embed=embed, view=self, file=bestand)
        else:
            await interaction.response.send_message(embed=embed, view=self)
        self.message = await interaction.original_response()

    async def _blesseer(self, pet_id: int) -> None:
        async with async_session() as session:
            pet = await session.get(Huisdier, pet_id)
            pet.energie = 0
            pet.geblesseerd_tot = _nu() + timedelta(hours=BLESSURE_DUUR_UUR)
            await session.commit()

    async def _kies_tactiek(self, interaction: discord.Interaction, tactiek: str) -> None:
        if interaction.user.id == self.eigen_id:
            if self.eigen_tactiek is not None:
                await interaction.response.send_message(
                    "Je hebt al gekozen voor deze matchup, wachten op de andere speler...", ephemeral=True
                )
                return
            self.eigen_tactiek = tactiek
        else:
            if self.tegenstander_tactiek is not None:
                await interaction.response.send_message(
                    "Je hebt al gekozen voor deze matchup, wachten op de andere speler...", ephemeral=True
                )
                return
            self.tegenstander_tactiek = tactiek

        await interaction.response.defer()

        if self.is_pvp and (self.eigen_tactiek is None or self.tegenstander_tactiek is None):
            await self.message.edit(embed=self._wacht_embed(), view=self)
            return

        eigen_tactiek = self.eigen_tactiek
        tegenstander_tactiek = self.tegenstander_tactiek if self.is_pvp else "gebalanceerd"

        eigen_el = self.eigen_elementen[self.matchup_index]
        tegen_el = self.tegenstander_elementen[self.matchup_index]
        eigen_macht_gemod = self.eigen_macht[self.matchup_index] * elementen_modifier(eigen_el, tegen_el)
        tegenstander_macht_gemod = self.tegenstander_macht[self.matchup_index] * elementen_modifier(tegen_el, eigen_el)

        resultaat = speel_matchup(
            eigen_macht_gemod,
            tegenstander_macht_gemod,
            eigen_tactiek,
            tegenstander_tactiek,
        )
        if resultaat.eigen_wint:
            self.eigen_wins += 1
            if self.tegenstander_team is not None:
                await self._blesseer(self.tegenstander_team[self.matchup_index].id)
        else:
            self.tegenstander_wins += 1
            await self._blesseer(self.eigen_team[self.matchup_index].id)

        uitslag_tekst = "✅ Jij wint deze matchup!" if resultaat.eigen_wint else "❌ Jij verliest deze matchup."
        tactiek_tekst = (
            f"{TACTIEK_LABELS[eigen_tactiek]} vs {TACTIEK_LABELS[tegenstander_tactiek]}"
            if self.is_pvp
            else TACTIEK_LABELS[eigen_tactiek]
        )
        resultaat_embed = discord.Embed(
            title=f"Matchup {self.matchup_index + 1}/3 — {tactiek_tekst}",
            description=(
                f"{chr(10).join(resultaat.ronde_log)}\n\n{uitslag_tekst}\n"
                f"Stand: jij {self.eigen_wins} - {self.tegenstander_wins} {self.tegenstander_naam}"
            ),
            color=discord.Color.green() if resultaat.eigen_wint else discord.Color.red(),
        )
        await self.message.edit(embed=resultaat_embed, view=None)

        if self.eigen_wins == 2 or self.tegenstander_wins == 2 or self.matchup_index == 2:
            await asyncio.sleep(1.5)
            await self._verwerk_einde()
            return

        self.matchup_index += 1
        self.eigen_tactiek = None
        self.tegenstander_tactiek = None
        await asyncio.sleep(2)
        embed, bestand = await self._bouw_intro()
        await self.message.edit(embed=embed, view=self, attachments=[bestand] if bestand else [])

    async def _wegrennen(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        gevlucht_id = interaction.user.id
        if gevlucht_id == self.eigen_id:
            self.tegenstander_wins = 3
            vlucht_tekst = f"<@{self.eigen_id}> is gevlucht uit het gevecht!"
        else:
            self.eigen_wins = 3
            vlucht_tekst = f"<@{self.tegenstander_id}> is gevlucht uit het gevecht!"
        await self.message.edit(
            embed=discord.Embed(title=f"🏃 {vlucht_tekst}", color=discord.Color.dark_grey()),
            view=None,
            attachments=[],
        )
        await asyncio.sleep(1)
        await self._verwerk_einde(gevlucht_id=gevlucht_id)

    async def _verwerk_einde(self, gevlucht_id: int | None = None) -> None:
        gewonnen = self.eigen_wins > self.tegenstander_wins
        nieuwe_levels_eigen: list[tuple[str, int]] = []

        tegen_delta = None
        async with async_session() as session:
            speler = await session.get(Speler, self.eigen_id)
            delta = elo_delta(self.eigen_mmr, self.tegenstander_mmr, gewonnen)
            speler.mmr = max(0, speler.mmr + delta)

            beloning = 0
            if gewonnen:
                beloning = currency_beloning(self.tegenstander_mmr)
                speler.currency += beloning

            for pet in self.eigen_team:
                pet_db = await session.get(Huisdier, pet.id)
                for nieuw_level in voeg_xp_toe(pet_db, XP_WINST if gewonnen else XP_VERLIES):
                    nieuwe_levels_eigen.append((pet_db.naam, nieuw_level))

            if self.tegenstander_id is not None:
                tegen_speler = await session.get(Speler, self.tegenstander_id)
                tegen_delta = elo_delta(self.tegenstander_mmr, self.eigen_mmr, not gewonnen)
                tegen_speler.mmr = max(0, tegen_speler.mmr + tegen_delta)
                for pet in self.tegenstander_team:
                    pet_db = await session.get(Huisdier, pet.id)
                    voeg_xp_toe(pet_db, XP_VERLIES if gewonnen else XP_WINST)

                winnaar_id = self.eigen_id if gewonnen else self.tegenstander_id
                verliezer_id = self.tegenstander_id if gewonnen else self.eigen_id
                winnaar_speler = speler if gewonnen else tegen_speler
                verliezer_speler = tegen_speler if gewonnen else speler

                if self.inzet_coins:
                    winnaar_speler.currency += self.inzet_coins
                    verliezer_speler.currency -= self.inzet_coins
                if self.inzet_item:
                    item_naam, aantal = self.inzet_item
                    item_obj = await session.scalar(select(Item).where(Item.naam == item_naam))
                    verliezer_inv = await session.scalar(
                        select(InventarisItem).where(
                            InventarisItem.speler_id == verliezer_id, InventarisItem.item_id == item_obj.id
                        )
                    )
                    if verliezer_inv:
                        verliezer_inv.aantal = max(0, verliezer_inv.aantal - aantal)
                    await _voeg_toe_aan_inventaris(session, winnaar_id, item_obj.id, aantal)

            await session.commit()

        # Bij PvP kijken beide spelers naar hetzelfde bericht — "jij" is dan
        # dubbelzinnig (wint/verliest voor wie precies?). Expliciete mentions
        # lossen dat op; bij PvE is er maar één speler, dus blijft "Jij" prima
        # leesbaar. Feedback van de gebruiker: dit was verwarrend voor de
        # niet-uitdagende speler.
        eigen_ref = f"<@{self.eigen_id}>" if self.is_pvp else "Jij"
        tegen_ref = f"<@{self.tegenstander_id}>" if self.is_pvp else self.tegenstander_naam

        if gevlucht_id is not None and gevlucht_id == self.eigen_id:
            titel = f"🏳️ {eigen_ref} is gevlucht"
        elif gevlucht_id is not None and gevlucht_id == self.tegenstander_id:
            titel = f"🏆 {eigen_ref} wint! (tegenstander vluchtte)"
        else:
            titel = f"🏆 {eigen_ref} wint!" if gewonnen else f"💀 {eigen_ref} verliest"
        beschrijving = f"Eindstand: {eigen_ref} {self.eigen_wins} - {self.tegenstander_wins} {tegen_ref}\n"
        if self.is_pvp:
            beschrijving += (
                f"MMR-verandering: {eigen_ref} {'+' if delta >= 0 else ''}{delta}, "
                f"{tegen_ref} {'+' if tegen_delta >= 0 else ''}{tegen_delta}\n"
            )
        else:
            beschrijving += f"MMR-verandering: {'+' if delta >= 0 else ''}{delta}\n"
        if beloning:
            beschrijving += f"Beloning voor {eigen_ref}: {beloning} Chaos Coins\n"
        if self.inzet_coins or self.inzet_item:
            winnaar_ref = eigen_ref if gewonnen else tegen_ref
            beschrijving += f"Inzet gaat naar {winnaar_ref}: "
            delen = []
            if self.inzet_coins:
                delen.append(f"{self.inzet_coins} Chaos Coins")
            if self.inzet_item:
                delen.append(f"{self.inzet_item[1]}x {self.inzet_item[0]}")
            beschrijving += ", ".join(delen) + "\n"
        if nieuwe_levels_eigen:
            beschrijving += "\n✨ " + ", ".join(f"{naam} bereikte level {level}!" for naam, level in nieuwe_levels_eigen)

        await self.message.edit(
            embed=discord.Embed(
                title=titel, description=beschrijving, color=discord.Color.gold() if gewonnen else discord.Color.dark_red()
            ),
            view=None,
            attachments=[],
        )
        await send_log(
            self.bot,
            self.guild_id,
            "gevecht",
            fmt_log(
                "🟢" if gewonnen else "🔴",
                "vecht",
                f"{titel} — gevecht {eigen_ref} vs {tegen_ref} "
                f"({self.eigen_wins}-{self.tegenstander_wins}), MMR {'+' if delta >= 0 else ''}{delta}",
            ),
        )

    @discord.ui.button(label="🗡️ Aggressief", style=discord.ButtonStyle.danger)
    async def aggressief(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._kies_tactiek(interaction, "aggressief")

    @discord.ui.button(label="⚖️ Gebalanceerd", style=discord.ButtonStyle.primary)
    async def gebalanceerd(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._kies_tactiek(interaction, "gebalanceerd")

    @discord.ui.button(label="🛡️ Voorzichtig", style=discord.ButtonStyle.success)
    async def voorzichtig(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._kies_tactiek(interaction, "voorzichtig")

    @discord.ui.button(label="🏃 Wegrennen", style=discord.ButtonStyle.secondary)
    async def wegrennen(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wegrennen(interaction)


class GevechtenCog(commands.Cog):
    """Teams samenstellen en ranked matches. Zie projectbrief sectie 12."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="team", description="Stel je team van 3 pets samen voor gevechten")
    async def team(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            pets = (
                await session.execute(select(Huisdier).where(Huisdier.eigenaar_id == interaction.user.id))
            ).scalars().all()
            for pet in pets:
                sync_stats(pet)
            await session.commit()
            elementen = await soort_element_emojis(session)

        if not pets:
            await interaction.response.send_message("Je hebt nog geen pets gevangen.", ephemeral=True)
            return

        huidige_team = [p for p in pets if p.status == PetStatus.team]
        # Pets die al in het team zitten blijven altijd in de lijst staan, ook
        # als ze inmiddels niet meer inzetbaar zijn (bijv. energie weggezakt) —
        # anders verdwijnen ze uit de dropdown en kan je je team niet meer
        # aanpassen/leeghalen. Nieuwe pets moeten wel gewoon inzetbaar zijn.
        beschikbaar = [
            p for p in pets
            if p.status != PetStatus.werkplek and (p.status == PetStatus.team or inzetbaarheid_probleem(p) is None)
        ]

        embed = discord.Embed(
            title="⚔️ Jouw team",
            description=(
                ", ".join(f"{elementen.get(p.soort_id, '❓')} #{p.volgnummer} {p.naam}" for p in huidige_team)
                if huidige_team else "Nog geen team samengesteld."
            ),
            color=discord.Color.blurple(),
        )
        view = TeamSelectView(interaction.user.id, beschikbaar, {p.id for p in huidige_team}, elementen)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(
        name="vecht", description="Start een ranked gevecht: gesimuleerde tegenstander, of daag een speler uit"
    )
    @app_commands.describe(
        tegenstander="Daag deze speler uit (optioneel; zonder dit vecht je tegen een gesimuleerde tegenstander)",
    )
    async def vecht(
        self,
        interaction: discord.Interaction,
        tegenstander: discord.Member | None = None,
    ) -> None:
        async with async_session() as session:
            eigen_team = await _haal_team_op(session, interaction.user.id)
            for pet in eigen_team:
                sync_stats(pet)
            await session.commit()

            if len(eigen_team) != 3:
                await interaction.response.send_message(
                    "Je hebt geen volledig team van 3. Stel er eerst een samen met `/team`.", ephemeral=True
                )
                return
            for pet in eigen_team:
                probleem = inzetbaarheid_probleem(pet)
                if probleem:
                    await interaction.response.send_message(f"{probleem}", ephemeral=True)
                    return

            speler = await session.get(Speler, interaction.user.id)
            heeft_poging, poging_probleem = await _heeft_ranked_poging(session, speler)
            if not heeft_poging:
                await session.commit()
                await interaction.response.send_message(poging_probleem, ephemeral=True)
                return

            if tegenstander is not None:
                item_opties = await _inzet_item_opties(session, interaction.user.id)

            await session.commit()

        if tegenstander is not None:
            if tegenstander.id == interaction.user.id:
                await interaction.response.send_message("Je kan jezelf niet uitdagen.", ephemeral=True)
                return
            if tegenstander.bot:
                await interaction.response.send_message("Je kan geen bot uitdagen.", ephemeral=True)
                return

            view = VechtInzetView(self, interaction.user.id, tegenstander, interaction.guild_id, item_opties)
            await interaction.response.send_message(embed=view._bouw_embed(), view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return

        # PvE: gesimuleerde tegenstander, per matchup gespiegeld op de macht
        # van de eigen pet in die matchup (blijft eerlijk ongeacht hoe scheef
        # de eigen teamsamenstelling is), met een kleine MMR-modifier.
        async with async_session() as session:
            speler = await session.get(Speler, interaction.user.id)
            await _verbruik_ranked_poging(session, speler)
            for pet in eigen_team:
                pet_db = await session.get(Huisdier, pet.id)
                pet_db.energie = max(0, pet_db.energie - random.randint(ENERGIE_KOST_MIN, ENERGIE_KOST_MAX))
            eigen_macht = await _team_macht_lijst(session, eigen_team)
            eigen_mmr = speler.mmr
            elementen_bij_soort = await soort_elementen(session)
            afbeeldingen_bij_soort = await soort_afbeeldingen(session)
            wilde_soorten = await _kies_wilde_tegenstanders(session, len(eigen_team))
            await session.commit()

        tegenstander_mmr = eigen_mmr
        tegenstander_macht = [
            synthetische_tegenstander_macht(macht, eigen_mmr) * random.uniform(0.85, 1.15)
            for macht in eigen_macht
        ]
        eigen_elementen = [elementen_bij_soort.get(pet.soort_id) for pet in eigen_team]
        eigen_afbeeldingen = [afbeeldingen_bij_soort.get(pet.soort_id) for pet in eigen_team]
        # Gesimuleerde tegenstander heeft geen echte pet, maar leent naam +
        # element + afbeelding van een echte, willekeurig gekozen wilde soort
        # (2026-07-26, verzoek van de gebruiker: eerlijker als je vooraf weet
        # tegen wat/welk element je vecht, i.p.v. een naamloze tegenstander).
        tegenstander_namen = [soort.naam for soort in wilde_soorten]
        tegenstander_elementen = [soort.element for soort in wilde_soorten]
        tegenstander_afbeeldingen = [soort.afbeelding_url for soort in wilde_soorten]

        view = VechtView(
            self.bot,
            interaction.user.id,
            eigen_team,
            eigen_macht,
            eigen_mmr,
            "de wilde dieren",
            None,
            tegenstander_macht,
            tegenstander_mmr,
            interaction.guild_id,
            0,
            None,
            None,
            eigen_elementen,
            tegenstander_elementen,
            eigen_afbeeldingen,
            tegenstander_afbeeldingen,
            tegenstander_namen,
        )
        await view.start(interaction)
        await send_log(
            self.bot,
            interaction.guild_id,
            "gevecht",
            fmt_log(
                "🟡", "vecht",
                f"{interaction.user.mention} startte een gevecht tegen wilde dieren "
                f"({', '.join(tegenstander_namen)}, MMR {tegenstander_mmr})",
            ),
        )

    async def _annuleer_uitdaging(
        self, interaction: discord.Interaction, uitdaging: UitdagingView, reden: str
    ) -> None:
        await interaction.response.edit_message(content=f"{reden} Uitdaging geannuleerd.", embed=None, view=uitdaging)
        await send_log(
            self.bot,
            uitdaging.guild_id,
            "gevecht",
            fmt_log(
                "🔴",
                "vecht",
                f"Uitdaging tussen <@{uitdaging.uitdager_id}> en <@{uitdaging.tegenstander_id}> geannuleerd: {reden}",
            ),
        )

    async def start_pvp_gevecht(self, interaction: discord.Interaction, uitdaging: UitdagingView) -> None:
        async with async_session() as session:
            eigen_team = await _haal_team_op(session, uitdaging.uitdager_id)
            tegenstander_team = await _haal_team_op(session, uitdaging.tegenstander_id)
            for pet in [*eigen_team, *tegenstander_team]:
                sync_stats(pet)
            await session.commit()

            if len(eigen_team) != 3 or len(tegenstander_team) != 3:
                await self._annuleer_uitdaging(
                    interaction, uitdaging, "Een van beide spelers heeft geen volledig team meer van 3."
                )
                return
            for pet in [*eigen_team, *tegenstander_team]:
                probleem = inzetbaarheid_probleem(pet)
                if probleem:
                    await self._annuleer_uitdaging(interaction, uitdaging, probleem)
                    return

            uitdager = await session.get(Speler, uitdaging.uitdager_id)
            tegenstander_speler = await session.get(Speler, uitdaging.tegenstander_id)

            for speler in (uitdager, tegenstander_speler):
                heeft_poging, poging_probleem = await _heeft_ranked_poging(session, speler)
                if not heeft_poging:
                    await session.commit()
                    await self._annuleer_uitdaging(interaction, uitdaging, f"<@{speler.discord_id}>: {poging_probleem}")
                    return

            if uitdaging.inzet_coins:
                if uitdager.currency < uitdaging.inzet_coins or tegenstander_speler.currency < uitdaging.inzet_coins:
                    await session.commit()
                    await self._annuleer_uitdaging(
                        interaction, uitdaging, "Een van beide spelers heeft niet meer genoeg Chaos Coins voor de inzet."
                    )
                    return
            if uitdaging.inzet_item:
                item_naam, aantal = uitdaging.inzet_item
                item_obj = await session.scalar(select(Item).where(Item.naam == item_naam))
                for speler_id in (uitdaging.uitdager_id, uitdaging.tegenstander_id):
                    inv = await session.scalar(
                        select(InventarisItem).where(
                            InventarisItem.speler_id == speler_id, InventarisItem.item_id == item_obj.id
                        )
                    )
                    if inv is None or inv.aantal < aantal:
                        await session.commit()
                        await self._annuleer_uitdaging(
                            interaction, uitdaging, f"<@{speler_id}> heeft niet meer genoeg **{item_naam}** voor de inzet."
                        )
                        return

            await _verbruik_ranked_poging(session, uitdager)
            await _verbruik_ranked_poging(session, tegenstander_speler)
            for pet in [*eigen_team, *tegenstander_team]:
                pet_db = await session.get(Huisdier, pet.id)
                pet_db.energie = max(0, pet_db.energie - random.randint(ENERGIE_KOST_MIN, ENERGIE_KOST_MAX))

            eigen_macht = await _team_macht_lijst(session, eigen_team)
            tegenstander_macht = await _team_macht_lijst(session, tegenstander_team)
            eigen_mmr = uitdager.mmr
            tegenstander_mmr = tegenstander_speler.mmr
            elementen_bij_soort = await soort_elementen(session)
            afbeeldingen_bij_soort = await soort_afbeeldingen(session)
            await session.commit()

        await interaction.response.edit_message(
            content=f"⚔️ Uitdaging geaccepteerd! {interaction.user.mention} kijkt toe terwijl <@{uitdaging.uitdager_id}> vecht.",
            embed=None,
            view=uitdaging,
        )

        view = VechtView(
            self.bot,
            uitdaging.uitdager_id,
            eigen_team,
            eigen_macht,
            eigen_mmr,
            f"<@{uitdaging.tegenstander_id}>",
            tegenstander_team,
            tegenstander_macht,
            tegenstander_mmr,
            interaction.guild_id,
            uitdaging.inzet_coins,
            uitdaging.inzet_item,
            uitdaging.tegenstander_id,
            [elementen_bij_soort.get(pet.soort_id) for pet in eigen_team],
            [elementen_bij_soort.get(pet.soort_id) for pet in tegenstander_team],
            [afbeeldingen_bij_soort.get(pet.soort_id) for pet in eigen_team],
            [afbeeldingen_bij_soort.get(pet.soort_id) for pet in tegenstander_team],
        )
        embed, bestand = await view._bouw_intro()
        if bestand is not None:
            bericht = await interaction.channel.send(embed=embed, view=view, file=bestand)
        else:
            bericht = await interaction.channel.send(embed=embed, view=view)
        view.message = bericht


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GevechtenCog(bot))
