import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.vangen import TIER_KLEUREN
from cogs.werk import WERK_CYCLI, _format_duur, _nu, _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, ItemType, PetStatus, Speler
from utils.leveling import MAX_LEVEL, xp_voor_volgend_level
from utils.stats import SLAAP_COOLDOWN_UUR, SLAAP_HONGER_KOST, sync_stats


def _level_status(pet: Huisdier) -> str:
    if pet.level >= MAX_LEVEL:
        return f"Level {pet.level} (max)"
    return f"Level {pet.level} (XP: {pet.xp}/{xp_voor_volgend_level(pet.level)})"

PETS_PER_PAGINA = 10

SHOP_CATEGORIE_LABELS = {
    ItemType.voeding: "🍖 Voeding",
    ItemType.boost: "✨ Boosts",
    ItemType.overig: "📦 Overig",
}

ITEM_CATEGORIE_LABELS = {
    ItemType.voeding: "🍖 Voeding",
    ItemType.grondstof: "🌾 Grondstoffen",
    ItemType.materiaal: "🔧 Materialen",
    ItemType.boost: "✨ Boosts",
    ItemType.overig: "📦 Overig",
}

# Directe voedingsitems die /verzorg kan gebruiken (honger-effect). Energie
# komt voortaan alleen uit passief herstel in rust (utils/stats.py) of /slaap.
# Overige "overig"-items (voerbakken, zelfreinigend systeem) zijn passieve
# aankopen voor de shop-stap en horen hier nog niet bij.
_HONGER_HERSTEL = {
    "Basis brokjes": 15,
    "Graanvrije premium voeding": 40,
}
_VOLLEDIG_HERSTEL = {"Vers vlees/vis"}
_MYSTERIE_VOEDSEL = "Mysterie voedselzak"

VOEDING_ITEMS = [*_HONGER_HERSTEL.keys(), *_VOLLEDIG_HERSTEL, _MYSTERIE_VOEDSEL]


def _toepassen_voeding(huisdier: Huisdier, item_naam: str) -> str:
    """Past het effect van een voedingsitem toe op de pet, geeft de gebruikte naam terug
    (relevant bij de Mysterie voedselzak, die een willekeurig item simuleert)."""
    if item_naam == _MYSTERIE_VOEDSEL:
        item_naam = random.choice([*_HONGER_HERSTEL.keys(), *_VOLLEDIG_HERSTEL])

    if item_naam in _VOLLEDIG_HERSTEL:
        huisdier.honger = 100
    else:
        huisdier.honger = min(100, huisdier.honger + _HONGER_HERSTEL[item_naam])
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
    "honger": "Honger",
    "energie": "Energie",
}

SORTEER_LABELS = {
    "sorteer_id": "ID",
    "sorteer_level": "Level",
    "sorteer_naam": "Naam",
    "sorteer_werk": "Werkstatus",
    "sorteer_honger": "Honger",
    "sorteer_energie": "Energie",
}


