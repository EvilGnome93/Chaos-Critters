"""Pets vrijlaten voor Chaos Coins (+ kleine kans op een bonus-item).
Backlog-item 1, zie docs/dev-status.md."""

import random

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.werk import _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Huisdier, Item, ItemType, PetSoort, PetStatus, Speler, Tier, Werkplek
from utils.discord_log import fmt_log, send_log

RELEASE_BASIS_COINS = 15
BONUS_ITEM_KANS = 0.15


def _release_beloning(tier: Tier, level: int) -> int:
    """Zelfde groeipatroon als pet_power (utils/gevechten.py:pet_power):
    tier_multiplier x (1 + level x 0,05), zodat hogere tier/level pets ook
    hier meer waard zijn."""
    return round(RELEASE_BASIS_COINS * float(tier.stat_multiplier) * (1 + level * 0.05))


async def _bonus_item_voor(session, pet: Huisdier) -> Item | None:
    """Kleine kans op een grondstof terug: bij voorkeur de grondstof van de
    eigen werkplek-voorkeur, anders een willekeurige grondstof."""
    if random.random() >= BONUS_ITEM_KANS:
        return None

    soort = await session.get(PetSoort, pet.soort_id)
    werkplek = await session.get(Werkplek, soort.werkplek_voorkeur_id) if soort.werkplek_voorkeur_id else None
    if werkplek is not None and werkplek.opbrengst_item_id is not None:
        return await session.get(Item, werkplek.opbrengst_item_id)

    grondstoffen = (await session.execute(select(Item).where(Item.type == ItemType.grondstof))).scalars().all()
    return random.choice(grondstoffen) if grondstoffen else None


class ReleaseBevestigView(discord.ui.View):
    def __init__(self, cog: "ReleaseCog", speler_id: int, pet_id: int, guild_id: int | None):
        super().__init__(timeout=60)
        self.cog = cog
        self.speler_id = speler_id
        self.pet_id = pet_id
        self.guild_id = guild_id
        self.message: discord.Message | None = None
        # De knoppen staan pas écht uit zodra edit_message() geland is, dus
        # tot die tijd kan een dubbelklik een tweede vrijlating starten — die
        # zou de pet nog zien (andere sessie) en nogmaals coins uitkeren.
        self._verwerkt = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.speler_id:
            await interaction.response.send_message("Dit is niet jouw pet om vrij te laten.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🕊️ Bevestig vrijlaten", style=discord.ButtonStyle.danger)
    async def bevestigen(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._verwerkt:
            await interaction.response.send_message("Deze pet is al vrijgelaten.", ephemeral=True)
            return
        self._verwerkt = True
        for item in self.children:
            item.disabled = True

        async with async_session() as session:
            pet = await session.scalar(
                select(Huisdier).where(Huisdier.eigenaar_id == self.speler_id, Huisdier.volgnummer == self.pet_id)
            )
            if pet is None:
                await interaction.response.edit_message(
                    content=f"❌ Pet #{self.pet_id} bestaat niet (meer).", embed=None, view=self
                )
                return
            if pet.status == PetStatus.werkplek:
                await interaction.response.edit_message(
                    content=f"❌ Pet #{self.pet_id} is aan het werk en kan niet vrijgelaten worden.",
                    embed=None, view=self,
                )
                return

            tier = await session.get(Tier, pet.tier_id)
            coins = _release_beloning(tier, pet.level)
            naam = pet.naam
            bonus_item = await _bonus_item_voor(session, pet)

            speler = await session.get(Speler, self.speler_id)
            speler.currency += coins
            if bonus_item is not None:
                await _voeg_toe_aan_inventaris(session, self.speler_id, bonus_item.id, 1)

            await session.delete(pet)
            await session.commit()

        beschrijving = f"🕊️ **{naam}** (pet #{self.pet_id}) is vrijgelaten.\n💰 +{coins} Chaos Coins"
        if bonus_item is not None:
            beschrijving += f"\n📦 Bonus: 1x {bonus_item.naam}"

        embed = discord.Embed(title="Pet vrijgelaten", description=beschrijving, color=discord.Color.green())
        await interaction.response.edit_message(content=None, embed=embed, view=self)
        await send_log(
            self.cog.bot, self.guild_id, "vangst",
            fmt_log(
                "🟢", "release",
                f"<@{self.speler_id}> liet **{naam}** (pet #{self.pet_id}) vrij voor {coins} Chaos Coins"
                + (f" + 1x {bonus_item.naam}" if bonus_item is not None else ""),
            ),
        )

    @discord.ui.button(label="❌ Annuleren", style=discord.ButtonStyle.secondary)
    async def annuleren(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Vrijlaten geannuleerd.", embed=None, view=self)

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(content="⌛ Vrijlaten niet bevestigd, verlopen.", view=self)
        except discord.HTTPException:
            pass


class ReleaseCog(commands.Cog):
    """`/release`. Zie projectbrief en docs/dev-status.md backlog-item 1."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="release", description="Laat een pet vrij in ruil voor Chaos Coins")
    @app_commands.describe(pet_id="Het nummer van de pet die je wilt vrijlaten (zie /lijst)")
    async def release(self, interaction: discord.Interaction, pet_id: int) -> None:
        async with async_session() as session:
            pet = await session.scalar(
                select(Huisdier).where(Huisdier.eigenaar_id == interaction.user.id, Huisdier.volgnummer == pet_id)
            )
            if pet is None:
                await interaction.response.send_message(f"Je hebt geen pet #{pet_id}.", ephemeral=True)
                return
            if pet.status == PetStatus.werkplek:
                await interaction.response.send_message(
                    f"Pet #{pet_id} is aan het werk. Haal eerst de opbrengst op met `/werk {pet_id}` voor je 'm vrijlaat.",
                    ephemeral=True,
                )
                return

            tier = await session.get(Tier, pet.tier_id)
            geschatte_coins = _release_beloning(tier, pet.level)
            naam = pet.naam

        view = ReleaseBevestigView(self, interaction.user.id, pet_id, interaction.guild_id)
        embed = discord.Embed(
            title="🕊️ Weet je het zeker?",
            description=(
                f"Je staat op het punt om **{naam}** (pet #{pet_id}) vrij te laten.\n"
                f"Geschatte beloning: **~{geschatte_coins} Chaos Coins** "
                f"(+ kleine kans op een bonus-item).\n\n"
                "**Dit kan niet ongedaan gemaakt worden.**"
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReleaseCog(bot))
