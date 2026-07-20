import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from db.engine import async_session
from db.models import Huisdier, PetStatus

PETS_PER_PAGINA = 10

STATUS_LABELS = {
    PetStatus.rust: "😴 Rust",
    PetStatus.werkplek: "👷 Aan het werk",
    PetStatus.team: "⚔️ In team",
}


async def _haal_pets_op(session, speler_id: int, sortering: str) -> list[Huisdier]:
    stmt = select(Huisdier).where(Huisdier.eigenaar_id == speler_id)
    if sortering == "level":
        stmt = stmt.order_by(Huisdier.level.desc(), Huisdier.id)
    elif sortering == "naam":
        stmt = stmt.order_by(Huisdier.naam)
    elif sortering == "werk":
        stmt = stmt.order_by((Huisdier.status == PetStatus.werkplek).desc(), Huisdier.id)
    else:
        stmt = stmt.order_by(Huisdier.id)
    return (await session.execute(stmt)).scalars().all()


class PetLijstView(discord.ui.View):
    def __init__(self, pets: list[Huisdier], eigenaar_id: int):
        super().__init__(timeout=120)
        self.pets = pets
        self.eigenaar_id = eigenaar_id
        self.pagina = 0
        self.max_pagina = max(0, (len(pets) - 1) // PETS_PER_PAGINA)
        self.message: discord.Message | None = None
        self._update_knoppen()

    def _update_knoppen(self) -> None:
        self.vorige.disabled = self.pagina == 0
        self.volgende.disabled = self.pagina >= self.max_pagina

    def huidige_embed(self) -> discord.Embed:
        start = self.pagina * PETS_PER_PAGINA
        subset = self.pets[start : start + PETS_PER_PAGINA]

        embed = discord.Embed(title="Jouw pets", color=discord.Color.blurple())
        for pet in subset:
            embed.add_field(
                name=f"#{pet.id} {pet.naam} (lvl {pet.level})",
                value=STATUS_LABELS[pet.status],
                inline=False,
            )
        embed.set_footer(text=f"Pagina {self.pagina + 1}/{self.max_pagina + 1} — {len(self.pets)} pets totaal")
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

    @discord.ui.button(label="◀ Vorige", style=discord.ButtonStyle.secondary)
    async def vorige(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pagina -= 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.button(label="Volgende ▶", style=discord.ButtonStyle.secondary)
    async def volgende(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pagina += 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)


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
    @app_commands.describe(sorteer="Hoe de lijst gesorteerd moet worden (standaard: ID)")
    @app_commands.choices(
        sorteer=[
            app_commands.Choice(name="ID", value="id"),
            app_commands.Choice(name="Level (hoog naar laag)", value="level"),
            app_commands.Choice(name="Naam (A-Z)", value="naam"),
            app_commands.Choice(name="Werkstatus (werkend eerst)", value="werk"),
        ]
    )
    async def lijst(
        self, interaction: discord.Interaction, sorteer: app_commands.Choice[str] | None = None
    ) -> None:
        sortering = sorteer.value if sorteer else "id"
        async with async_session() as session:
            pets = await _haal_pets_op(session, interaction.user.id, sortering)

        if not pets:
            await interaction.response.send_message("Je hebt nog geen pets gevangen.", ephemeral=True)
            return

        view = PetLijstView(pets, interaction.user.id)
        await interaction.response.send_message(embed=view.huidige_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VerzorgingCog(bot))