def _sorteer(pets: list[Huisdier], sortering: str) -> list[Huisdier]:
    if sortering == "level":
        return sorted(pets, key=lambda p: (-p.level, p.volgnummer))
    if sortering == "naam":
        return sorted(pets, key=lambda p: p.naam.lower())
    if sortering == "werk":
        return sorted(pets, key=lambda p: (p.status != PetStatus.werkplek, p.volgnummer))
    if sortering in ("honger", "energie"):
        # Laagst (meest urgent te verzorgen) eerst.
        return sorted(pets, key=lambda p: (getattr(p, sortering), p.volgnummer))
    return sorted(pets, key=lambda p: p.volgnummer)


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
        knoppen = (
            self.sorteer_id,
            self.sorteer_level,
            self.sorteer_naam,
            self.sorteer_werk,
            self.sorteer_honger,
            self.sorteer_energie,
        )
        for knop in knoppen:
            waarde = knop.custom_id.removeprefix("sorteer_")
            basis = SORTEER_LABELS[knop.custom_id]
            knop.label = f"✅ {basis}" if waarde == self.sortering else basis

    def huidige_embed(self) -> discord.Embed:
        start = self.pagina * PETS_PER_PAGINA
        subset = self.pets[start : start + PETS_PER_PAGINA]

        hoogste_tier = max((pet.tier_id for pet in subset), default=1)
        embed = discord.Embed(title="🐾 Jouw pets", color=TIER_KLEUREN.get(hoogste_tier, discord.Color.blurple()))
        for i, pet in enumerate(subset):
            status = _werk_status(pet) if pet.status == PetStatus.werkplek else STATUS_LABELS[pet.status]
            stats = f"🍖 {pet.honger} ⚡ {pet.energie}"
            emoji = TIER_EMOJI.get(pet.tier_id, "⚪")
            embed.add_field(
                name=f"{emoji} #{pet.volgnummer} {pet.naam} (lvl {pet.level})",
                value=f"{_level_status(pet)}\n{status}\n{stats}",
                inline=False,
            )
            if i < len(subset) - 1:
                embed.add_field(name="​", value="─────────", inline=False)
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

    @discord.ui.button(label="Honger", style=discord.ButtonStyle.secondary, row=2, custom_id="sorteer_honger")
    async def sorteer_honger(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "honger")

    @discord.ui.button(label="Energie", style=discord.ButtonStyle.secondary, row=2, custom_id="sorteer_energie")
    async def sorteer_energie(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._wissel_sortering(interaction, "energie")


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
            huisdier = await session.scalar(
                select(Huisdier).where(
                    Huisdier.eigenaar_id == interaction.user.id, Huisdier.volgnummer == pet_id
                )
            )
            if huisdier is None:
                await interaction.response.send_message("Je hebt geen pet met dat ID.", ephemeral=True)
                return

            sync_stats(huisdier)

            if item is None:
                await session.commit()
                await interaction.response.send_message(
                    f"**{huisdier.naam}** — {_level_status(huisdier)}\n"
                    f"🍖 Honger: {huisdier.honger}/100, "
                    f"⚡ Energie: {huisdier.energie}/100",
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
                    f"Je hebt geen **{item.value}** in je inventaris. Koop het via `/shop`.", ephemeral=True
                )
                return

            inventaris_item.aantal -= 1
            gebruikt_item = _toepassen_voeding(huisdier, item.value)
            await session.commit()

            extra = f" (bleek **{gebruikt_item}**)" if item.value == _MYSTERIE_VOEDSEL else ""
            await interaction.response.send_message(
                f"🍽️ **{huisdier.naam}** kreeg **{item.value}**{extra}. Honger is nu {huisdier.honger}/100.",
                ephemeral=True,
            )

    @app_commands.command(
        name="slaap", description="Laat een pet direct volledig uitrusten (kost honger, max 1x per dag per pet)"
    )
    @app_commands.describe(pet_id="Het ID van je pet")
    async def slaap(self, interaction: discord.Interaction, pet_id: int) -> None:
        async with async_session() as session:
            huisdier = await session.scalar(
                select(Huisdier).where(
                    Huisdier.eigenaar_id == interaction.user.id, Huisdier.volgnummer == pet_id
                )
            )
            if huisdier is None:
                await interaction.response.send_message("Je hebt geen pet met dat ID.", ephemeral=True)
                return

            sync_stats(huisdier)

            if huisdier.laatste_slaap_op is not None:
                verstreken = _nu() - huisdier.laatste_slaap_op
                resterend = timedelta(hours=SLAAP_COOLDOWN_UUR) - verstreken
                if resterend > timedelta(0):
                    await session.commit()
                    await interaction.response.send_message(
                        f"**{huisdier.naam}** heeft al geslapen. Nog {_format_duur(resterend.total_seconds() / 3600)} "
                        "tot de volgende keer.",
                        ephemeral=True,
                    )
                    return

            if huisdier.honger <= 0:
                await session.commit()
                await interaction.response.send_message(
                    f"**{huisdier.naam}** heeft te veel honger om te kunnen slapen. Verzorg de pet eerst met `/verzorg`.",
                    ephemeral=True,
                )
                return

            huisdier.energie = 100
            huisdier.honger = max(0, huisdier.honger - SLAAP_HONGER_KOST)
            huisdier.laatste_slaap_op = _nu()
            await session.commit()

            await interaction.response.send_message(
                f"💤 **{huisdier.naam}** heeft goed geslapen! Energie is nu 100/100, "
                f"honger is nu {huisdier.honger}/100.",
                ephemeral=True,
            )

    async def _shop_item_autocomplete(
        self, interaction: discord.Interaction, huidig: str
    ) -> list[app_commands.Choice[str]]:
        async with async_session() as session:
            namen = (
                await session.execute(select(Item.naam).where(Item.prijs > 0))
            ).scalars().all()
        huidig = huidig.lower()
        return [app_commands.Choice(name=naam, value=naam) for naam in namen if huidig in naam.lower()][:25]

    @app_commands.command(name="shop", description="Bekijk de shop, of koop een item met Chaos Coins")
    @app_commands.describe(
        item="Item om te kopen (optioneel, laat leeg om de shop te bekijken)",
        aantal="Hoeveel stuks (standaard 1)",
    )
    @app_commands.autocomplete(item=_shop_item_autocomplete)
    async def shop(
        self, interaction: discord.Interaction, item: str | None = None, aantal: int = 1
    ) -> None:
        async with async_session() as session:
            if item is None:
                items = (
                    await session.execute(
                        select(Item).where(Item.prijs > 0).order_by(Item.type, Item.naam)
                    )
                ).scalars().all()

                embed = discord.Embed(title="🛒 Shop", color=discord.Color.gold())
                for categorie, label in SHOP_CATEGORIE_LABELS.items():
                    subset = [i for i in items if i.type == categorie]
                    if not subset:
                        continue
                    waarde = "\n".join(f"**{i.naam}** — {i.prijs} Chaos Coins\n{i.beschrijving}" for i in subset)
                    embed.add_field(name=label, value=waarde, inline=False)
                embed.set_footer(text="Koop met /shop item:<naam> aantal:<n>")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            if aantal < 1:
                await interaction.response.send_message("`aantal` moet minstens 1 zijn.", ephemeral=True)
                return

            item_obj = await session.scalar(select(Item).where(Item.naam == item, Item.prijs > 0))
            if item_obj is None:
                await interaction.response.send_message(f"Onbekend shop-item: **{item}**.", ephemeral=True)
                return

            speler = await session.get(Speler, interaction.user.id)
            if speler is None:
                speler = Speler(discord_id=interaction.user.id, currency=0)
                session.add(speler)

            kosten = item_obj.prijs * aantal
            if speler.currency < kosten:
                await interaction.response.send_message(
                    f"Je hebt niet genoeg Chaos Coins. **{item}** x{aantal} kost {kosten}, "
                    f"je hebt {speler.currency}.",
                    ephemeral=True,
                )
                return

            speler.currency -= kosten
            await _voeg_toe_aan_inventaris(session, interaction.user.id, item_obj.id, aantal)
            await session.commit()

            await interaction.response.send_message(
                f"✅ Gekocht: {aantal}x **{item}** voor {kosten} Chaos Coins. "
                f"Saldo: {speler.currency} Chaos Coins.",
                ephemeral=True,
            )

    @app_commands.command(name="items", description="Bekijk je inventaris")
    async def items(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            rijen = (
                await session.execute(
                    select(InventarisItem, Item)
                    .join(Item, InventarisItem.item_id == Item.id)
                    .where(InventarisItem.speler_id == interaction.user.id, InventarisItem.aantal > 0)
                )
            ).all()

        if not rijen:
            await interaction.response.send_message("Je inventaris is leeg.", ephemeral=True)
            return

        aantallen = {item.id: inv.aantal for inv, item in rijen}
        embed = discord.Embed(title="🎒 Jouw inventaris", color=discord.Color.blurple())
        for categorie, label in ITEM_CATEGORIE_LABELS.items():
            subset = sorted(
                (item for _, item in rijen if item.type == categorie), key=lambda i: i.naam
            )
            if not subset:
                continue
            waarde = "\n".join(f"**{item.naam}** x{aantallen[item.id]}" for item in subset)
            embed.add_field(name=label, value=waarde, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

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
