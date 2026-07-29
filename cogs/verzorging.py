import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from cogs.vangen import TIER_EMOJI, TIER_KLEUREN
from cogs.werk import WERK_CYCLI, _format_duur, _neem_uit_inventaris, _nu, _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import Huisdier, InventarisItem, Item, ItemType, PetSoort, PetStatus, Speler
from utils.elementen import emoji as element_emoji, soort_element_emojis
from utils.leveling import MAX_LEVEL, xp_voor_volgend_level
from utils.stats import (
    HONGER_HERSTEL_WAARDEN as _HONGER_HERSTEL,
    SLAAP_COOLDOWN_UUR,
    SLAAP_HONGER_KOST,
    VOLLEDIG_HERSTEL_ITEMS as _VOLLEDIG_HERSTEL,
    sync_stats_met_voerbak,
)


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
# _HONGER_HERSTEL/_VOLLEDIG_HERSTEL komen uit utils/stats.py (single source
# of truth, want die worden sinds 2026-07-28 ook gebruikt door het
# voerbak-auto-voer-effect in sync_stats_met_voerbak).
_MYSTERIE_VOEDSEL = "Mysterie voedselzak"

VOEDING_ITEMS = [*_HONGER_HERSTEL.keys(), *_VOLLEDIG_HERSTEL, _MYSTERIE_VOEDSEL]

# Extra grondstof-kosten bovenop de Chaos Coins-prijs, voor items die dat
# volgens hun shop-omschrijving vereisen (2026-07-27, Item-overhaul deel 1,
# verzoek van de gebruiker). Geeft elke grondstof een concreet doel, zonder
# een volledig crafting-systeem te bouwen.
#
# Herzien tijdens de Balans-audit (2026-07-28, verzoek van de gebruiker: "niet
# snel aan de OP-items komen"). Elk recept vereist nu minstens 2 verschillende
# grondstoffen uit 2 verschillende werkplekken. Hoofdgrondstoffen (gegarandeerd
# per shift: Groente/Algen/Schroot/Takken/Maanschijnkristal/Erts) zijn de
# belangrijkste knop en dus fors hoger dan vóór de audit; bonus-grondstoffen
# (Water/Sterrenstof/Fruit/Bladeren/Spijker/Edelsteen — 25%-kans per shift)
# blijven bewust klein, want die zijn door hun zeldzaamheid al traag genoeg.
# De 2 duurste "OP"-items (Slimme voerbak, Zelfreinigend systeem) hebben de
# zwaarste combinatie: allebei nu ook Schroot nodig, naast hun eigen unieke
# ingrediënt.
RECEPT_KOSTEN: dict[str, list[tuple[str, int]]] = {
    "Graanvrije premium voeding": [("Groente", 12), ("Water", 1)],
    "Vers vlees/vis": [("Algen", 15), ("Takken", 8)],
    "Mysterie voedselzak": [("Fruit", 1), ("Bladeren", 1)],
    "Naamkaartje": [("Takken", 15), ("Spijker", 1)],
    "Focus drankje": [("Bladeren", 2), ("Edelsteen", 1)],
    "Werk-elixer": [("Erts", 12), ("Spijker", 2)],
    "Extra match token": [("Maanschijnkristal", 30), ("Edelsteen", 2)],
    "Simpele voerbak": [("Water", 2), ("Fruit", 2)],
    "Slimme voerbak": [("Schroot", 40), ("Erts", 20)],
    "Zelfreinigend systeem": [("Sterrenstof", 3), ("Schroot", 20)],
}

