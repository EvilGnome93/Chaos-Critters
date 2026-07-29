import discord
from discord import app_commands
from discord.ext import commands

# Elk onderwerp: (titel, uitleg van de mechaniek, lijst met relevante
# commando's). Handmatig bijgehouden, net als TODO_ITEMS/TEST_COMMANDOS in
# cogs/algemeen.py — bijwerken als een mechaniek verandert. Legt uit HOE
# dingen werken (i.p.v. /commands, dat alleen command-syntax + 1 zin toont).
WIKI_ONDERWERPEN: list[tuple[str, str, list[str]]] = [
    (
        "📖 Vangen & Tiers",
        "Pets spawnen automatisch in de ingestelde spawn-kanalen (op basis van activiteit + af en toe "
        "gewoon na een tijdje). Vang de actieve spawn met `/vang` en de (deel van de) naam. Elke soort "
        "heeft een tier (zeldzaamheid): **Common** (45%), **Uncommon** (25%), **Rare** (18%), **Epic** "
        "(9%), **Legendary** (3%) kans per spawn. Een hogere tier betekent hogere basisstats "
        "(stat-multiplier van 1.0x tot 2.0x) — een Legendary is dus standaard sterker dan een Common "
        "van dezelfde genen.",
        [
            "`/vang <naam>` — vang de actieve spawn in dit kanaal",
            "`/lijst` — bekijk al je gevangen pets",
            "`/critterdex` — overzicht van alle soorten + of je 'm al hebt",
            "`/info <soort>` — details van één specifieke soort",
        ],
    ),
    (
        "🌪️ Elementen & contra's",
        "Elke pet-soort heeft een vast element: ⛰️ **Grond**, 🌊 **Water**, 🌪️ **Lucht**, 🔥 **Vuur**, "
        "of 🌀 **Chaos**. Er is een vaste contra-cirkel: **Vuur > Lucht > Grond > Water > Vuur**. Heb "
        "je in een gevechts-matchup het gunstige element tegen je tegenstander, dan krijg je **+15% "
        "macht**; heb je het ongunstige, dan **-10%**. Twee stappen verschil in de cirkel is neutraal "
        "(geen bonus/malus). **Chaos** aan een van beide kanten maakt de uitkomst willekeurig (+15%/"
        "-10%/neutraal) — onvoorspelbaar per matchup.",
        [
            "`/lijst`, `/team`, `/info` — tonen het element per pet als emoji",
            "`/vecht` — de matchup-titel toont beide elementen tegen elkaar",
        ],
    ),
    (
        "🍖 Verzorgen",
        "Honger daalt vanzelf over tijd (lazy berekend, dus je merkt het pas als je de pet weer "
        "aanraakt). Energie herstelt alleen passief terwijl een pet in **rust** staat — niet tijdens "
        "werk of in je team. Voed een pet met `/verzorg` om honger aan te vullen, of gebruik `/slaap` "
        "voor instant volle energie (kost wel honger, max 1x per dag per pet). **Voerbakken** "
        "(Simpele/Slimme, per pet uit te rusten) voeren een pet automatisch met écht voer uit je "
        "inventaris zodra dat nodig is — Simpele voerbak alleen met Basis brokjes, Slimme voerbak met "
        "je goedkoopste beschikbare voer. Geen voer meer? Dan gebeurt er niets, gewoon normaal verval. "
        "Het **Zelfreinigend systeem** laat energie ook buiten rust herstellen.",
        [
            "`/verzorg <pet_id> [item] [aantal]` — bekijk stats, of voer een pet",
            "`/slaap <pet_id>` — instant volle energie",
            "`/uitrusten <pet_id> <item> [afkoppelen]` — voerbak/Zelfreinigend systeem aan-/afkoppelen",
            "`/shop`, `/craft`, `/items` — voeding en uitrustingsitems kopen/bekijken",
        ],
    ),
    (
        "👷 Werken & grondstoffen",
        "Zet een pet aan het werk op een werkplek (Moestuin/Vijver/Werkbank/Bos/Nachtwacht/Mijnschacht) "
        "voor een gekozen shift-duur. Bij het ophalen krijg je Chaos Coins + de grondstof van die "
        "werkplek + XP, en een kleine kans op een zeldzamere bonus-grondstof. Elke werkplek heeft een "
        "**gedeelde capaciteit** over spelers heen — vol is vol, probeer het later opnieuw. Zit je in "
        "een clan, dan deel je die capaciteit alleen met je eigen clangenoten (een eigen pool per "
        "clan). Grondstoffen zijn nodig om bepaalde shop-items te maken via **recepten** (`/craft`).",
        [
            "`/werk <pet_id> [werkplek] [cyclus]` — start een shift, of haal 'm op als hij klaar is",
            "`/craft [item] [aantal]` — maak een item met een grondstof-recept, kosten vooraf zichtbaar",
        ],
    ),
    (
        "⚔️ Vechten & ranked",
        "Stel eerst een team van 3 pets samen. Een gevecht is best-of-3: per matchup kies je een "
        "tactiek (**Aggressief** = hoog risico/hoge variantie, **Gebalanceerd** = gemiddeld, "
        "**Voorzichtig** = laag risico) of je rent weg. Elementen tellen mee als bonus/malus op de "
        "macht (zie hierboven). Winnen levert MMR op (Elo-systeem) plus Chaos Coins en XP voor je "
        "pets; verliezen kost een beetje MMR en geeft de verslagen pet een tijdelijke blessure. Je hebt "
        "een beperkt aantal gratis **ranked**-pogingen per dag. Geen zin in het risico of de limiet? "
        "Kies de **vriendschappelijke modus** — altijd beschikbaar, maar zonder MMR/beloning/blessures.",
        [
            "`/team` — stel je team van 3 pets samen",
            "`/vecht [tegenstander] [modus]` — vecht tegen een simulatie of een speler",
        ],
    ),
    (
        "🔁 Traden & releasen",
        "Met `/trade` stel je een ruilvoorstel samen met een ander speler: items en/of een pet van "
        "elke kant, plus optioneel Chaos Coins. De ontvanger accepteert of weigert eerst, en daarna "
        "moet jij het nog een keer definitief bevestigen — een extra stap tegen typefouten. Wil je een "
        "pet gewoon kwijt in ruil voor wat Chaos Coins (zonder tegenpartij), gebruik dan `/release` — "
        "de opbrengst schaalt met tier en level, plus een kleine kans op een bonus-grondstof. Dit is "
        "onomkeerbaar.",
        [
            "`/trade <speler>` — open het ruil-paneel",
            "`/release <pet_id>` — laat een pet vrij tegen Chaos Coins",
        ],
    ),
    (
        "🏰 Clans",
        "Een clan is een groep spelers die een deel van de werkplek-capaciteit met elkaar delen: elke "
        "clan krijgt zijn **eigen** capaciteit-pool per werkplek, volledig los van andere clans en van "
        "spelers zonder clan. Meer clans in de server betekent dus meer totale werkplek-ruimte voor "
        "iedereen. Het leaderboard laat zien welke clan cumulatief het meest heeft verdiend via werken "
        "— dat blijft staan ook als leden het geld weer uitgeven.",
        [
            "`/clan-aanmaken <naam>` — richt een nieuwe clan op",
            "`/clan-join <naam>` — word lid van een bestaande clan",
            "`/clan-verlaten`, `/clan-ontbinden` — clan verlaten, of ontbinden (alleen oprichter)",
            "`/clan-info [naam]`, `/clan-leaderboard` — info bekijken",
        ],
    ),
    (
        "✨ Leveling",
        "Pets verdienen XP via voltooide werk-shifts en gevechten. Bij `level × 100` XP levelt een pet "
        "op, tot maximaal level 50 — elke level-up geeft een kleine samengestelde groei op zowel "
        "gevecht- als werk-genen, dus oudere/hoger-level pets zijn geleidelijk sterker en productiever "
        "dan een vers gevangen exemplaar van dezelfde soort.",
        [
            "`/lijst` — level en XP-voortgang per pet",
            "`/critterdex`, `/info <soort>` — basisstats per soort (vóór levels/genen)",
        ],
    ),
]


