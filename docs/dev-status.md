# Chaos Critters — Dev-status

Dit document vat samen wat er staat en waarom, zodat een nieuwe Claude Code-sessie
(op deze of een andere locatie) snel weer aanhaakt. Voor het volledige ontwerp: zie
`docs/chaos-critters-projectbrief.md`.

## Setup

- **Repo**: `EvilGnome93/Chaos-Critters` (hernoemd vanaf `gamename-bot`), branch `dev` is actief werk, `main` is voor later/productie.
- **Stack**: Python + discord.py 2.7, PostgreSQL via SQLAlchemy async (asyncpg) + Alembic migraties.
- **Lokaal draaien**: `venv/Scripts/python.exe bot.py` vanuit `gamename-bot/`. **Let op**: niet lokaal draaien terwijl Railway ook live staat — beide processen proberen dezelfde Discord-interacties te beantwoorden en botsen (zie git-log rond "Race condition" en de `/werk` ephemeral-fix).
- **Environments**: `ENVIRONMENT=dev` in `.env`/Railway-variables schakelt: instant guild-command-sync (`DEV_GUILD_ID`), snellere test-cycli (werk-shifts 1 minuut i.p.v. uren, spawn-tijd-trigger elke 30 min i.p.v. 2-4 uur), en dev-logging naar console.
- **Railway**: twee environments (`production` = huidige Postgres + huidige dev-bot-service; er is nog geen aparte prod-bot-service). `DATABASE_URL` op Railway zelf gebruikt de interne referentie; lokaal `.env` gebruikt de publieke proxy-URL (interne hostname is niet bereikbaar van buiten Railway's netwerk).

## Wat werkt (getest, op dev)

- **`/ping`** — connectiviteitscheck.
- **`/vang <naam>`** — vangt de actief gespawnde pet in het kanaal (exacte naam, of het deel vóór haakjes bij soorten als "Hond (Zwerfhond)" → "Hond"). Geen spawn actief = nette foutmelding.
- **Spawn-systeem**: activiteit-trigger (25-40 berichten, instelbaar via `Instelling`-tabel) + tijd-trigger (2-4u, 30 min in dev), meerdere spawn-kanalen per server (`/setspawnkanaal`, `/verwijderspawnkanaal`). Eén actieve spawn per kanaal; een nieuwe spawn markeert de oude als "ontsnapt" in de embed (race-condition-veilig via een lock per kanaal). Spawn-embed toont tier-kleur + pet-afbeelding (of placeholder). Bij vangst wordt dezelfde embed geëdit naar "gevangen door X", geen apart bericht meer.
- **`/spawn`** (admin) — forceert een spawn, met optionele `tier`- en `naam`-parameters (naam heeft autocomplete).
- **Werk-laag**: `/werk pet_id werkplek cyclus` wijst toe; `/werk pet_id` (zonder extra params) haalt op als de shift klaar is, of toont resterende tijd. Elke werkplek levert een eigen grondstof-item + Chaos Coins (was "currency", puur weergavenaam gewijzigd — DB-kolom heet nog `currency`). Energie wordt volledig afgetrokken bij start. **Werkplek-capaciteit wordt nog niet afgedwongen** — staat gepland voor de gilde-feature (sectie 16 van de brief). Notificatie: tag in het kanaal waar de shift gestart is (niet DM) zodra klaar.
- **`/lijst`** — gepagineerd (10/pagina) overzicht van je pets, publiek zichtbaar, met sorteerknoppen (ID/Level/Naam/Werkstatus, elk een eigen kleur, actieve sortering met ✅-prefix) en resterende werktijd per werkende pet.
- **Discord-logsysteem**: `/setlog <categorie> <kanaal>` (admin) koppelt per server+categorie een logkanaal (`utils/discord_log.py`, patroon overgenomen van het Botv3-project maar herbouwd in Python). Categorieën in gebruik: `main` (bot start/fouten), `vangst` (catches + geforceerde spawns), `werk` (start/opbrengst).
- **13 pet-soorten geseed** (3 tiers: Common 70%, Rare 25%, Legendary 5%, gelijk verdeeld binnen tier), elk met een eigen AI-gegenereerde afbeelding in `docs/assets/`, gelinkt via `scripts/link_afbeeldingen.py` (leest repo-naam automatisch uit de git remote, dus overleefde de repo-rename zonder handwerk).
- **5 werkplekken geseed**, elk gekoppeld aan een eigen grondstof-item.
- **11 shop-items geseed** (nog geen `/shop`-koopcommando gebouwd, alleen de data staat klaar).
- **Stat-verval & `/verzorg`**: honger/blijdschap dalen lazy over tijd (berekend bij elke aanraking van een pet, zoals `/lijst`, `/verzorg`, `/werk` — geen achtergrondtaak, logica in `utils/stats.py`). Energie herstelt passief (+1/10 min, alleen in status `rust`, brief sectie 6). `/verzorg pet_id` toont de stats; met optioneel `item` (Basis brokjes/Graanvrije premium voeding/Vers vlees/vis/Mysterie voedselzak) verbruikt het 1 stuk uit de inventaris voor een energie-boost. Bij honger=0 of blijdschap=0 kan een pet niet aan het werk gezet worden (zelfde blokkade als energie<20, gedeeld via `inzetbaarheid_probleem()`). Verval-snelheden zijn placeholders, en in dev met dezelfde 120x-versnellingsfactor als de werk-cycli. **Nog niet gedekt**: honger zelf direct herstellen (de 3 voedingsitems herstellen alleen energie, per brief-tekst) en de "overig"-automatiseringsitems (voerbakken, zelfreinigend systeem) — die horen bij de shop-stap.
- **`/give`** (admin) — geeft een speler N stuks van een item (autocomplete over alle geseede items). Tijdelijk testcommando zodat `/verzorg` (en later de shop-items) getest kunnen worden zonder `/shop`. Overwegen om te verwijderen of achter een extra guard te zetten zodra `/shop` bestaat.

## Nog niet gebouwd (uit de brief, ruwweg in logische volgorde)

1. Verzorgingssysteem: shop-koopcommando (`/shop`, uitgeven van Chaos Coins aan de 11 geseede items) — voeding gebruiken + stat-verval is al gebouwd, zie hierboven.
2. Level-up systeem (stats/genen laten meegroeien).
3. Team & gevechten (`/team`, `/vecht`) — placeholders in `cogs/gevechten.py`, vecht-formule staat al in de brief (sectie 12).
4. Fokken/breeding (`cogs/fokken.py` is placeholder).
5. Trading (`cogs/trading.py` is placeholder).
6. Admin panel / `/instelling`-commando (placeholder in `cogs/admin.py`) — Instellingen-tabel bestaat al met een paar waardes (spawn-interval, vang-cooldown, ranked-per-dag), maar er is nog geen manier om ze via Discord te wijzigen.
7. Werkplek-capaciteit afdwingen (zie hierboven — expliciet uitgesteld, niet vergeten).
8. Gilde-systeem (verder weg, `gilde_id`-velden staan al klaar in het schema).
9. Help-commando (mini-wiki): `/help`, publiek bericht in het kanaal (zoals `/lijst`). Dropdown om een onderwerp te kiezen, buttons voor navigatie/paginering binnen dat onderwerp (zelfde patroon als `/lijst`). Welke onderwerpen erin komen en de exacte inhoud nog te bepalen.

## Belangrijke afspraken/voorkeuren van de gebruiker

- Altijd vragen stellen bij ontwerpkeuzes voordat je bouwt (niet zelf beslissen en doorbouwen).
- Na elke afgeronde stap automatisch committen + pushen naar `dev`, tenzij anders aangegeven.
- Testen gebeurt zoveel mogelijk via losse logica-scripts (met opruimen van testdata achteraf) i.p.v. de bot lokaal laten draaien, om botsingen met de live Railway-instance te voorkomen.
- Placeholder-balanswaarden (getallen voor genen, prijzen, `CURRENCY_PER_GRONDSTOF`, etc.) zijn expliciet gemarkeerd als voorlopig — later bij te stellen, mogelijk via een admin panel/web-portal.