async def _koop_item(session, speler_id: int, item_obj: Item, aantal: int) -> tuple[bool, str]:
    """Voert een aankoop uit (Chaos Coins + eventuele recept-grondstoffen uit
    RECEPT_KOSTEN). Geeft (gelukt, bericht) terug; bij gelukt=False is niets
    afgeboekt. Gedeeld tussen /shop en /craft zodat ze niet uit de pas lopen."""
    speler = await session.get(Speler, speler_id)
    if speler is None:
        speler = Speler(discord_id=speler_id, currency=0)
        session.add(speler)

    kosten = item_obj.prijs * aantal
    if speler.currency < kosten:
        return False, (
            f"Je hebt niet genoeg Chaos Coins. **{item_obj.naam}** x{aantal} kost {kosten}, "
            f"je hebt {speler.currency}."
        )

    recept = RECEPT_KOSTEN.get(item_obj.naam, [])
    grondstof_items: dict[str, Item] = {}
    for grondstof_naam, hoeveelheid in recept:
        benodigd = hoeveelheid * aantal
        grondstof_item = await session.scalar(select(Item).where(Item.naam == grondstof_naam))
        inv = await session.scalar(
            select(InventarisItem).where(
                InventarisItem.speler_id == speler_id, InventarisItem.item_id == grondstof_item.id
            )
        )
        if inv is None or inv.aantal < benodigd:
            in_bezit = inv.aantal if inv else 0
            return False, (
                f"**{item_obj.naam}** x{aantal} vereist ook {benodigd}x **{grondstof_naam}** "
                f"(je hebt {in_bezit})."
            )
        grondstof_items[grondstof_naam] = grondstof_item

    # Atomisch afboeken (zie _neem_uit_inventaris): de check hierboven kan
    # verouderd zijn als er tegelijk een ander commando van dezelfde speler
    # loopt, dus elke afboeking bevestigt zelf nog of er genoeg was.
    for grondstof_naam, hoeveelheid in recept:
        if not await _neem_uit_inventaris(
            session, speler_id, grondstof_items[grondstof_naam].id, hoeveelheid * aantal
        ):
            await session.rollback()
            return False, f"Je hebt niet meer genoeg **{grondstof_naam}** voor deze aankoop."
    speler.currency -= kosten
    await _voeg_toe_aan_inventaris(session, speler_id, item_obj.id, aantal)
    await session.commit()

    recept_tekst = (
        " + " + ", ".join(f"{hoeveelheid * aantal}x {naam}" for naam, hoeveelheid in recept)
        if recept
        else ""
    )
    return True, (
        f"✅ Gekocht: {aantal}x **{item_obj.naam}** voor {kosten} Chaos Coins{recept_tekst}. "
        f"Saldo: {speler.currency} Chaos Coins."
    )


# Koppelt de shop-itemnaam aan de interne uitrustings-waarde op Huisdier.
VOERBAK_NIVEAUS = {"Simpele voerbak": "simpel", "Slimme voerbak": "slim"}
ZELFREINIGEND_ITEM = "Zelfreinigend systeem"
UITRUSTING_ITEMS = [*VOERBAK_NIVEAUS.keys(), ZELFREINIGEND_ITEM]


_VOERBAK_NAMEN_OMGEKEERD = {v: n for n, v in VOERBAK_NIVEAUS.items()}


def _uitrusting_tekst(huisdier: Huisdier) -> str:
    delen = []
    if huisdier.voerbak_niveau:
        delen.append(_VOERBAK_NAMEN_OMGEKEERD[huisdier.voerbak_niveau])
    if huisdier.zelfreinigend_actief:
        delen.append(ZELFREINIGEND_ITEM)
    return ", ".join(delen) if delen else "geen"


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
        await sync_stats_met_voerbak(session, pet)
    await session.commit()
    return pets


def _werk_status(pet: Huisdier) -> str:
    cyclus_info = WERK_CYCLI[pet.werk_cyclus]
    resterend = timedelta(hours=cyclus_info.duur_uren) - (_nu() - pet.werk_gestart_op)
    if resterend <= timedelta(0):
        return "👷 Klaar! Gebruik `/werk` om op te halen"
    return f"👷 Aan het werk, nog {_format_duur(resterend.total_seconds() / 3600)}"


