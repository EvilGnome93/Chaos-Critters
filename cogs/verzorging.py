import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.vangen import TIER_KLEUREN
from cogs.werk import WERK_CYCLI, _format_duur, _nu
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, PetStatus
from utils.stats import sync_stats

PETS_PER_PAGINA = 10

# Directe voedingsitems die /verzorg kan gebruiken (energie-effect, brief sectie 5).
# Overige "overig"-items (voerbakken, zelfreinigend systeem) zijn passieve
# aankopen voor de shop-stap en horen hier nog niet bij.
_ENERGIE_BOOST = {
    "Basis brokjes": 15,
    "Graanvrije premium voeding": 40,
}
_VOLLEDIG_HERSTEL = {"Vers vlees/vis"}
_MYSTERIE_VOEDSEL = "Mysterie voedselzak"

VOEDING_ITEMS = [*_ENERGIE_BOOST.keys(), *_VOLLEDIG_HERSTEL, _MYSTERIE_VOEDSEL]


def _toepassen_voeding(huisdier: Huisdier, item_naam: str) -> str:
    """Past het effect van een voedingsitem toe op de pet, geeft de gebruikte naam terug
    (relevant bij de Mysterie voedselzak, die een willekeurig item simuleert)."""
    if item_naam == _MYSTERIE_VOEDSEL:
        item_naam = random.choice([*_ENERGIE_BOOST.keys(), *_VOLLEDIG_HERSTEL])

    if item_naam in _VOLLEDIG_HERSTEL:
        huisdier.energie = 100
    else:
        huisdier.energie = min(100, huisdier.energie + _ENERGIE_BOOST[item_naam])
    return item_naam


STATUS_LABELS = {
    PetStatus.rust: "😴 Rust",
    PetStatus.team: "⚔️ In team",
}

TIER_EMOJI = {1: "⚪", 3: "🔵", 5: "🟡"}

SORTEER_OPTIES = {
    "id": "ID",
    "level": "Level",
    "naam": "Naam",
    "werk": "Werkstatus",
}

SORTEER_LABELS = {
    "sorteer_id": "ID",
    "sorteer_level": "Level",
    "sorteer_naam": "Naam",
    "sorteer_werk": "Werkstatus",
}


def _sorteer(pets: list[Huisdier], sortering: str) -> list[Huisdier]:
    if sortering == "level":
        return sorted(pets, key=lambda p: (-p.level, p.id))
    if sortering == "naam":
        return sorted(pets, key=lambda p: p.naam.lower())
    if sortering == "werk":
        return sorted(pets, key=lambda p: (p.status != PetStatus.werkplek, p.id))
    return sorted(pets, key=lambda p: p.id)


async def _haal_pets_op(session, speler_id: int) -> list[Huisdier]:
    stmt = select(Huisdier).where(Huisdier.eigenaar_id == speler_id)
    pets = (await session.execute(stmt)).scalars().all()
    for pet in pets:
        sync_stats(pet)
    await session.commit()
    return pets


def _werk_status(pet: Huisdier) -> str:
    cyclus_info = WERK_CYCLI[pet.werk_cyclus]
    resterend = timedelta(hours=cyclus_info.duur_uren) - (_nu() - pet.werk_gestart_op)
    if resterend <= timedelta(0):
        return "👷 Klaar! Gebruik `/werk` om op te halen"
    return f"👷 Aan het werk, nog {_format_duur(resterend.total_seconds() / 3600)}"


