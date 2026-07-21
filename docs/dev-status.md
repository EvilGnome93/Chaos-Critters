# Chaos Critters — Dev-status

Dit document vat samen wat er staat en waarom, zodat een nieuwe Claude Code-sessie
(op deze of een andere locatie) snel weer aanhaakt. Voor het volledige ontwerp: zie
`docs/chaos-critters-projectbrief.md`.

## Setup

- **Repo**: `EvilGnome93/Chaos-Critters` (hernoemd vanaf `gamename-bot`), branch `dev` is actief werk, `main` is voor later/productie.
- **Stack**: Python + discord.py 2.7, PostgreSQL via SQLAlchemy async (asyncpg) + Alembic migraties.
- **Migraties draaien automatisch bij opstart** (`bot.py`, `_draai_migraties()`): vóórdat de bot connect, draait hij `alembic upgrade head` als subprocess tegen de eigen `DATABASE_URL`. Lukt dat niet, dan crasht de bot bewust meteen (geen silent start op een verouderd schema). Dit loste een incident op (2026-07-21): een migratie was gepusht maar nog niet tegen Railway's DB gedraaid, waardoor `/werk`/`/verzorg`/`/lijst` crashten met `UndefinedColumnError`. Je hoeft dus niet meer handmatig `alembic upgrade head` te draaien na een deploy — wel nog steeds nodig als je zelf lokaal migraties wil testen vóórdat je pusht.
- **Lokaal draaien**: `venv/Scripts/python.exe bot.py` vanuit `gamename-bot/`. **Let op**: niet lokaal draaien terwijl Railway ook live staat — beide processen proberen dezelfde Discord-interacties te beantwoorden en botsen (zie git-log rond "Race condition" en de `/werk` ephemeral-fix).
- **Environments**: `ENVIRONMENT=dev` in `.env`/Railway-variables schakelt: instant guild-command-sync (`DEV_GUILD_ID`), snellere test-cycli (werk-shifts 1 minuut i.p.v. uren, spawn-tijd-trigger elke 30 min i.p.v. 2-4 uur), en dev-logging naar console.
- **Railway**: twee environments (`production` = huidige Postgres + huidige dev-bot-service; er is nog geen aparte prod-bot-service). `DATABASE_URL` op Railway zelf gebruikt de interne referentie; lokaal `.env` gebruikt de publieke proxy-URL (interne hostname is niet bereikbaar van buiten Railway's netwerk).

## Wat werkt (getest, op dev)

- **`/ping`** — connectiviteitscheck.
- **`/vang <naam>`** — vangt de actief gespawnde pet in het kanaal (exacte naam, of het deel vóór haakjes bij soorten als "Hond (Zwerfhond)" → "Hond"). Geen spawn actief = nette foutmelding.
- **Spawn-systeem**: activiteit-trigger (25-40 berichten, instelbaar via `Instelling`-tabel) + tijd-trigger (2-4u, 30 min in dev), meerdere spawn-kanalen per server (`/setspawnkanaal`, `/verwijderspawnkanaal`). Eén actieve spawn per kanaal; een nieuwe spawn markeert de oude als "ontsnapt" in de embed (race-condition-veilig via een lock per kanaal). Spawn-embed toont tier-kleur + pet-afbeelding (of placeholder). Bij vangst wordt dezelfde embed geëdit naar "gevangen door X", geen apart bericht meer.
- **`/spawn`** (admin) — forceert een spawn, met optionele `tier`- en `naam`-parameters (naam heeft autocomplete).
- **Werk-laag**: `/werk pet_id werkplek cyclus` wijst toe; `/werk pet_id` (zonder extra params) haalt op als de shift klaar is, of toont resterende tijd. Elke werkplek levert een eigen grondstof-item + Chaos Coins (was "currency", puur weergavenaam gewijzigd — DB-kolom heet nog `currency`). Energie wordt volledig afgetrokken bij start. **Werkplek-capaciteit wordt nog niet afgedwongen** — staat gepland voor de gilde-feature (sectie 16 van de brief). Notificatie: tag in het kanaal waar de shift gestart is (niet DM) zodra klaar.
- **`/lijst`** — gepagineerd (10/pagina) overzicht van je pets, publiek zichtbaar, met sorteerknoppen (ID/Level/Naam/Werkstatus + Honger/Energie/Blijdschap, elk een eigen kleur, actieve sortering met ✅-prefix), resterende werktijd per werkende pet, en per pet de actuele honger/energie/blijdschap. Sortering op de 3 stats is oplopend (laagste/meest urgent te verzorgen eerst).
- **Discord-logsysteem**: `/setlog <categorie> <kanaal>` (admin) koppelt per server+categorie een logkanaal (`utils/discord_log.py`, patroon overgenomen van het Botv3-project maar herbouwd in Python). Categorieën in gebruik: `main` (bot start/fouten), `vangst` (catches + geforceerde spawns), `werk` (start/opbrengst).
- **13 pet-soorten geseed** (3 tiers: Common 70%, Rare 25%, Legendary 5%, gelijk verdeeld binnen tier), elk met een eigen AI-gegenereerde afbeelding in `docs/assets/`, gelinkt via `scripts/link_afbeeldingen.py` (leest repo-naam automatisch uit de git remote, dus overleefde de repo-rename zonder handwerk).
- **5 werkplekken geseed**, elk gekoppeld aan een eigen grondstof-item.
- **11 shop-items geseed**, koopbaar via `/shop` (zie hieronder).
- **Stat-verval & `/verzorg`**: honger/blijdschap dalen lazy over tijd (berekend bij elke aanraking van een pet, zoals `/lijst`, `/verzorg`, `/werk` — geen achtergrondtaak, logica in `utils/stats.py`). Energie herstelt passief (+1/10 min, alleen in status `rust`, brief sectie 6). `/verzorg pet_id` toont de stats; met optioneel `item` (Basis brokjes/Graanvrije premium voeding/Vers vlees/vis/Mysterie voedselzak) verbruikt het 1 stuk uit de inventaris voor een energie-boost. Bij honger=0 of blijdschap=0 kan een pet niet aan het werk gezet worden (zelfde blokkade als energie<20, gedeeld via `inzetbaarheid_probleem()`). Verval-snelheden zijn placeholders, en in dev met dezelfde 120x-versnellingsfactor als de werk-cycli. Volledig getest op dev (2026-07-21): verval, herstel, voeden en de blokkade bij 0 werken allemaal. **Nog niet gedekt**: honger zelf direct herstellen (de 3 voedingsitems herstellen alleen energie, per brief-tekst).
- **`/shop`** — zonder `item` toont het een ephemeral overzicht van de 11 koopbare items (gegroepeerd: Voeding/Boosts/Overig, grondstoffen/materialen niet-koopbaar want die komen alleen uit werken). Met `item` + optioneel `aantal` koopt het tegen Chaos Coins (autocomplete over koopbare items). De 3 "overig"-automatiseringsitems (voerbakken, zelfreinigend systeem) zijn nu wel koopbaar, maar hun passieve herstel-effect is **bewust nog niet geïmplementeerd** — ze belanden alleen in de inventaris, met opzet buiten scope van deze stap gehouden.
- **`/items`** — ephemeral overzicht van je inventaris, gegroepeerd per itemtype (Voeding/Grondstoffen/Materialen/Boosts/Overig) met aantallen.
- **`/give`** (admin) — geeft een speler N stuks van een item (autocomplete over alle geseede items). Was bedoeld als tijdelijk testcommando zolang er geen `/shop` was; nu die er is, heroverwegen of dit blijft staan (handig voor toekomstige features testen) of weg mag.
- **`/tests`** (admin) — stuurt een `@everyone`-oproep (embed) met een korte uitleg per speler-commando (`/vang`, `/lijst`, `/werk`, `/verzorg`, `/shop`, `/items`), om een testronde aan te kondigen. Lijst met commando's staat hardcoded in `TEST_COMMANDOS` in `cogs/admin.py` — bijwerken als er een nieuw speler-commando bijkomt. Vereist dat de bot-rol de "Mention @everyone"-permissie heeft, anders pingt het niet.

## Nog niet gebouwd (uit de brief, ruwweg in logische volgorde)

Het verzorgingssysteem (voeden, stat-verval, shop-koopcommando) is volledig af en getest, zie "Wat werkt" hierboven.

1. Level-up systeem (stats/genen laten meegroeien).
2. Team & gevechten (`/team`, `/vecht`) — placeholders in `cogs/gevechten.py`, vecht-formule staat al in de brief (sectie 12).
3. Fokken/breeding (`cogs/fokken.py` is placeholder).
4. Trading (`cogs/trading.py` is placeholder).
5. Admin panel / `/instelling`-commando (placeholder in `cogs/admin.py`) — Instellingen-tabel bestaat al met een paar waardes (spawn-interval, vang-cooldown, ranked-per-dag), maar er is nog geen manier om ze via Discord te wijzigen.
6. Werkplek-capaciteit afdwingen (zie hierboven — expliciet uitgesteld, niet vergeten).
7. Gilde-systeem (verder weg, `gilde_id`-velden staan al klaar in het schema).
8. Help-commando (mini-wiki): `/help`, publiek bericht in het kanaal (zoals `/lijst`). Dropdown om een onderwerp te kiezen, buttons voor navigatie/paginering binnen dat onderwerp (zelfde patroon als `/lijst`). Welke onderwerpen erin komen en de exacte inhoud nog te bepalen.
9. Passief herstel-effect van de automatiseringsitems (Simpele/Slimme voerbak, Zelfreinigend systeem) — nu wel koopbaar via `/shop`, maar zonder effect. Vereist nieuwe velden + aanpassing van `utils/stats.py`.

## Belangrijke afspraken/voorkeuren van de gebruiker

- Altijd vragen stellen bij ontwerpkeuzes voordat je bouwt (niet zelf beslissen en doorbouwen).
- Na elke afgeronde stap automatisch committen + pushen naar `dev`, tenzij anders aangegeven.
- Testen gebeurt zoveel mogelijk via losse logica-scripts (met opruimen van testdata achteraf) i.p.v. de bot lokaal laten draaien, om botsingen met de live Railway-instance te voorkomen.
- Placeholder-balanswaarden (getallen voor genen, prijzen, `CURRENCY_PER_GRONDSTOF`, etc.) zijn expliciet gemarkeerd als voorlopig — later bij te stellen, mogelijk via een admin panel/web-portal.
