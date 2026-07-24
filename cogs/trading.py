"""Direct ruilen tussen spelers. Zie projectbrief sectie 11 (marktplaats-
verkoop is bewust geschrapt, dat wordt straks door /release afgedekt)."""

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.werk import _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, PetStatus, Speler
from utils.discord_log import fmt_log, send_log

TradeKant = tuple[str | None, int, int | None, int]
"""(item_naam, item_aantal, pet_id, coins) — item_naam en pet_id zijn onderling exclusief."""


def _kant_tekst(kant: TradeKant) -> str:
    item_naam, item_aantal, pet_id, coins = kant
    delen = []
    if item_naam:
        delen.append(f"{item_aantal}x {item_naam}")
    if pet_id is not None:
        delen.append(f"pet #{pet_id}")
    if coins:
        delen.append(f"{coins} Chaos Coins")
    return " + ".join(delen) if delen else "niets"


async def _bezit_kant(session, speler_id: int, kant: TradeKant) -> str | None:
    """Controleert of speler_id daadwerkelijk over de aangeboden kant beschikt.
    Geeft None terug bij een geldige kant, anders een foutmelding."""
    item_naam, item_aantal, pet_id, coins = kant

    if item_naam:
        item_obj = await session.scalar(select(Item).where(Item.naam == item_naam))
        if item_obj is None:
            return f"Onbekend item: **{item_naam}**."
        inv = await session.scalar(
            select(InventarisItem).where(
                InventarisItem.speler_id == speler_id, InventarisItem.item_id == item_obj.id
            )
        )
        if inv is None or inv.aantal < item_aantal:
            return f"<@{speler_id}> heeft geen {item_aantal}x **{item_naam}** (meer)."

    if pet_id is not None:
        pet = await session.scalar(
            select(Huisdier).where(Huisdier.eigenaar_id == speler_id, Huisdier.volgnummer == pet_id)
        )
        if pet is None:
            return f"<@{speler_id}> heeft geen pet #{pet_id} (meer)."
        if pet.status == PetStatus.werkplek:
            return f"Pet #{pet_id} van <@{speler_id}> is aan het werk en kan niet geruild worden."

    if coins:
        speler = await session.get(Speler, speler_id)
        if speler is None or speler.currency < coins:
            return f"<@{speler_id}> heeft niet (meer) genoeg Chaos Coins."

    return None


async def _voer_kant_uit(session, van_speler_id: int, naar_speler_id: int, kant: TradeKant) -> None:
    item_naam, item_aantal, pet_id, coins = kant

    if item_naam:
        item_obj = await session.scalar(select(Item).where(Item.naam == item_naam))
        inv = await session.scalar(
            select(InventarisItem).where(
                InventarisItem.speler_id == van_speler_id, InventarisItem.item_id == item_obj.id
            )
        )
        inv.aantal -= item_aantal
        await _voeg_toe_aan_inventaris(session, naar_speler_id, item_obj.id, item_aantal)

    if pet_id is not None:
        pet = await session.scalar(
            select(Huisdier).where(Huisdier.eigenaar_id == van_speler_id, Huisdier.volgnummer == pet_id)
        )
        nieuwe_eigenaar = await session.get(Speler, naar_speler_id)
        pet.eigenaar_id = naar_speler_id
        pet.volgnummer = nieuwe_eigenaar.volgend_pet_nummer
        nieuwe_eigenaar.volgend_pet_nummer += 1
        # Team-lidmaatschap/werkstatus van de oude eigenaar is bij de nieuwe
        # eigenaar zinloos (andere team-slots, andere werk-sessie).
        pet.status = PetStatus.rust

    if coins:
        van_speler = await session.get(Speler, van_speler_id)
        naar_speler = await session.get(Speler, naar_speler_id)
        van_speler.currency -= coins
        naar_speler.currency += coins