class PetLijstView(discord.ui.View):
    def __init__(self, pets: list[Huisdier], eigenaar_id: int, sortering: str = "id"):
        super().__init__(timeout=120)
        self.pets = _sorteer(pets, sortering)
        self.eigenaar_id = eigenaar_id
        self.sortering = sortering
        self.pagina = 0
        self.message: discord.Message | None = None
        self._update_knoppen()

    @property
    def max_pagina(self) -> int:
        return max(0, (len(self.pets) - 1) // PETS_PER_PAGINA)

    def _update_knoppen(self) -> None:
        self.vorige.disabled = self.pagina == 0
        self.volgende.disabled = self.pagina >= self.max_pagina
        for knop in (self.sorteer_id, self.sorteer_level, self.sorteer_naam, self.sorteer_werk):
            waarde = knop.custom_id.removeprefix("sorteer_")
            basis = SORTEER_LABELS[knop.custom_id]
            knop.label = f"✅ {basis}" if waarde == self.sortering else basis

    def huidige_embed(self) -> discord.Embed:
        start = self.pagina * PETS_PER_PAGINA
        subset = self.pets[start : start + PETS_PER_PAGINA]

        hoogste_tier = max((pet.tier_id for pet in subset), default=1)
        embed = discord.Embed(title="🐾 Jouw pets", color=TIER_KLEUREN.get(hoogste_tier, discord.Color.blurple()))
        for pet in subset:
            status = _werk_status(pet) if pet.status == PetStatus.werkplek else STATUS_LABELS[pet.status]
            emoji = TIER_EMOJI.get(pet.tier_id, "⚪")
            embed.add_field(name=f"{emoji} #{pet.id} {pet.naam} (lvl {pet.level})", value=status, inline=False)
        embed.set_footer(
            text=f"Pagina {self.pagina + 1}/{self.max_pagina + 1} — {len(self.pets)} pets totaal "
            f"— sortering: {SORTEER_OPTIES[self.sortering]}"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.eigenaar_id:
            await interaction.response.send_message("Dit is niet jouw pet-lijst.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="◀ Vorige", style=discord.ButtonStyle.primary, row=0)
    async def vorige(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pagina -= 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.button(label="Volgende ▶", style=discord.ButtonStyle.primary, row=0)
    async def volgende(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pagina += 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    async def _wissel_sortering(self, interaction: discord.Interaction, sortering: str) -> None:
        self.sortering = sortering
        self.pets = _sorteer(self.pets, sortering)
        self.pagina = 0
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.button(label="ID", style=discord.ButtonStyle.primary, row=1, custom_id="sorteer_id")
    async def sorteer_id(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "id")

    @discord.ui.button(label="Level", style=discord.ButtonStyle.success, row=1, custom_id="sorteer_level")
    async def sorteer_level(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "level")

    @discord.ui.button(label="Naam", style=discord.ButtonStyle.secondary, row=1, custom_id="sorteer_naam")
    async def sorteer_naam(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "naam")

    @discord.ui.button(label="Werkstatus", style=discord.ButtonStyle.danger, row=1, custom_id="sorteer_werk")
    async def sorteer_werk(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "werk")


class VerzorgingCog(commands.Cog):
    """Voeding, stats en shop-items voor huisdieren. Zie projectbrief sectie 5 en 6."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="verzorg", description="Bekijk de stats van een pet, of voer 'm met voeding uit je inventaris")
    @app_commands.describe(
        pet_id="Het ID van je pet",
        item="Voeding om te gebruiken (optioneel, laat leeg om alleen de stats te bekijken)",
    )
    @app_commands.choices(
        item=[app_commands.Choice(name=naam, value=naam) for naam in VOEDING_ITEMS]
    )
    async def verzorg(
        self,
        interaction: discord.Interaction,
        pet_id: int,
        item: app_commands.Choice[str] | None = None,
    ) -> None:
        async with async_session() as session:
            huisdier = await session.get(Huisdier, pet_id)
            if huisdier is None or huisdier.eigenaar_id != interaction.user.id:
                await interaction.response.send_message("Je hebt geen pet met dat ID.", ephemeral=True)
                return

            sync_stats(huisdier)

            if item is None:
                await session.commit()
                await interaction.response.send_message(
                    f"**{huisdier.naam}** — 🍖 Honger: {huisdier.honger}/100, "
                    f"⚡ Energie: {huisdier.energie}/100, 😊 Blijdschap: {huisdier.blijdschap}/100",
                    ephemeral=True,
                )
                return

            item_obj = await session.scalar(select(Item).where(Item.naam == item.value))
            inventaris_item = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == interaction.user.id,
                    InventarisItem.item_id == item_obj.id,
                )
            )
            if inventaris_item is None or inventaris_item.aantal < 1:
                await interaction.response.send_message(
                    f"Je hebt geen **{item.value}** in je inventaris.", ephemeral=True
                )
                return

            inventaris_item.aantal -= 1
            gebruikt_item = _toepassen_voeding(huisdier, item.value)
            await session.commit()

            extra = f" (bleek **{gebruikt_item}**)" if item.value == _MYSTERIE_VOEDSEL else ""
            await interaction.response.send_message(
                f"🍽️ **{huisdier.naam}** kreeg **{item.value}**{extra}. Energie is nu {huisdier.energie}/100.",
                ephemeral=True,
            )

    @app_commands.command(name="lijst", description="Bekijk al je pets")
    async def lijst(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            pets = await _haal_pets_op(session, interaction.user.id)

        if not pets:
            await interaction.response.send_message("Je hebt nog geen pets gevangen.", ephemeral=True)
            return

        view = PetLijstView(pets, interaction.user.id)
        await interaction.response.send_message(embed=view.huidige_embed(), view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VerzorgingCog(bot))
