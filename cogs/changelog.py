"""Changelog-aankondigingen met een reviewstap, zelfde patroon als Botv3
(2026-07-30, verzoek van de gebruiker: "op de zelfde manier als Botv3").
Vervangt het oude, direct-verstuurde /tests-commando.

Flow:
1. `/changelog` (admin) opent een modal, voorgevuld met de nieuwste `## `
   entry uit CHANGELOG.md (of een placeholder als dat bestand ontbreekt/leeg
   is). De tekst mag hier nog aangepast worden.
2. Bij versturen komt het voorstel in het reviewkanaal te staan
   (`CHANGELOG_REVIEW_KANAAL_ID`, hardcoded net als bij Botv3, verzoek van de
   gebruiker: "niet met een command, programeer deze vast"), met
   Goedkeuren/Afwijzen/Bewerken-knoppen.
3. **Goedkeuren** splitst de tekst op een "### Voor admins & moderators"-kop
   (zelfde conventie als Botv3): alles ervoor gaat naar het publieke
   aankondigingskanaal (`CHANGELOG_AANKONDIGING_KANAAL_ID`, ook hardcoded;
   optionele rol-tag uit de `changelog_rol_id`-instelling), alles erna
   (inclusief die kop) gaat naar het aparte "changelog-admin"-kanaal (wél
   via `/setlog` instelbaar, want daar was geen vaste ID voor). Geen kop
   gevonden? Dan is alles publiek.
4. **Afwijzen** markeert het voorstel als afgewezen, geen berichten de deur
   uit.
5. **Bewerken** opent een nieuwe modal met de huidige tekst, en werkt het
   reviewbericht bij zonder de status te wijzigen.

Bewuste vereenvoudiging t.o.v. Botv3: geen persistente (custom_id-based)
view die een botherstart overleeft — dat past niet bij hoe de rest van deze
bot views behandelt (zie "Wat overleeft een redeploy" in dev-status.md,
alle interactieve UI is expliciet niet-persistent). Een lopende review
tijdens een redeploy moet dus opnieuw gestart worden met `/changelog`.
"""

import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from db.engine import async_session
from db.models import Instelling
from utils.checks import is_admin
from utils.discord_log import get_log_channel

# Hardcoded, zelfde patroon als Botv3 (2026-07-30, verzoek van de gebruiker:
# "niet met een command, programeer deze vast"). Werkt net als bij Botv3
# prima zolang de bot maar op één hoofdserver draait; bot.get_channel/
# fetch_channel werken op een kanaal-ID ongeacht vanuit welke server het
# commando aangeroepen wordt.
CHANGELOG_REVIEW_KANAAL_ID = 1532720331750641684
CHANGELOG_AANKONDIGING_KANAAL_ID = 1529099160526131215

CHANGELOG_PAD = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
MAX_LENGTE = 4000  # Discord's modal-TextInput-limiet
ADMIN_KOP_PATROON = re.compile(r"###\s*Voor admins\s*&\s*moderators", re.IGNORECASE)

KLEUR_IN_BEHANDELING = discord.Color.blurple()
KLEUR_GOEDGEKEURD = discord.Color.green()
KLEUR_AFGEWEZEN = discord.Color.red()


def _laatste_changelog_entry() -> str | None:
    """Pakt de bovenste (nieuwste) '## '-entry uit CHANGELOG.md, tot aan de
    volgende '## ' of het einde van het bestand. Zelfde parse-logica als
    Botv3's getLatestChangelogEntry()."""
    try:
        regels = CHANGELOG_PAD.read_text(encoding="utf-8").split("\n")
    except FileNotFoundError:
        return None

    start = next((i for i, r in enumerate(regels) if r.startswith("## ")), None)
    if start is None:
        return None

    eind = next((i for i in range(start + 1, len(regels)) if regels[i].startswith("## ")), len(regels))
    entry_regels = regels[start:eind]
    while entry_regels and entry_regels[-1].strip() in ("", "---"):
        entry_regels.pop()

    entry = "\n".join(entry_regels).strip()
    return entry or None


def split_changelog_content(content: str) -> tuple[str, str | None]:
    """(publieke_tekst, admin_tekst | None). Zelfde conventie als Botv3:
    alles vóór "### Voor admins & moderators" is voor iedereen, de rest
    (inclusief die kop) is voor het admin-kanaal."""
    match = ADMIN_KOP_PATROON.search(content)
    if not match:
        return content, None
    publiek = content[: match.start()].rstrip()
    publiek = re.sub(r"\n?-{3,}\s*$", "", publiek).strip()
    admin = content[match.start():].strip()
    return publiek, admin


def _status_embed(
    content: str, status: str = "in_behandeling", notitie: str | None = None, tag_rol: bool = True
) -> discord.Embed:
    kleur = {
        "goedgekeurd": KLEUR_GOEDGEKEURD,
        "afgewezen": KLEUR_AFGEWEZEN,
    }.get(status, KLEUR_IN_BEHANDELING)
    embed = discord.Embed(description=content, color=kleur, timestamp=discord.utils.utcnow())
    if notitie:
        embed.add_field(
            name="✅ Goedgekeurd" if status == "goedgekeurd" else "❌ Afgewezen", value=notitie, inline=False
        )
    if status == "in_behandeling":
        embed.set_footer(text="📢 Rol wordt getagd bij goedkeuring" if tag_rol else "🔕 Rol wordt niet getagd bij goedkeuring")
    return embed


