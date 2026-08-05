import discord
from discord import app_commands
from discord.ext import commands

# Elk onderwerp: (titel, uitleg van de mechaniek, lijst met relevante
# commando's). Handmatig bijgehouden, net als TODO_ITEMS/TEST_COMMANDOS in
# cogs/algemeen.py, bijwerken als een mechaniek verandert. Legt uit HOE
# dingen werken (i.p.v. /commands, dat alleen command-syntax + 1 zin toont).
WIKI_ONDERWERPEN: list[tuple[str, str, list[str]]] = [
    (
        "📖 Vangen & Tiers",
        "Pets spawnen automatisch in de ingestelde spawn-kanalen (op basis van activiteit + af en toe "
        "gewoon na een tijdje). Vang de actieve spawn met `/vang` en de (deel van de) naam. Elke soort "
        "heeft een tier (zeldzaamheid): **Common** (45%), **Uncommon** (25%), **Rare** (18%), **Epic** "
        "(9%), **Legendary** (3%) kans per spawn.\n\n"
        "Een hogere tier geeft een **gevecht-bonus**: de tier-multiplier (1.0x bij Common oplopend tot "
        "2.0x bij Legendary) vermenigvuldigt de gevechtsmacht van je pet, en verhoogt ook wat een pet "
        "oplevert bij `/release`. **Let op**: op je werk-opbrengst heeft de tier géén invloed, daar "
        "telt alleen de werk-motivatie van de pet zelf. Een Common met hoge werk-motivatie kan dus "
        "prima productiever zijn dan een Legendary.",
        [
            "`/vang <naam>`: vang de actieve spawn in dit kanaal",
            "`/lijst`: bekijk al je gevangen pets",
            "`/critterdex`: overzicht van alle soorten + of je 'm al hebt",
            "`/info <soort>`: details van één specifieke soort",
        ],
    ),
    (
        "🌪️ Elementen & contra's",
        "Elke pet-soort heeft een vast element: ⛰️ **Grond**, 🌊 **Water**, 🌪️ **Lucht**, 🔥 **Vuur**, "
        "of 🌀 **Chaos**. Er is een vaste contra-cirkel: **Vuur > Lucht > Grond > Water > Vuur**.\n\n"
        "Sta je in een matchup met het gunstige element tegenover je tegenstander, dan krijg je **+15% "
        "macht**; sta je er ongunstig in, dan **-10%**. Zit je twee stappen uit elkaar in de cirkel "
        "(bijvoorbeeld 🔥 Vuur tegenover ⛰️ Grond), dan gebeurt er niets, dat is neutraal. Zelfde "
        "element tegen elkaar is ook neutraal.\n\n"
        "🌀 **Chaos** volgt de cirkel niet: staat er aan één van beide kanten een Chaos-pet, dan wordt "
        "de uitkomst per matchup willekeurig geloot (bonus, malus of neutraal), voor beide kanten "
        "apart. Onvoorspelbaar dus, in je voordeel én in je nadeel.",
        [
            "`/lijst`, `/team`, `/info`: tonen het element per pet als emoji",
            "`/vecht`: de matchup-titel toont beide elementen tegen elkaar",
            "`/critterdex`: filter alle soorten op element",
        ],
    ),
    (
        "🍖 Verzorgen",
        "Honger daalt vanzelf over tijd. Energie herstelt alleen passief terwijl een pet in **rust** "
        "staat, niet tijdens werk of in je team. Beide worden pas herberekend op het moment dat je de "
        "pet ergens aanraakt (`/lijst`, `/verzorg`, `/werk`, ...), dus verwacht geen live tikkende "
        "teller.\n\n"
        "**Twee grenzen bepalen of een pet inzetbaar is**: bij **energie onder de 20** of **honger op "
        "0** kan een pet niet aan het werk en niet in je team. Dat is meestal de reden dat `/werk` of "
        "`/team` je weigert. Voed met `/verzorg`, of gebruik `/slaap` voor instant volle energie (kost "
        "wel honger, max 1x per dag per pet).\n\n"
        "**Voerbakken** (per pet uit te rusten) voeren een pet automatisch met écht voer uit je "
        "inventaris, telkens wanneer de stats bijgewerkt worden, tot de honger weer vol is of het voer "
        "op is. De **Simpele voerbak** gebruikt alleen Basis brokjes; de **Slimme voerbak** begint bij "
        "je goedkoopste voer en schuift door naar duurder voer zodra dat op is. Heb je niks meer in "
        "voorraad? Dan doet de voerbak niets, gewoon normaal verval, geen gratis vangnet. Het "
        "**Zelfreinigend systeem** laat energie óók buiten rust herstellen, dus ook tijdens werk.",
        [
            "`/verzorg <pet_id> [item] [aantal]`: bekijk stats, of voer een pet",
            "`/slaap <pet_id>`: instant volle energie",
            "`/uitrusten <pet_id> <item> [afkoppelen]`: voerbak/Zelfreinigend systeem aan-/afkoppelen",
            "`/shop`, `/craft`, `/items`: voeding en uitrustingsitems kopen/bekijken",
        ],
    ),
    (
        "👷 Werken & grondstoffen",
        "Zet een pet aan het werk op een werkplek en kies een shift: **korte**, **lange** of "
        "**overnacht**. Langere shifts leveren meer op, maar kosten ook meer energie, die wordt meteen "
        "bij de start afgetrokken. Als de shift klaar is haal je met hetzelfde commando de opbrengst op: "
        "Chaos Coins + de grondstof van die werkplek + XP, plus een kans op een zeldzamere "
        "bonus-grondstof. Je krijgt een seintje in het kanaal zodra een pet klaar is.\n\n"
        "**Wat elke werkplek oplevert** (hoofdgrondstof, altijd; bonus-grondstof, kleine kans per "
        "shift):\n"
        "⛰️ Moestuin: Groente, kans op Fruit\n"
        "🌊 Vijver: Algen, kans op Water\n"
        "🔧 Werkbank: Schroot, kans op Spijker\n"
        "🌲 Bos: Takken, kans op Bladeren\n"
        "🌙 Nachtwacht: Maanschijnkristal, kans op Sterrenstof\n"
        "⛏️ Mijnschacht: Erts, kans op Edelsteen\n\n"
        "**Twee limieten om rekening mee te houden**: je kan maximaal **2 pets tegelijk** aan het werk "
        "hebben, en elke werkplek heeft een eigen **gedeelde capaciteit** (Moestuin heeft 3 plekken, de "
        "rest 2). Die capaciteit deel je met andere spelers: zit je in een clan, dan alleen met je "
        "clangenoten; zit je in geen enkele clan, dan met alle andere clanloze spelers. Vol is vol, even "
        "later opnieuw proberen.\n\n"
        "De grondstoffen die je zo verzamelt heb je nodig voor **recepten**: bepaalde shop-items kosten "
        "naast Chaos Coins ook grondstoffen, en die maak je via `/craft`.",
        [
            "`/werk <pet_id> [werkplek] [cyclus]`: start een shift, of haal 'm op als hij klaar is",
            "`/craft [item] [aantal]`: maak een item met een grondstof-recept, kosten vooraf zichtbaar",
        ],
    ),
    (
        "⚔️ Vechten & ranked",
        "Je hebt een **volledig team van 3 inzetbare pets** nodig om te kunnen vechten. Een gevecht is "
        "best-of-3: je pets nemen het één voor één tegen elkaar op. Per matchup kies je een tactiek "
        "(**Aggressief** = hoog risico, grote uitschieters; **Gebalanceerd** = gemiddeld; "
        "**Voorzichtig** = veilig, kleine marges) of je rent weg. Elementen tellen mee als bonus/malus "
        "op de macht (zie het onderwerp Elementen).\n\n"
        "**Elke verloren matchup levert een tijdelijke blessure op** voor díé pet, ook als je het "
        "gevecht daarna alsnog wint. Een geblesseerde pet is even niet inzetbaar. Elk gevecht kost je "
        "pets sowieso wat energie.\n\n"
        "**XP krijg je altijd**, of je nu wint of verliest, je hele team deelt mee, bij winst flink "
        "meer dan bij verlies. Winnen levert daarnaast MMR op (Elo-systeem: van een sterkere "
        "tegenstander winnen telt zwaarder) plus Chaos Coins die meeschalen met de MMR van je "
        "tegenstander. Verliezen kost MMR.\n\n"
        "Je hebt **3 gratis ranked-pogingen per dag**. Op? Dan kan je een **Extra match token** "
        "gebruiken om er tóch nog een te doen.",
        [
            "`/team`: stel je team van 3 pets samen",
            "`/vecht`: vecht tegen een gesimuleerde tegenstander (wilde dieren)",
            "`/critterdex`, `/info <soort>`: check vooraf de gevecht-stats van een soort",
        ],
    ),
    (
        "🤝 PvP & inzet",
        "Geef `/vecht` een **tegenstander** mee om een echte speler uit te dagen. Je krijgt eerst een "
        "paneel waarin je optioneel een **inzet** samenstelt: Chaos Coins en/of een item uit je "
        "inventaris. De uitgedaagde speler accepteert of weigert; bij acceptatie gaat de volledige "
        "inzet van de verliezer naar de winnaar. Bij PvP kiezen **beide spelers** per matchup hun eigen "
        "tactiek, de matchup lost pas op als jullie allebei gekozen hebben.\n\n"
        "Wil je gewoon oefenen zonder gedoe? Kies **`modus: vriendschappelijk`**. Die is altijd "
        "beschikbaar (ook als je ranked-pogingen op zijn) en kost je niets: geen MMR-verandering, geen "
        "Chaos Coins, **geen XP**, geen blessures, en geen inzet. Puur voor de lol dus, je pets worden "
        "er niet beter van.",
        [
            "`/vecht <tegenstander>`: daag een speler uit (opent het inzet-paneel)",
            "`/vecht [tegenstander] modus:vriendschappelijk`: oefenpotje zonder gevolgen",
            "`/items`: kijk wat je kan inzetten",
        ],
    ),
    (
        "🔁 Traden & releasen",
        "Met `/trade` stel je een ruilvoorstel samen met een andere speler. Per kant bied je **óf één "
        "item (in een gewenst aantal), óf één pet** aan, niet allebei tegelijk, en daar mag je "
        "optioneel Chaos Coins bij doen. Pets die aan het werk zijn kan je niet ruilen.\n\n"
        "Er zitten bewust twee bevestigingen in: de ontvanger accepteert of weigert eerst, en daarna "
        "moet jij als voorsteller nóg een keer definitief bevestigen. Vlak vóór de overdracht wordt "
        "opnieuw gecontroleerd of beide kanten alles nog écht bezitten. Een geruilde pet krijgt bij de "
        "nieuwe eigenaar een nieuw petnummer.\n\n"
        "Wil je een pet gewoon kwijt zonder tegenpartij? `/release` ruilt 'm in voor Chaos Coins (de "
        "opbrengst schaalt met tier en level) plus een kleine kans op een bonus-grondstof. Dit is "
        "onomkeerbaar.",
        [
            "`/trade <speler>`: open het ruil-paneel",
            "`/release <pet_id>`: laat een pet vrij tegen Chaos Coins",
        ],
    ),
    (
        "🏰 Clans",
        "Een clan is een groep spelers die de werkplek-capaciteit met elkaar deelt: elke clan krijgt "
        "zijn **eigen** pool per werkplek, volledig los van andere clans en van spelers zonder clan. "
        "Meer clans in de server betekent dus meer totale werkplek-ruimte voor iedereen, maar binnen "
        "je eigen clan concurreer je wél met je clangenoten om de plekken.\n\n"
        "Je kan in één clan tegelijk zitten; verlaat je huidige clan eerst als je wilt overstappen. "
        "Vertrekt het laatste lid, dan wordt de clan automatisch ontbonden. Alleen de oprichter kan een "
        "clan handmatig ontbinden (ook mét leden erin).\n\n"
        "Het leaderboard toont de top 10 clans op **cumulatieve werk-opbrengst**: alles wat de leden "
        "samen ooit via `/werk` verdiend hebben. Dat telt alleen maar op, uitgeven doet er niets aan af.",
        [
            "`/clan-aanmaken <naam>`: richt een nieuwe clan op (max 32 tekens)",
            "`/clan-join <naam>`: word lid van een bestaande clan",
            "`/clan-verlaten`, `/clan-ontbinden`: clan verlaten, of ontbinden (alleen oprichter)",
            "`/clan-info [naam]`, `/clan-leaderboard`: info bekijken",
        ],
    ),
    (
        "✨ Leveling",
        "Pets verdienen XP via voltooide werk-shifts en via gevechten (winst én verlies). Elk level "
        "kost XP om te bereiken, en dat kost-per-level loopt geleidelijk op naarmate een pet hoger "
        "levelt. **Level 50 is het maximum.**\n\n"
        "Elke level-up geeft een kleine samengestelde groei op **zowel gevecht- als werk-motivatie**, "
        "dus een hoger-level pet is zowel sterker in gevechten als productiever op de werkplek dan een "
        "vers gevangen exemplaar van dezelfde soort. Voor **gevechten** telt je level daarnaast nog een "
        "tweede keer mee als losse machtsbonus bovenop die groei, het verschil tussen een verse en een "
        "uitgelevelde pet is in de arena dus veel groter dan op de werkplek.",
        [
            "`/lijst`: level en XP-voortgang per pet",
            "`/critterdex`, `/info <soort>`: basisstats per soort (vóór levels/motivatie)",
        ],
    ),
    (
        "📋 Dagelijkse opdrachten",
        "Elke dag krijg je **drie willekeurige opdrachten** uit een grotere pool: dingen als critters "
        "vangen, shifts voltooien, gevechten winnen, je pets voeren of items craften. Iedereen krijgt "
        "z'n eigen set, dus je buurman heeft waarschijnlijk andere opdrachten dan jij.\n\n"
        "Voortgang telt **automatisch** mee zodra je iets doet, je hoeft niets te starten of op te "
        "halen. Zodra een opdracht vol is worden de Chaos Coins meteen bijgeschreven, en heb je alle "
        "drie af dan komt daar nog een **bonus** bovenop.\n\n"
        "De opdrachten resetten elke nacht op een vast moment voor iedereen tegelijk. Bewust niet om "
        "middernacht, maar een paar uur later, zodat je bij een late sessie niet halverwege je "
        "voortgang kwijtraakt. In `/opdrachten` zie je precies wanneer de volgende set komt.",
        [
            "`/opdrachten`: je drie opdrachten van vandaag, met voortgangsbalk en beloningen",
        ],
    ),
    (
        "🎉 Chaos events",
        "Af en toe start er een **chaos-event**: een tijdelijk effect dat voor iedereen tegelijk "
        "geldt. Je hoeft je nergens voor aan te melden, het werkt vanzelf zolang het loopt.\n\n"
        "🌫️ **Incense** — critters verschijnen veel sneller in de spawn-kanalen.\n"
        "🌠 **Sterrenregen** — flink meer kans dat een spawn Rare of hoger is.\n"
        "🌾 **Grondstoffenregen** — voltooide shifts leveren meer grondstoffen op.\n"
        "💰 **Muntregen** — meer Chaos Coins uit werken en gevechten.\n\n"
        "**Let op waar een event geldt.** Een Incense of Sterrenregen kan voor alle spawn-kanalen "
        "tegelijk lopen, maar ook voor **één specifiek kanaal** — bijvoorbeeld een tijdelijk "
        "event-kanaal waar normaal helemaal niet gespawnd wordt. In dat geval staat er expliciet "
        "bij in welk kanaal het geldt, en verschijnen de critters ook alleen daar. "
        "Grondstoffenregen en Muntregen gelden altijd overal, want werken en vechten hangen niet "
        "aan een kanaal.\n\n"
        "In de aankondiging staat hoe lang het event nog duurt en hoe sterk het is. Er kunnen er "
        "meerdere tegelijk lopen, want ze raken elk een ander deel van het spel. Een "
        "grondstoffenregen verdubbelt trouwens **alleen** je grondstoffen en niet je Chaos Coins, "
        "daar is de muntregen voor.",
        [
            "Geen commando nodig, events gelden automatisch zolang ze lopen",
            "Lopende events zijn ook te zien op critters.casualchaos.nl",
        ],
    ),
]


class WikiView(discord.ui.View):
    """Dropdown om direct naar een onderwerp te springen, plus Vorige/
    Volgende-knoppen om er sequentieel doorheen te bladeren. Zelfde
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
