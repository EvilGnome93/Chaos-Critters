# Chaos Critters — Changelog

Publieke aankondigingen, samengesteld en goedgekeurd via `/changelog`. Nieuwste bovenaan.
Zie `docs/dev-status.md` voor het volledige, technische ontwikkellog.

## Dagelijkse opdrachten, chaos events en 25 nieuwe critters

Een flinke update met drie dingen om te ontdekken.

**📋 Dagelijkse opdrachten**
Elke dag krijg je drie willekeurige opdrachten: critters vangen, shifts voltooien, gevechten winnen, je pets voeren of items craften. Iedereen krijgt z'n eigen set, dus je buurman heeft waarschijnlijk andere dan jij. Voortgang telt automatisch mee, je hoeft niets te starten of op te halen — zodra een opdracht vol is worden de Chaos Coins meteen bijgeschreven. Alle drie afronden geeft een flinke bonus. Bekijk ze met `/opdrachten`.

**🎉 Chaos events**
Af en toe start er een tijdelijk event dat voor iedereen tegelijk geldt. Je hoeft je nergens voor aan te melden:
- 🌫️ **Incense** — critters verschijnen veel sneller (minder chatberichten per spawn)
- ⏱️ **Tijd-incense** — elke zoveel minuten een critter, ook als er niemand chat
- 🌠 **Sterrenregen** — flink meer kans op Rare of hoger
- 🌾 **Grondstoffenregen** — meer grondstoffen per shift
- 💰 **Muntregen** — meer Chaos Coins uit werken en vechten

Een Incense of Sterrenregen kan voor alle spawn-kanalen tegelijk lopen, of juist voor één specifiek kanaal — ook een kanaal waar normaal niet gespawnd wordt. In de aankondiging staat altijd waar het geldt en hoe lang het nog duurt. Er kunnen er meerdere tegelijk lopen.

**🐾 25 nieuwe critters**
De Critterdex staat nu op 175 soorten. Nieuw zijn onder andere de Orka, de Mammoet, de Komodovaraan, de Walvishaai en twee nieuwe Chaos-varianten: de Chaos Wandelende Tak en de Chaos Casuaris.

**📖 Wiki bijgewerkt**
`/wiki` heeft nieuwe pagina's over de dagelijkse opdrachten en de chaos events.

### Voor admins & moderators

- Chaos events start je in de portal onder het nieuwe tabblad **Chaos events**. Per event kies je de duur, de vermenigvuldiger, in welk kanaal het geldt, en optioneel een extra aankondigingskanaal.
- **Incense en Sterrenregen kun je op één kanaal richten.** Kies je een kanaal dat géén spawn-kanaal is, dan verschijnen daar tijdens het event tóch critters — handig voor een tijdelijk event-kanaal los van de vaste spawn-kanalen. Zodra het event afloopt houdt dat vanzelf weer op. Grondstoffenregen en Muntregen zijn altijd server-breed; die hangen niet aan een kanaal.
- De vermenigvuldiger vul je in zoals je 'm leest: bij een incense betekent **8** dat critters 8x sneller verschijnen. Intern is dat een factor 0.125, maar daar heb je geen last van. Boven ~27x staat de drempel al op 1 bericht per spawn, dus hoger invullen doet niets meer — vandaar dat 30 het maximum is.
- Bij de **Tijd-incense** vul je geen factor in maar simpelweg **minuten per spawn**. Die spawnt op de klok en is dus niet afhankelijk van chatactiviteit — handig voor een event-kanaal.
- De standaardsterkte per type staat bij Instellingen (`event_incense_sterkte`, `event_sterrenregen_sterkte`, etc.) en is de voorvulling van dat veld. Een lopend event houdt de sterkte waarmee het gestart is, dus tussentijds bijstellen raakt alleen volgende events.
- Eenzelfde type twee keer in hetzelfde kanaal wordt geweigerd, net als een kanaal-event naast een server-breed event van dat type. Verschillende types naast elkaar mag wel.
- Doelen en beloningen van de dagopdrachten zijn ook instelbaar (`opdracht_*`), net als het resetuur (`opdracht_reset_uur`, standaard 04:00). De opdracht-types zelf zitten in code.
- Let op bij de balans: een grondstoffenregen verdubbelt bewust alleen grondstoffen en niet de Chaos Coins — daar is de muntregen voor.

## De adminportal is live, plus /critter-stats

Sinds de release is er best wat bijgekomen. De hoogtepunten:

**🛠️ De portal (critters.casualchaos.nl)**
Er is nu een web-paneel waar je live kan meekijken met de spelbalans: instellingen, prijzen, werkplekken, tiers en alle pet-soorten. Log in met je Discord-account om het te bekijken.

**📊 /critter-stats**
Nieuw commando: bekijk je eigen (of iemand anders z'n) statistieken in één overzicht. Hoeveel pets je hebt gevangen, je Critterdex-voortgang, hoe vaak je gewerkt hebt, je PvP/PvE-winst en -verlies, en je Chaos Coins.

**🔧 Verder**
Een aantal kleinere fixes en balansaanpassingen sinds de release, waaronder een correctie op hoe snel pets hun eerste levels haalden.