async def _changelog_rol_id(session) -> int | None:
    waarde = await session.scalar(select(Instelling.waarde).where(Instelling.sleutel == "changelog_rol_id"))
    return int(waarde) if waarde and waarde.strip() else None


class ChangelogModal(discord.ui.Modal):
    def __init__(self, *, tag_rol: bool, huidig: str | None, review_message: discord.Message | None = None):
        super().__init__(title="Changelog bewerken" if review_message else "Changelog opstellen")
        self.tag_rol = tag_rol
        self.review_message = review_message
        self.tekst_input = discord.ui.TextInput(
            label="Changelog-tekst (Markdown mag)",
            style=discord.TextStyle.paragraph,
            max_length=MAX_LENGTE,
            required=True,
            default=huidig[:MAX_LENGTE] if huidig else None,
            placeholder=None if huidig else "## Titel\n\nKorte intro...\n\n**Kop**\n- punt 1\n- punt 2",
        )
        self.add_item(self.tekst_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        content = self.tekst_input.value
        embed = _status_embed(content, tag_rol=self.tag_rol)

        if self.review_message is not None:
            await self.review_message.edit(embed=embed, view=ChangelogReviewView(self.tag_rol))
            await interaction.response.send_message("✏️ Changelog bijgewerkt.", ephemeral=True)
            return

        kanaal = interaction.client.get_channel(
            CHANGELOG_REVIEW_KANAAL_ID
        ) or await interaction.client.fetch_channel(CHANGELOG_REVIEW_KANAAL_ID)
        await kanaal.send(embed=embed, view=ChangelogReviewView(self.tag_rol))
        await interaction.response.send_message(f"📋 Changelog geplaatst ter review in {kanaal.mention}.", ephemeral=True)


class ChangelogReviewView(discord.ui.View):
    """Niet-persistent (zie moduledocstring): overleeft geen botherstart,
    consistent met alle andere interactieve UI in deze bot."""

    def __init__(self, tag_rol: bool):
        super().__init__(timeout=None)
        self.tag_rol = tag_rol

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_admin(interaction):
            await interaction.response.send_message("Je hebt geen toestemming om dit te doen.", ephemeral=True)
            return False
        return True

    def _huidige_tekst(self, interaction: discord.Interaction) -> str | None:
        embeds = interaction.message.embeds
        return embeds[0].description if embeds else None

    @discord.ui.button(label="Goedkeuren", style=discord.ButtonStyle.success)
    async def goedkeuren(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        content = self._huidige_tekst(interaction)
        if content is None:
            await interaction.response.send_message("Kon de changelog-tekst niet vinden.", ephemeral=True)
            return

        publiek, admin_tekst = split_changelog_content(content)
        publieke_tekst = publiek + ("\n\n*Er zijn deze update ook wijzigingen voor admins en moderators.*" if admin_tekst else "")
        kanaal = interaction.client.get_channel(
            CHANGELOG_AANKONDIGING_KANAAL_ID
        ) or await interaction.client.fetch_channel(CHANGELOG_AANKONDIGING_KANAAL_ID)

        async with async_session() as session:
            rol_id = await _changelog_rol_id(session)

        bericht_content = f"<@&{rol_id}>" if (self.tag_rol and rol_id) else None
        await kanaal.send(content=bericht_content, embed=_status_embed(publieke_tekst))

        notitie = f"{interaction.user.mention} keurde dit goed en postte het in {kanaal.mention}"
        notitie += "." if (self.tag_rol and rol_id) or not self.tag_rol else " (rol niet getagd, geen changelog_rol_id ingesteld)."

        if admin_tekst:
            admin_kanaal_id = await get_log_channel(interaction.guild_id, "changelog-admin")
            if admin_kanaal_id is not None:
                admin_kanaal = interaction.client.get_channel(admin_kanaal_id) or await interaction.client.fetch_channel(
                    admin_kanaal_id
                )
                await admin_kanaal.send(embed=_status_embed(admin_tekst))
                notitie += f" Admin-gedeelte gepost in {admin_kanaal.mention}."
            else:
                notitie += " Admin-gedeelte NIET gepost (geen changelog-admin-kanaal ingesteld)."

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=_status_embed(content, "goedgekeurd", notitie, self.tag_rol), view=self
        )

    @discord.ui.button(label="Afwijzen", style=discord.ButtonStyle.danger)
    async def afwijzen(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        content = self._huidige_tekst(interaction) or ""
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=_status_embed(content, "afgewezen", f"Afgewezen door {interaction.user.mention}.", self.tag_rol),
            view=self,
        )

    @discord.ui.button(label="Bewerken", style=discord.ButtonStyle.secondary)
    async def bewerken(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        content = self._huidige_tekst(interaction)
        await interaction.response.send_modal(
            ChangelogModal(tag_rol=self.tag_rol, huidig=content, review_message=interaction.message)
        )


class ChangelogCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="changelog", description="Stel een changelog-aankondiging samen voor review (admin)"
    )
    @app_commands.describe(tag_rol="Moet de aankondigingsrol getagd worden bij goedkeuring? (standaard: ja)")
    @app_commands.check(is_admin)
    async def changelog(self, interaction: discord.Interaction, tag_rol: bool = True) -> None:
        huidig = _laatste_changelog_entry()
        await interaction.response.send_modal(ChangelogModal(tag_rol=tag_rol, huidig=huidig))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChangelogCog(bot))
