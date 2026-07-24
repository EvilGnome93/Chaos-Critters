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


class TradingCog(commands.Cog):
    """Ruilen tussen spelers. Zie projectbrief sectie 11."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _item_autocomplete(
        self, interaction: discord.Interaction, huidig: str
    ) -> list[app_commands.Choice[str]]:
        async with async_session() as session:
            namen = (await session.execute(select(Item.naam))).scalars().all()
        huidig = huidig.lower()
        return [app_commands.Choice(name=naam, value=naam) for naam in namen if huidig in naam.lower()][:25]

    @app_commands.command(name="trade", description="Stel een ruil voor aan een andere speler")
    @app_commands.describe(
        speler="De speler waarmee je wilt ruilen",
        geef_item="Item dat jij aanbiedt (niet te combineren met geef_pet_id)",
        geef_aantal="Aantal van het item dat jij aanbiedt (standaard 1)",
        geef_pet_id="Jouw pet-nummer dat jij aanbiedt (niet te combineren met geef_item)",
        geef_coins="Chaos Coins die jij aanbiedt (optioneel)",
        vraag_item="Item dat je terugvraagt (niet te combineren met vraag_pet_id)",
        vraag_aantal="Aantal van het item dat je terugvraagt (standaard 1)",
        vraag_pet_id="Pet-nummer (van de ander) dat je terugvraagt (niet te combineren met vraag_item)",
        vraag_coins="Chaos Coins die je terugvraagt (optioneel)",
    )
    @app_commands.autocomplete(geef_item=_item_autocomplete, vraag_item=_item_autocomplete)
    async def trade(
        self,
        interaction: discord.Interaction,
        speler: discord.Member,
        geef_item: str | None = None,
        geef_aantal: int = 1,
        geef_pet_id: int | None = None,
        geef_coins: int | None = None,
        vraag_item: str | None = None,
        vraag_aantal: int = 1,
        vraag_pet_id: int | None = None,
        vraag_coins: int | None = None,
    ) -> None:
        if speler.id == interaction.user.id:
            await interaction.response.send_message("Je kan niet met jezelf ruilen.", ephemeral=True)
            return
        if speler.bot:
            await interaction.response.send_message("Je kan niet met een bot ruilen.", ephemeral=True)
            return
        if geef_item and geef_pet_id is not None:
            await interaction.response.send_message(
                "Kies óf een item óf een pet om aan te bieden, niet allebei.", ephemeral=True
            )
            return
        if vraag_item and vraag_pet_id is not None:
            await interaction.response.send_message(
                "Kies óf een item óf een pet om terug te vragen, niet allebei.", ephemeral=True
            )
            return

        geef: TradeKant = (geef_item, geef_aantal, geef_pet_id, geef_coins or 0)
        vraag: TradeKant = (vraag_item, vraag_aantal, vraag_pet_id, vraag_coins or 0)

        if geef[0] is None and geef[2] is None and not geef[3]:
            await interaction.response.send_message(
                "Je moet minstens iets aanbieden (item, pet, en/of Chaos Coins).", ephemeral=True
            )
            return
        if vraag[0] is None and vraag[2] is None and not vraag[3]:
            await interaction.response.send_message(
                "Je moet minstens iets terugvragen (item, pet, en/of Chaos Coins).", ephemeral=True
            )
            return

        async with async_session() as session:
            if await session.get(Speler, interaction.user.id) is None:
                session.add(Speler(discord_id=interaction.user.id))
                await session.commit()

            probleem = await _bezit_kant(session, interaction.user.id, geef)
            if probleem is not None:
                await interaction.response.send_message(f"❌ {probleem}", ephemeral=True)
                return

        view = TradeVoorstelView(self, interaction.user.id, speler.id, geef, vraag, interaction.guild_id)
        embed = discord.Embed(
            title="🔄 Ruilvoorstel",
            description=(
                f"{interaction.user.mention} stelt een ruil voor aan {speler.mention}.\n\n"
                f"{interaction.user.mention} geeft: {_kant_tekst(geef)}\n"
                f"{speler.mention} geeft: {_kant_tekst(vraag)}"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(content=speler.mention, embed=embed, view=view)
        view.message = await interaction.original_response()
        await send_log(
            self.bot, interaction.guild_id, "trade",
            fmt_log(
                "🟡", "trade",
                f"{interaction.user.mention} stelde een ruil voor aan {speler.mention}: "
                f"geeft {_kant_tekst(geef)}, vraagt {_kant_tekst(vraag)}",
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TradingCog(bot))
