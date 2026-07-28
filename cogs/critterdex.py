import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from cogs.vangen import TIER_EMOJI, TIER_KLEUREN
from db.engine import async_session
from db.models import Huisdier, PetSoort, Tier, Werkplek
from utils.elementen import emoji as element_emoji

PET_SOORTEN_PER_PAGINA = 10

TIER_KEUZES = [
    ("Alle tiers", "alle"),
    ("Common", "1"),
    ("Uncommon", "2"),
    ("Rare", "3"),
    ("Epic", "4"),
    ("Legendary", "5"),
]
ELEMENT_KEUZES = [
    ("Alle elementen", "alle"),
    ("⛰️ Grond", "grond"),
    ("🌊 Water", "water"),
    ("🌪️ Lucht", "lucht"),
    ("🔥 Vuur", "vuur"),
    ("🌀 Chaos", "chaos"),
]

# Kwalitatieve schaal voor /info, dezelfde waarden als ZEER_LAAG..HOOGSTE in
# scripts/seed.py — hier als (ondergrens, label) om een gevecht_basis/
# werk_basis-getal terug om te zetten naar leesbare tekst.
_STAT_LABELS = [
    (90, "Hoogste"), (70, "Zeer hoog"), (50, "Hoog"), (30, "Gemiddeld"), (15, "Laag"), (0, "Zeer laag"),
]


def _stat_label(waarde: float) -> str:
    waarde = float(waarde)
    for ondergrens, label in _STAT_LABELS:
        if waarde >= ondergrens:
            return label
    return _STAT_LABELS[-1][1]


