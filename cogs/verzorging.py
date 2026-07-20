from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.werk import WERK_CYCLI, _nu
from db.engine import async_session
from db.models import Huisdier, PetStatus

PETS_PER_PAGINA = 10

STATUS_LABELS = {
    PetStatus.rust: "😴 Rust",
    PetStatus.team: "⚔️ In team",
}

SORTEER_OPTIES = {
    "id": "ID",
    "level": "Level",
    "naam": "Naam",
    "werk": "Werkstatus",
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
    return (await session.execute(stmt)).scalars().all()


def _werk_status(pet: Huisdier) -> str:
    cyclus_info = WERK_CYCLI[pet.werk_cyclus]
    resterend = timedelta(hours=cyclus_info.duur_uren) - (_nu() - pet.werk_gestart_op)
    if resterend <= timedelta(0):
        return "👷 Klaar! Gebruik `/werk` om op te halen"
    uren = resterend.total_seconds() / 3600
    return f"👷 Aan het werk, nog {uren:.1f} uur"


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
            knop.style = (
                discord.ButtonStyle.primary if waarde == self.sortering else discord.ButtonStyle.secondary
            )

    def huidige_embed(self) -> discord.Embed:
        start = self.pagina * PETS_PER_PAGINA
        subset = self.pets[start : start + PETS_PER_PAGINA]

        embed = discord.Embed(title="Jouw pets", color=discord.Color.blurple())
        for pet in subset:
            status = _werk_status(pet) if pet.status == PetStatus.werkplek else STATUS_LABELS[pet.status]
            embed.add_field(name=f"#{pet.id} {pet.naam} (lvl {pet.level})", value=status, inline=False)
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

    @discord.ui.button(label="◀ Vorige", style=discord.ButtonStyle.secondary, row=0)
    async def vorige(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pagina -= 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.button(label="Volgende ▶", style=discord.ButtonStyle.secondary, row=0)
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

    @discord.ui.button(label="Level", style=discord.ButtonStyle.secondary, row=1, custom_id="sorteer_level")
    async def sorteer_level(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "level")

    @discord.ui.button(label="Naam", style=discord.ButtonStyle.secondary, row=1, custom_id="sorteer_naam")
    async def sorteer_naam(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "naam")

    @discord.ui.button(label="Werkstatus", style=discord.ButtonStyle.secondary, row=1, custom_id="sorteer_werk")
    async def sorteer_werk(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "werk")


class VerzorgingCog(commands.Cog):
    """Voeding, stats en shop-items voor huisdieren. Zie projectbrief sectie 5 en 6."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="verzorg", description="Bekijk of verzorg de stats van een pet")
    @app_commands.describe(pet_id="Het ID van je pet")
    async def verzorg(self, interaction: discord.Interaction, pet_id: int) -> None:
        await interaction.response.send_message(
            f"Verzorgingssysteem voor pet #{pet_id} is nog niet geïmplementeerd.", ephemeral=True
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