class WikiView(discord.ui.View):
    """Dropdown om direct naar een onderwerp te springen, plus Vorige/
    Volgende-knoppen om er sequentieel doorheen te bladeren — zelfde
    paginering-gevoel als /lijst, maar de "pagina's" zijn hier de
    onderwerpen zelf i.p.v. stukken van 1 lange lijst."""

    def __init__(self, eigenaar_id: int):
        super().__init__(timeout=180)
        self.eigenaar_id = eigenaar_id
        self.onderwerp_index = 0
        self.message: discord.Message | None = None
        self.onderwerp_select.options = [
            discord.SelectOption(label=titel, value=str(i))
            for i, (titel, _, _) in enumerate(WIKI_ONDERWERPEN)
        ]
        self._update_knoppen()

    def _update_knoppen(self) -> None:
        self.vorige.disabled = self.onderwerp_index == 0
        self.volgende.disabled = self.onderwerp_index >= len(WIKI_ONDERWERPEN) - 1

    def huidige_embed(self) -> discord.Embed:
        titel, uitleg, commandos = WIKI_ONDERWERPEN[self.onderwerp_index]
        embed = discord.Embed(title=titel, description=uitleg, color=discord.Color.blurple())
        embed.add_field(name="Relevante commando's", value="\n".join(commandos), inline=False)
        embed.set_footer(text=f"Onderwerp {self.onderwerp_index + 1}/{len(WIKI_ONDERWERPEN)}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.eigenaar_id:
            await interaction.response.send_message("Gebruik je eigen `/wiki` om te bladeren.", ephemeral=True)
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

    @discord.ui.select(placeholder="Kies een onderwerp", row=0)
    async def onderwerp_select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        self.onderwerp_index = int(select.values[0])
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.button(label="◀ Vorige", style=discord.ButtonStyle.primary, row=1)
    async def vorige(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.onderwerp_index -= 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)

    @discord.ui.button(label="Volgende ▶", style=discord.ButtonStyle.primary, row=1)
    async def volgende(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.onderwerp_index += 1
        self._update_knoppen()
        await interaction.response.edit_message(embed=self.huidige_embed(), view=self)


class WikiCog(commands.Cog):
    """Doorbladerbare uitleg van de spelmechanieken. Zie backlog-item
    "Mini-wiki" in docs/dev-status.md."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="wiki", description="Blader door uitleg van hoe Chaos Critters werkt")
    async def wiki(self, interaction: discord.Interaction) -> None:
        view = WikiView(interaction.user.id)
        await interaction.response.send_message(embed=view.huidige_embed(), view=view, ephemeral=False)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WikiCog(bot))