class TradeBevestigView(discord.ui.View):
    """Tweede, definitieve bevestiging door de voorsteller nadat de ander al
    heeft geaccepteerd — extra zekerheid tegen typefouten in het voorstel."""

    def __init__(
        self,
        cog: "TradingCog",
        voorsteller_id: int,
        ontvanger_id: int,
        geef: TradeKant,
        vraag: TradeKant,
        guild_id: int | None,
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.voorsteller_id = voorsteller_id
        self.ontvanger_id = ontvanger_id
        self.geef = geef
        self.vraag = vraag
        self.guild_id = guild_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.voorsteller_id:
            await interaction.response.send_message(
                "Alleen degene die de ruil voorstelde kan dit definitief bevestigen.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="✅ Definitief bevestigen", style=discord.ButtonStyle.success)
    async def bevestigen(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True

        async with async_session() as session:
            probleem = await _bezit_kant(session, self.voorsteller_id, self.geef)
            if probleem is None:
                probleem = await _bezit_kant(session, self.ontvanger_id, self.vraag)
            if probleem is not None:
                await interaction.response.edit_message(
                    content=f"❌ Ruil kon niet worden voltooid: {probleem}", embed=None, view=self
                )
                await send_log(
                    self.cog.bot, self.guild_id, "trade",
                    fmt_log("🔴", "trade", f"Ruil tussen <@{self.voorsteller_id}> en <@{self.ontvanger_id}> mislukte: {probleem}"),
                )
                return

            await _voer_kant_uit(session, self.voorsteller_id, self.ontvanger_id, self.geef)
            await _voer_kant_uit(session, self.ontvanger_id, self.voorsteller_id, self.vraag)
            await session.commit()

        embed = discord.Embed(
            title="✅ Ruil voltooid!",
            description=(
                f"<@{self.voorsteller_id}> gaf {_kant_tekst(self.geef)}\n"
                f"<@{self.ontvanger_id}> gaf {_kant_tekst(self.vraag)}"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=self)
        await send_log(
            self.cog.bot, self.guild_id, "trade",
            fmt_log(
                "🟢", "trade",
                f"Ruil voltooid tussen <@{self.voorsteller_id}> ({_kant_tekst(self.geef)}) en "
                f"<@{self.ontvanger_id}> ({_kant_tekst(self.vraag)})",
            ),
        )

    @discord.ui.button(label="❌ Annuleren", style=discord.ButtonStyle.danger)
    async def annuleren(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Ruil geannuleerd.", embed=None, view=self)
        await send_log(
            self.cog.bot, self.guild_id, "trade",
            fmt_log("🔴", "trade", f"<@{self.voorsteller_id}> annuleerde de ruil met <@{self.ontvanger_id}> alsnog"),
        )

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(content="⌛ Definitieve bevestiging verliep.", view=self)
        except discord.HTTPException:
            pass
        await send_log(
            self.cog.bot, self.guild_id, "trade",
            fmt_log("🔴", "trade", f"Definitieve bevestiging van <@{self.voorsteller_id}> verliep zonder reactie"),
        )


class TradeVoorstelView(discord.ui.View):
    def __init__(
        self,
        cog: "TradingCog",
        voorsteller_id: int,
        ontvanger_id: int,
        geef: TradeKant,
        vraag: TradeKant,
        guild_id: int | None,
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.voorsteller_id = voorsteller_id
        self.ontvanger_id = ontvanger_id
        self.geef = geef
        self.vraag = vraag
        self.guild_id = guild_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ontvanger_id:
            await interaction.response.send_message("Dit ruilvoorstel is niet voor jou.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Accepteren", style=discord.ButtonStyle.success)
    async def accepteren(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session() as session:
            probleem = await _bezit_kant(session, self.ontvanger_id, self.vraag)

        for item in self.children:
            item.disabled = True

        if probleem is not None:
            await interaction.response.edit_message(
                content=f"❌ Je kan dit voorstel niet accepteren: {probleem}", embed=None, view=self
            )
            await send_log(
                self.cog.bot, self.guild_id, "trade",
                fmt_log("🔴", "trade", f"<@{self.ontvanger_id}> kon ruil met <@{self.voorsteller_id}> niet accepteren: {probleem}"),
            )
            return

        bevestig_view = TradeBevestigView(
            self.cog, self.voorsteller_id, self.ontvanger_id, self.geef, self.vraag, self.guild_id
        )
        embed = discord.Embed(
            title="🤝 Wachten op definitieve bevestiging",
            description=(
                f"<@{self.ontvanger_id}> accepteerde het voorstel. "
                f"<@{self.voorsteller_id}> moet nu definitief bevestigen.\n\n"
                f"{self._samenvatting()}"
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.edit_message(content=f"<@{self.voorsteller_id}>", embed=embed, view=bevestig_view)
        bevestig_view.message = await interaction.original_response()
        await send_log(
            self.cog.bot, self.guild_id, "trade",
            fmt_log("🟢", "trade", f"<@{self.ontvanger_id}> accepteerde de ruil van <@{self.voorsteller_id}>, wacht op definitieve bevestiging"),
        )

    @discord.ui.button(label="❌ Weigeren", style=discord.ButtonStyle.danger)
    async def weigeren(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Ruilvoorstel geweigerd.", embed=None, view=self)
        await send_log(
            self.cog.bot, self.guild_id, "trade",
            fmt_log("🔴", "trade", f"<@{self.ontvanger_id}> weigerde het ruilvoorstel van <@{self.voorsteller_id}>"),
        )

    def _samenvatting(self) -> str:
        return (
            f"<@{self.voorsteller_id}> geeft: {_kant_tekst(self.geef)}\n"
            f"<@{self.ontvanger_id}> geeft: {_kant_tekst(self.vraag)}"
        )

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(content="⌛ Ruilvoorstel verlopen.", view=self)
        except discord.HTTPException:
            pass
        await send_log(
            self.cog.bot, self.guild_id, "trade",
            fmt_log("🔴", "trade", f"Ruilvoorstel van <@{self.voorsteller_id}> aan <@{self.ontvanger_id}> verliep zonder reactie"),
        )


def _parse_optie(waarde: str) -> tuple[str, str | int] | None:
    if waarde == "none":
        return None
    soort, rest = waarde.split("::", 1)
    return (soort, int(rest)) if soort == "pet" else (soort, rest)


async def _bouw_opties(session, speler_id: int) -> list[discord.SelectOption]:
    """Dropdown-opties voor wat een speler kan aanbieden/terugvragen: eigen
    (of, bij de ander, hun) items met voorraad + niet-werkende pets."""
    opties = [discord.SelectOption(label="Niets", value="none", default=True)]

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
                discord.SelectOption(label=f"{item.naam} ({r.aantal}x in bezit)"[:100], value=f"item::{item.naam}"[:100])
            )

    pets = (
        await session.execute(
            select(Huisdier).where(Huisdier.eigenaar_id == speler_id, Huisdier.status != PetStatus.werkplek)
        )
    ).scalars().all()
    for pet in pets:
        opties.append(discord.SelectOption(label=f"Pet #{pet.volgnummer} {pet.naam}"[:100], value=f"pet::{pet.volgnummer}"))

    return opties[:25]


class AantalCoinsModal(discord.ui.Modal):
    def __init__(self, view: "TradeBuilderView", kant: str):
        super().__init__(title="Aanbod aanpassen" if kant == "geef" else "Vraag aanpassen")
        self.view_ref = view
        self.kant = kant
        huidig_aantal = view.geef_aantal if kant == "geef" else view.vraag_aantal
        huidige_coins = view.geef_coins if kant == "geef" else view.vraag_coins
        self.aantal_input = discord.ui.TextInput(
            label="Aantal (alleen relevant bij een item)", default=str(huidig_aantal), required=False, max_length=5
        )
        self.coins_input = discord.ui.TextInput(
            label="Chaos Coins", default=str(huidige_coins), required=False, max_length=8
        )
        self.add_item(self.aantal_input)
        self.add_item(self.coins_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            aantal = max(1, int(self.aantal_input.value or 1))
        except ValueError:
            aantal = 1
        try:
            coins = max(0, int(self.coins_input.value or 0))
        except ValueError:
            coins = 0

        if self.kant == "geef":
            self.view_ref.geef_aantal = aantal
            self.view_ref.geef_coins = coins
        else:
            self.view_ref.vraag_aantal = aantal
            self.view_ref.vraag_coins = coins

        await interaction.response.edit_message(embed=self.view_ref._bouw_embed(), view=self.view_ref)


class TradeBuilderView(discord.ui.View):
    """Interactief paneel om een ruilvoorstel samen te stellen: dropdowns
    voor wat je aanbiedt/terugvraagt (gevuld met de eigen/andermans items en
    pets), knoppen voor aantal + Chaos Coins per kant. Alleen zichtbaar voor
    de voorsteller (ephemeral), pas bij versturen komt er een publiek bericht
    met de bestaande accept/weiger-flow."""

    def __init__(
        self,
        cog: "TradingCog",
        voorsteller_id: int,
        ontvanger_id: int,
        guild_id: int | None,
        eigen_opties: list[discord.SelectOption],
        ontvanger_opties: list[discord.SelectOption],
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.voorsteller_id = voorsteller_id
        self.ontvanger_id = ontvanger_id
        self.guild_id = guild_id
        self.message: discord.Message | None = None

        self.geef_waarde: tuple[str, str | int] | None = None
        self.geef_aantal = 1
        self.geef_coins = 0
        self.vraag_waarde: tuple[str, str | int] | None = None
        self.vraag_aantal = 1
        self.vraag_coins = 0

        self.geef_select = discord.ui.Select(placeholder="Wat bied jij aan?", options=eigen_opties, row=0)
        self.geef_select.callback = self._on_geef_select
        self.add_item(self.geef_select)

        self.vraag_select = discord.ui.Select(placeholder="Wat vraag je terug?", options=ontvanger_opties, row=1)
        self.vraag_select.callback = self._on_vraag_select
        self.add_item(self.vraag_select)

        aanbod_knop = discord.ui.Button(label="Aanbod: aantal/coins", style=discord.ButtonStyle.secondary, row=2)
        aanbod_knop.callback = self._open_geef_modal
        self.add_item(aanbod_knop)

        vraag_knop = discord.ui.Button(label="Vraag: aantal/coins", style=discord.ButtonStyle.secondary, row=2)
        vraag_knop.callback = self._open_vraag_modal
        self.add_item(vraag_knop)

        versturen_knop = discord.ui.Button(label="✅ Versturen", style=discord.ButtonStyle.success, row=3)
        versturen_knop.callback = self._versturen
        self.add_item(versturen_knop)

        annuleren_knop = discord.ui.Button(label="❌ Annuleren", style=discord.ButtonStyle.danger, row=3)
        annuleren_knop.callback = self._annuleren
        self.add_item(annuleren_knop)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.voorsteller_id:
            await interaction.response.send_message("Dit is niet jouw ruilvoorstel om samen te stellen.", ephemeral=True)
            return False
        return True

    def _kant_van(self, waarde: tuple[str, str | int] | None, aantal: int, coins: int) -> TradeKant:
        if waarde is None:
            return (None, aantal, None, coins)
        soort, val = waarde
        return (val, aantal, None, coins) if soort == "item" else (None, aantal, val, coins)

    @property
    def geef(self) -> TradeKant:
        return self._kant_van(self.geef_waarde, self.geef_aantal, self.geef_coins)

    @property
    def vraag(self) -> TradeKant:
        return self._kant_van(self.vraag_waarde, self.vraag_aantal, self.vraag_coins)

    def _bouw_embed(self) -> discord.Embed:
        return discord.Embed(
            title="🔄 Ruilvoorstel samenstellen",
            description=(
                f"Ruil met <@{self.ontvanger_id}>.\n\n"
                f"**Jij biedt:** {_kant_tekst(self.geef)}\n"
                f"**Jij vraagt:** {_kant_tekst(self.vraag)}"
            ),
            color=discord.Color.blurple(),
        )

    async def _on_geef_select(self, interaction: discord.Interaction) -> None:
        self.geef_waarde = _parse_optie(self.geef_select.values[0])
        await interaction.response.edit_message(embed=self._bouw_embed(), view=self)

    async def _on_vraag_select(self, interaction: discord.Interaction) -> None:
        self.vraag_waarde = _parse_optie(self.vraag_select.values[0])
        await interaction.response.edit_message(embed=self._bouw_embed(), view=self)

    async def _open_geef_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AantalCoinsModal(self, "geef"))

    async def _open_vraag_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AantalCoinsModal(self, "vraag"))

    async def _versturen(self, interaction: discord.Interaction) -> None:
        geef, vraag = self.geef, self.vraag
        if geef[0] is None and geef[2] is None and not geef[3]:
            await interaction.response.send_message("Je moet minstens iets aanbieden.", ephemeral=True)
            return
        if vraag[0] is None and vraag[2] is None and not vraag[3]:
            await interaction.response.send_message("Je moet minstens iets terugvragen.", ephemeral=True)
            return

        async with async_session() as session:
            probleem = await _bezit_kant(session, self.voorsteller_id, geef)
        if probleem is not None:
            await interaction.response.send_message(f"❌ {probleem}", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="✅ Voorstel verstuurd.", embed=None, view=self)

        voorstel_view = TradeVoorstelView(self.cog, self.voorsteller_id, self.ontvanger_id, geef, vraag, self.guild_id)
        embed = discord.Embed(
            title="🔄 Ruilvoorstel",
            description=(
                f"<@{self.voorsteller_id}> stelt een ruil voor aan <@{self.ontvanger_id}>.\n\n"
                f"<@{self.voorsteller_id}> geeft: {_kant_tekst(geef)}\n"
                f"<@{self.ontvanger_id}> geeft: {_kant_tekst(vraag)}"
            ),
            color=discord.Color.blurple(),
        )
        bericht = await interaction.channel.send(content=f"<@{self.ontvanger_id}>", embed=embed, view=voorstel_view)
        voorstel_view.message = bericht
        await send_log(
            self.cog.bot, self.guild_id, "trade",
            fmt_log(
                "🟡", "trade",
                f"<@{self.voorsteller_id}> stelde een ruil voor aan <@{self.ontvanger_id}>: "
                f"geeft {_kant_tekst(geef)}, vraagt {_kant_tekst(vraag)}",
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
            await self.message.edit(content="⌛ Ruilvoorstel-opbouw verlopen.", embed=None, view=self)
        except discord.HTTPException:
            pass


class TradingCog(commands.Cog):
    """Ruilen tussen spelers. Zie projectbrief sectie 11."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="trade", description="Stel een ruil voor aan een andere speler")
    @app_commands.describe(speler="De speler waarmee je wilt ruilen")
    async def trade(self, interaction: discord.Interaction, speler: discord.Member) -> None:
        if speler.id == interaction.user.id:
            await interaction.response.send_message("Je kan niet met jezelf ruilen.", ephemeral=True)
            return
        if speler.bot:
            await interaction.response.send_message("Je kan niet met een bot ruilen.", ephemeral=True)
            return

        async with async_session() as session:
            if await session.get(Speler, interaction.user.id) is None:
                session.add(Speler(discord_id=interaction.user.id))
            if await session.get(Speler, speler.id) is None:
                session.add(Speler(discord_id=speler.id))
            await session.commit()

            eigen_opties = await _bouw_opties(session, interaction.user.id)
            ontvanger_opties = await _bouw_opties(session, speler.id)

        view = TradeBuilderView(self, interaction.user.id, speler.id, interaction.guild_id, eigen_opties, ontvanger_opties)
        await interaction.response.send_message(embed=view._bouw_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TradingCog(bot))