class CritterdexView(discord.ui.View):
    def __init__(
        self,
        alle_soorten: list[PetSoort],
        eigenaar_id: int,
        gevangen_aantallen: dict[int, int],
        tier_namen: dict[int, str],
    ):
        super().__init__(timeout=120)
        self.alle_soorten = alle_soorten
        self.eigenaar_id = eigenaar_id
        self.gevangen_aantallen = gevangen_aantallen
        self.tier_namen = tier_namen
        self.tier_filter = "alle"
        self.element_filter = "alle"
        self.pagina = 0
        self.message: discord.Message | None = None
        self._update_knoppen()

    @property
    def gefilterd(self) -> list[PetSoort]:
        soorten = self.alle_soorten
        if self.tier_filter != "alle":
            soorten = [s for s in soorten if s.tier_id == int(self.tier_filter)]
        if self.element_filter != "alle":
            soorten = [s for s in soorten if s.element is not None and s.element.value == self.element_filter]
        return soorten

    @property
    def max_pagina(self) -> int:
        return max(0, (len(self.gefilterd) - 1) // PET_SOORTEN_PER_PAGINA)

    def _update_knoppen(self) -> None:
        self.vorige.disabled = self.pagina == 0
        self.volgende.disabled = self.pagina >= self.max_pagina

    def huidige_embed(self) -> discord.Embed:
        gefilterd = self.gefilterd
        start = self.pagina * PET_SOORTEN_PER_PAGINA
        subset = gefilterd[start : start + PET_SOORTEN_PER_PAGINA]

        embed = discord.Embed(title="📖 Critterdex", color=discord.Color.blurple())
        if not subset:
            embed.description = "Geen soorten gevonden met deze filters."
        for soort in subset:
            emoji = TIER_EMOJI.get(soort.tier_id, "⚪")
            el_emoji = element_emoji(soort.element)
            tier_naam = self.tier_namen.get(soort.tier_id, "?")
            aantal = self.gevangen_aantallen.get(soort.id, 0)
            status = f"✅ Gevangen: {aantal}x" if aantal else "❌ Nog niet gevangen"
            embed.add_field(
                name=f"{emoji} {el_emoji} {soort.naam}",
                value=f"{tier_naam} — {status}",
                inline=True,
            )
        embed.set_footer(
            text=f"Pagina {self.pagina + 1}/{self.max_pagina + 1} — {len(gefilterd)}/{len(self.alle_soorten)} soorten"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.eigenaar_id:
            await interaction.response.send_message("Dit is niet jouw Critterdex.", ephemeral=True)
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

    @discord.ui.select(
        placeholder="Filter op tier",
        options=[discord.SelectOption(label=label, value=waarde) for label, waarde in TIER_KEUZES],
        row=0,
    )
    async def tier_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        self.tier_filter = select.values[0]
        self.pagina = 0
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.select(
        placeholder="Filter op element",
        options=[discord.SelectOption(label=label, value=waarde) for label, waarde in ELEMENT_KEUZES],
        row=1,
    )
    async def element_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        self.element_filter = select.values[0]
        self.pagina = 0
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.button(label="◀ Vorige", style=discord.ButtonStyle.primary, row=2)
    async def vorige(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pagina -= 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.button(label="Volgende ▶", style=discord.ButtonStyle.primary, row=2)
    async def volgende(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.pagina += 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)


class CritterdexCog(commands.Cog):
    """Overzicht van alle pet-soorten + losse soort-lookup. Zie backlog-item
    "Critterdex" in docs/dev-status.md."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="critterdex", description="Bekijk alle pet-soorten: tier, element en of je 'm al gevangen hebt"
    )
    async def critterdex(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            alle_soorten = (
                await session.execute(select(PetSoort).order_by(PetSoort.tier_id, PetSoort.naam))
            ).scalars().all()
            rijen = (
                await session.execute(
                    select(Huisdier.soort_id, func.count())
                    .where(Huisdier.eigenaar_id == interaction.user.id)
                    .group_by(Huisdier.soort_id)
                )
            ).all()
            gevangen_aantallen = dict(rijen)
            tiers = (await session.execute(select(Tier))).scalars().all()
            tier_namen = {tier.id: tier.naam for tier in tiers}

        view = CritterdexView(alle_soorten, interaction.user.id, gevangen_aantallen, tier_namen)
        await interaction.response.send_message(embed=view.huidige_embed(), view=view, ephemeral=False)
        view.message = await interaction.original_response()

    async def _soort_naam_autocomplete(
        self, interaction: discord.Interaction, huidig: str
    ) -> list[app_commands.Choice[str]]:
        async with async_session() as session:
            namen = (await session.execute(select(PetSoort.naam))).scalars().all()
        huidig = huidig.lower()
        return [app_commands.Choice(name=naam, value=naam) for naam in namen if huidig in naam.lower()][:25]

    @app_commands.command(name="info", description="Bekijk gevecht/werk-stats en info over een pet-soort")
    @app_commands.describe(soort="Naam van de pet-soort")
    @app_commands.autocomplete(soort=_soort_naam_autocomplete)
    async def info(self, interaction: discord.Interaction, soort: str) -> None:
        async with async_session() as session:
            soort_obj = await session.scalar(select(PetSoort).where(PetSoort.naam == soort))
            if soort_obj is None:
                await interaction.response.send_message(f"Onbekende pet-soort: **{soort}**.", ephemeral=True)
                return

            tier = await session.get(Tier, soort_obj.tier_id)
            werkplek = (
                await session.get(Werkplek, soort_obj.werkplek_voorkeur_id)
                if soort_obj.werkplek_voorkeur_id
                else None
            )
            aantal_gevangen = await session.scalar(
                select(func.count())
                .select_from(Huisdier)
                .where(Huisdier.eigenaar_id == interaction.user.id, Huisdier.soort_id == soort_obj.id)
            )

        embed = discord.Embed(
            title=f"{TIER_EMOJI.get(soort_obj.tier_id, '⚪')} {element_emoji(soort_obj.element)} {soort_obj.naam}",
            color=TIER_KLEUREN.get(soort_obj.tier_id, discord.Color.blurple()),
        )
        embed.add_field(name="Tier", value=tier.naam, inline=True)
        embed.add_field(name="Gevecht", value=_stat_label(soort_obj.gevecht_basis), inline=True)
        embed.add_field(name="Werk", value=_stat_label(soort_obj.werk_basis), inline=True)
        embed.add_field(name="Werkplek-voorkeur", value=werkplek.type if werkplek else "Geen", inline=True)
        embed.add_field(
            name="Zelf gevangen",
            value=f"✅ {aantal_gevangen}x" if aantal_gevangen else "❌ Nog niet gevangen",
            inline=True,
        )
        if soort_obj.beschrijving:
            embed.add_field(name="Beschrijving", value=soort_obj.beschrijving, inline=False)
        if soort_obj.afbeelding_url:
            embed.set_thumbnail(url=soort_obj.afbeelding_url)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CritterdexCog(bot))
