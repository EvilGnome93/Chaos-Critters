import discord
from discord import app_commands
from discord.ext import commands

# Wat er nog op de planning staat, in tester-vriendelijke taal. Handmatig
# bijgehouden naast docs/dev-status.md ("Nog niet gebouwd"), dus bijwerken
# als daar iets bijkomt/wegvalt/klaar is.
TODO_ITEMS = [
    ("⚖️ Herbalanceren", "Item-prijzen, XP-snelheden, werk-opbrengsten — de meeste placeholder-balanswaarden zijn tegen het licht gehouden. Het bekende ranked-daglimiet-lek is aangepakt (Extra match token duurder + kost nu ook grondstoffen). Nog open: is het XP-tempo naar max level te traag?"),
    ("🔍 Volledige balans-audit", "Grondige dubbelcheck van alle items, Chaos Coins-prijzen, crafting-recepten en overige balanswaarden. Ook de /shop-UX onder de loep: nu niet altijd duidelijk of je met coins of met grondstoffen (items) betaalt; mogelijk een apart /craft-commando voor recept-aankopen i.p.v. alles door /shop."),
    ("📖 Critterdex", "Overzicht van alle pet-soorten met tier en element, en welke je al gevangen hebt. Max 10 per pagina, filterbaar op tier, standaard gesorteerd op tier + alfabet. Inclusief een `/info <soort>` losse lookup: gevecht/werk-stats, werkplek-voorkeur en hoeveel je er zelf al hebt."),
    ("❓ Mini-wiki", "Doorbladerbaar overzicht van alle commando's, met een dropdown per onderwerp."),
    ("🛠️ Admin panel", "Web-based paneel op casualchaos.nl om balans aan te passen zonder code-wijziging (geen Discord-commando)."),
    ("🐣 Fokken (lange termijn)", "Nieuwe pets kweken van je bestaande pets. Pas echt interessant vanaf 250 pet-soorten, dus staat achteraan."),
]


class AlgemeenCog(commands.Cog):
    """Algemene commando's die niet bij een specifiek spelsysteem horen."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check of de bot online is en meet de latency")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Pong! Latency: {round(self.bot.latency * 1000)}ms", ephemeral=False
        )

    @app_commands.command(name="todo", description="Bekijk wat er nog gepland staat voor Chaos Critters")
    async def todo(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🗺️ Chaos Critters — wat komt er nog aan?",
            description=(
                "Dit staat (ruwweg in deze volgorde) nog op de planning. "
                "(Nieuwe pet-soorten komen er trouwens doorlopend bij, dat stopt nooit echt.)"
            ),
            color=discord.Color.blurple(),
        )
        for titel, uitleg in TODO_ITEMS:
            embed.add_field(name=titel, value=uitleg, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AlgemeenCog(bot))