class PetLijstView(discord.ui.View):
    def __init__(self, pets: list[Huisdier], eigenaar_id: int, soort_elementen: dict[int, str], sortering: str = "id"):
        super().__init__(timeout=120)
        self.pets = _sorteer(pets, sortering)
        self.eigenaar_id = eigenaar_id
        self.soort_elementen = soort_elementen
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
            if pet.voerbak_niveau or pet.zelfreinigend_actief:
                stats += f" 🔧 {_uitrusting_tekst(pet)}"
            emoji = TIER_EMOJI.get(pet.tier_id, "⚪")
            element = self.soort_elementen.get(pet.soort_id, "❓")
            embed.add_field(
                name=f"{emoji} {element} #{pet.volgnummer} {pet.naam} (lvl {pet.level})",
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


class CraftBevestigView(discord.ui.View):
    """Bevestigingsstap voor /craft: kosten (Chaos Coins + grondstoffen) staan
    al zichtbaar in de preview-embed, hier alleen nog Bevestigen/Annuleren."""

    def __init__(self, speler_id: int, item_obj: Item, aantal: int, kan_craften: bool):
        super().__init__(timeout=60)
        self.speler_id = speler_id
        self.item_obj = item_obj
        self.aantal = aantal
        self.message: discord.Message | None = None
        self.bevestigen.disabled = not kan_craften
        # De knoppen staan pas écht uit zodra edit_message() geland is, dus
        # tot die tijd kan een dubbelklik een tweede craft starten.
        self._verwerkt = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.speler_id:
            await interaction.response.send_message("Dit is niet jouw craft-poging.", ephemeral=True)
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

    @discord.ui.button(label="Bevestigen", style=discord.ButtonStyle.success)
    async def bevestigen(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._verwerkt:
            await interaction.response.send_message("Deze craft is al verwerkt.", ephemeral=True)
            return
        self._verwerkt = True

        async with async_session() as session:
            item_obj = await session.get(Item, self.item_obj.id)
            _, bericht = await _koop_item(session, self.speler_id, item_obj, self.aantal)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=bericht, embed=None, view=self)
        self.stop()

    @discord.ui.button(label="Annuleren", style=discord.ButtonStyle.danger)
    async def annuleren(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Geannuleerd.", embed=None, view=self)
        self.stop()


class VerzorgingCog(commands.Cog):
    """Voeding, stats en shop-items voor huisdieren. Zie projectbrief sectie 5 en 6."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="verzorg", description="Bekijk de stats van een pet, of voer 'm met voeding uit je inventaris")
    @app_commands.describe(
        pet_id="Het ID van je pet",
        item="Voeding om te gebruiken (optioneel, laat leeg om alleen de stats te bekijken)",
        aantal="Hoeveel stuks in één keer geven (standaard 1)",
    )
    @app_commands.choices(
        item=[app_commands.Choice(name=naam, value=naam) for naam in VOEDING_ITEMS]
    )
    async def verzorg(
        self,
        interaction: discord.Interaction,
        pet_id: int,
        item: app_commands.Choice[str] | None = None,
        aantal: int = 1,
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

            await sync_stats_met_voerbak(session, huisdier)

            if item is None:
                soort = await session.get(PetSoort, huisdier.soort_id)
                await session.commit()
                await interaction.response.send_message(
                    f"**{huisdier.naam}** {element_emoji(soort.element if soort else None)} — {_level_status(huisdier)}\n"
                    f"🍖 Honger: {huisdier.honger}/100, "
                    f"⚡ Energie: {huisdier.energie}/100\n"
                    f"🔧 Uitrusting: {_uitrusting_tekst(huisdier)}",
                    ephemeral=True,
                )
                return

            if aantal < 1:
                await interaction.response.send_message("`aantal` moet minstens 1 zijn.", ephemeral=True)
                return

            item_obj = await session.scalar(select(Item).where(Item.naam == item.value))
            inventaris_item = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == interaction.user.id,
                    InventarisItem.item_id == item_obj.id,
                )
            )
            if inventaris_item is None or inventaris_item.aantal < aantal:
                in_bezit = inventaris_item.aantal if inventaris_item else 0
                await interaction.response.send_message(
                    f"Je hebt maar {in_bezit}x **{item.value}** (van de {aantal} gevraagd). Koop meer via `/shop`.",
                    ephemeral=True,
                )
                return

            if not await _neem_uit_inventaris(session, interaction.user.id, item_obj.id, aantal):
                await session.rollback()
                await interaction.response.send_message(
                    f"Je hebt niet meer genoeg **{item.value}**.", ephemeral=True
                )
                return
            gebruikte_items = [_toepassen_voeding(huisdier, item.value) for _ in range(aantal)]
            await session.commit()

            if item.value == _MYSTERIE_VOEDSEL:
                extra = f" (bleek: {', '.join(gebruikte_items)})"
            else:
                extra = ""
            aantal_tekst = f"{aantal}x " if aantal > 1 else ""
            await interaction.response.send_message(
                f"🍽️ **{huisdier.naam}** kreeg {aantal_tekst}**{item.value}**{extra}. Honger is nu {huisdier.honger}/100.",
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

            await sync_stats_met_voerbak(session, huisdier)

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

    @app_commands.command(
        name="uitrusten",
        description="Rust een pet uit met een voerbak/zelfreinigend systeem uit je inventaris, of koppel het af",
    )
    @app_commands.describe(
        pet_id="Het ID van je pet",
        item="Het uitrustingsitem",
        afkoppelen="Zet op True om dit item juist af te koppelen (komt terug in je inventaris)",
    )
    @app_commands.choices(
        item=[app_commands.Choice(name=naam, value=naam) for naam in UITRUSTING_ITEMS]
    )
    async def uitrusten(
        self,
        interaction: discord.Interaction,
        pet_id: int,
        item: app_commands.Choice[str],
        afkoppelen: bool = False,
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

            is_zelfreinigend = item.value == ZELFREINIGEND_ITEM
            slot_naam = "zelfreinigend systeem" if is_zelfreinigend else "voerbak"

            if afkoppelen:
                if is_zelfreinigend:
                    if not huisdier.zelfreinigend_actief:
                        await interaction.response.send_message(
                            f"**{huisdier.naam}** heeft geen {slot_naam} uitgerust.", ephemeral=True
                        )
                        return
                    huisdier.zelfreinigend_actief = False
                else:
                    if huisdier.voerbak_niveau != VOERBAK_NIVEAUS[item.value]:
                        await interaction.response.send_message(
                            f"**{huisdier.naam}** heeft geen **{item.value}** uitgerust.", ephemeral=True
                        )
                        return
                    huisdier.voerbak_niveau = None

                item_obj = await session.scalar(select(Item).where(Item.naam == item.value))
                await _voeg_toe_aan_inventaris(session, interaction.user.id, item_obj.id, 1)
                await session.commit()
                await interaction.response.send_message(
                    f"🔧 **{item.value}** afgekoppeld van **{huisdier.naam}** en teruggezet in je inventaris.",
                    ephemeral=True,
                )
                return

            if not is_zelfreinigend and huisdier.voerbak_niveau == VOERBAK_NIVEAUS[item.value]:
                await interaction.response.send_message(
                    f"**{huisdier.naam}** heeft al een **{item.value}** uitgerust.", ephemeral=True
                )
                return
            if is_zelfreinigend and huisdier.zelfreinigend_actief:
                await interaction.response.send_message(
                    f"**{huisdier.naam}** heeft al een {slot_naam} uitgerust.", ephemeral=True
                )
                return

            item_obj = await session.scalar(select(Item).where(Item.naam == item.value))
            inv = await session.scalar(
                select(InventarisItem).where(
                    InventarisItem.speler_id == interaction.user.id, InventarisItem.item_id == item_obj.id
                )
            )
            if inv is None or inv.aantal < 1:
                await interaction.response.send_message(
                    f"Je hebt geen **{item.value}** (meer) in je inventaris. Koop er een via `/shop`.",
                    ephemeral=True,
                )
                return

            # Eerst het nieuwe item afboeken: lukt dat niet (voorraad net weg
            # via een ander commando), dan is er nog niets veranderd.
            if not await _neem_uit_inventaris(session, interaction.user.id, item_obj.id, 1):
                await session.rollback()
                await interaction.response.send_message(
                    f"Je hebt geen **{item.value}** (meer) in je inventaris.", ephemeral=True
                )
                return

            wissel_tekst = ""
            if not is_zelfreinigend and huisdier.voerbak_niveau is not None:
                # Slot is al bezet door de andere voerbak — automatisch
                # omwisselen: oude teruggeven, nieuwe verbruiken.
                oude_naam = _VOERBAK_NAMEN_OMGEKEERD[huisdier.voerbak_niveau]
                oude_item = await session.scalar(select(Item).where(Item.naam == oude_naam))
                await _voeg_toe_aan_inventaris(session, interaction.user.id, oude_item.id, 1)
                wissel_tekst = f" (**{oude_naam}** kwam terug in je inventaris)"

            if is_zelfreinigend:
                huisdier.zelfreinigend_actief = True
            else:
                huisdier.voerbak_niveau = VOERBAK_NIVEAUS[item.value]
            await session.commit()

            await interaction.response.send_message(
                f"🔧 **{huisdier.naam}** is uitgerust met **{item.value}**!{wissel_tekst}",
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

            _, bericht = await _koop_item(session, interaction.user.id, item_obj, aantal)
            await interaction.response.send_message(bericht, ephemeral=True)

    async def _craft_item_autocomplete(
        self, interaction: discord.Interaction, huidig: str
    ) -> list[app_commands.Choice[str]]:
        huidig = huidig.lower()
        return [
            app_commands.Choice(name=naam, value=naam) for naam in RECEPT_KOSTEN if huidig in naam.lower()
        ][:25]

    async def _craft_overzicht_embed(self, session) -> discord.Embed:
        items_obj = (
            await session.execute(select(Item).where(Item.naam.in_(RECEPT_KOSTEN.keys())))
        ).scalars().all()
        per_naam = {i.naam: i for i in items_obj}

        embed = discord.Embed(
            title="🛠️ Craft-overzicht",
            description="Items met een grondstof-recept. Gebruik `/craft item:<naam>` voor de "
            "kosten in detail + een bevestigingsstap.",
            color=discord.Color.orange(),
        )
        for naam, recept in RECEPT_KOSTEN.items():
            recept_tekst = ", ".join(f"{hoeveelheid}x {grondstof}" for grondstof, hoeveelheid in recept)
            embed.add_field(
                name=naam, value=f"{per_naam[naam].prijs} Chaos Coins + {recept_tekst}", inline=False
            )
        return embed

    @app_commands.command(
        name="craft-lijst",
        description="(tijdelijk) Snel overzicht van alle craftbare items, zonder de rest van /craft",
    )
    async def craft_lijst(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            embed = await self._craft_overzicht_embed(session)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="craft",
        description="Bekijk of maak een item met een grondstof-recept, met alle kosten vooraf zichtbaar",
    )
    @app_commands.describe(
        item="Recept-item (optioneel, laat leeg voor het overzicht)",
        aantal="Hoeveel stuks (standaard 1)",
    )
    @app_commands.autocomplete(item=_craft_item_autocomplete)
    async def craft(
        self, interaction: discord.Interaction, item: str | None = None, aantal: int = 1
    ) -> None:
        async with async_session() as session:
            if item is None:
                embed = await self._craft_overzicht_embed(session)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            if aantal < 1:
                await interaction.response.send_message("`aantal` moet minstens 1 zijn.", ephemeral=True)
                return

            if item not in RECEPT_KOSTEN:
                await interaction.response.send_message(
                    f"**{item}** heeft geen grondstof-recept — koop 'm gewoon via `/shop`.", ephemeral=True
                )
                return

            item_obj = await session.scalar(select(Item).where(Item.naam == item))
            speler = await session.get(Speler, interaction.user.id)
            saldo = speler.currency if speler else 0
            kosten = item_obj.prijs * aantal

            regels = []
            alles_voldoende = saldo >= kosten
            for grondstof_naam, hoeveelheid in RECEPT_KOSTEN[item]:
                benodigd = hoeveelheid * aantal
                grondstof_item = await session.scalar(select(Item).where(Item.naam == grondstof_naam))
                inv = await session.scalar(
                    select(InventarisItem).where(
                        InventarisItem.speler_id == interaction.user.id,
                        InventarisItem.item_id == grondstof_item.id,
                    )
                )
                in_bezit = inv.aantal if inv else 0
                voldoende = in_bezit >= benodigd
                alles_voldoende = alles_voldoende and voldoende
                regels.append(f"{'✅' if voldoende else '❌'} {benodigd}x **{grondstof_naam}** (je hebt {in_bezit})")

            embed = discord.Embed(title=f"🛠️ Craften: {aantal}x {item}", color=discord.Color.orange())
            embed.add_field(
                name="Kosten",
                value=f"{'✅' if saldo >= kosten else '❌'} {kosten} Chaos Coins (je hebt {saldo})\n"
                + "\n".join(regels),
                inline=False,
            )
            if not alles_voldoende:
                embed.set_footer(text="Je hebt nog niet genoeg voor deze craft — Bevestigen is uitgeschakeld.")

            view = CraftBevestigView(interaction.user.id, item_obj, aantal, kan_craften=alles_voldoende)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()

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
            soort_elementen = await soort_element_emojis(session)

        if not pets:
            await interaction.response.send_message("Je hebt nog geen pets gevangen.", ephemeral=True)
            return

        view = PetLijstView(pets, interaction.user.id, soort_elementen)
        await interaction.response.send_message(embed=view.huidige_embed(), view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VerzorgingCog(bot))
