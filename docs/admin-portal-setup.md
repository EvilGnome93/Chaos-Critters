# Admin-portal — setup

Het web-adminpanel draait als aiohttp-server ín het bot-proces (`portal/`), en
serveert `web/admin.html` zelf op `/`. Er is dus **geen aparte hosting en geen
CORS-configuratie** nodig: één Railway-service, één deploy.

Zolang de env-vars hieronder ontbreken start de portal simpelweg niet en logt de
bot een waarschuwing — de bot zelf blijft gewoon werken.

## 1. Discord OAuth aanzetten

In de [Discord Developer Portal](https://discord.com/developers/applications) →
kies de applicatie waarvan je de login-knop wil gebruiken → **OAuth2**:

1. Voeg bij **Redirects** exact deze URL toe:
   `https://critters.casualchaos.nl/auth/callback`
   (of, zolang het subdomein nog niet staat, het Railway-domein +
   `/auth/callback`).
2. Noteer de **Client ID** en genereer/kopieer de **Client Secret**.

Je mag hiervoor de bestaande Botv3-applicatie hergebruiken — Discord staat
meerdere redirect-URI's per app toe. Twee kleine nadelen: de secret is dan
gedeeld tussen twee projecten, en het loginscherm toont de naam van die andere
app. De Chaos Critters-bot heeft zelf ook een applicatie, dus overstappen is
later puur een kwestie van deze twee env-vars wijzigen — geen codewijziging.

## 2. Env-vars op Railway

| Variabele | Waarde | Verplicht |
|---|---|---|
| `PORTAL_CLIENT_ID` | Client ID uit stap 1 | ja |
| `PORTAL_CLIENT_SECRET` | Client Secret uit stap 1 | ja |
| `PORTAL_BASIS_URL` | `https://critters.casualchaos.nl` (zonder slash op het eind) | ja |
| `ADMIN_GUILD_ID` | ID van de Discord-server waarop adminrechten gecheckt worden | ja in prod |
| `ADMIN_ROLE_ID` | Rol die naast Administrator ook toegang krijgt | optioneel |
| `PORTAL_SESSIE_DAGEN` | Hoe lang een login geldig blijft (standaard 7) | optioneel |
| `PORTAL_ENABLED` | `true`/`false` om de standaard te overrulen | optioneel |

`PORT` wordt door Railway zelf gezet; lokaal valt de server terug op 8080.

`ADMIN_GUILD_ID` valt terug op `DEV_GUILD_ID`, dus in dev hoef je die niet apart
te zetten.

### Alleen op prod

Het panel is bedoeld voor main/prod. Daarom staat het **standaard uit zodra
`ENVIRONMENT=dev`**, ook als de OAuth-vars daar wél gezet zijn — zo kan er nooit
per ongeluk een tweede paneel meedraaien dat dezelfde database beheert. Wil je
het toch even in dev testen, zet dan expliciet `PORTAL_ENABLED=true` op die
service.

De production-omgeving op Railway draait met **`ENVIRONMENT=prod`**; de check is
"alles behalve `dev`", dus zowel `prod` als `production` zet het panel aan. Zet
de vars uit de tabel hierboven dus alleen op de prod-service.

## 3. Railway: publiek domein

1. Railway → de bot-service → **Settings** → **Networking** → **Generate
   Domain**. Daarmee is de portal meteen bereikbaar op een
   `*.up.railway.app`-adres (handig om te testen vóór het subdomein er is).
2. Voor `critters.casualchaos.nl`: klik **Custom Domain**, vul dat subdomein in,
   en zet bij je DNS-provider het **CNAME**-record dat Railway laat zien.
3. Zodra dat werkt: pas `PORTAL_BASIS_URL` aan én voeg de bijbehorende
   `/auth/callback`-URL toe bij de Discord-redirects (stap 1).

Let op: een **pad** als `casualchaos.nl/critters-admin` kan niet met DNS alleen —
daarvoor zou een reverse proxy nodig zijn op wat casualchaos.nl serveert. Een
subdomein is de eenvoudigste route.

## 4. Controleren

- `https://<domein>/health` → moet JSON teruggeven zonder inloggen.
- `https://<domein>/` → loginscherm; na "Login met Discord" moet je in het
  paneel belanden.

Krijg je `unauthorized` terug: je hebt geen Administrator-permissie (of de
`ADMIN_ROLE_ID`-rol) op de server uit `ADMIN_GUILD_ID`. Krijg je `state`: de
login duurde te lang of de pagina was een oude tab — opnieuw proberen.

## Wat je met de portal kan (v1)

Alles hieronder leest en schrijft rechtstreeks de database die de bot ook
gebruikt; wijzigingen werken **meteen**, zonder herstart.

- **Overzicht** — aantallen spelers/pets/soorten/clans, hoeveel soorten nog nooit
  gevangen zijn, top-5 meest gevangen soorten en rijkste spelers.
- **Instellingen** — de 5 waarden uit de `Instelling`-tabel.
- **Items & prijzen** — prijs en beschrijving. Naam en type zijn read-only omdat
  alle itemnamen als tekst in de botcode staan (recepten, voer-effecten,
  uitrusting-slots, Extra match token).
- **Werkplekken** — output/uur, capaciteit (per clan), beide grondstoffen en de
  bonus-kans. Type read-only: de `/werk`-keuzelijst staat hardcoded.
- **Tiers** — spawnkans (met een waarschuwing als het totaal geen 100% is) en
  stat-multiplier.
- **Pet-soorten** — volledig beheer: toevoegen, bewerken, verwijderen. Push het
  plaatje eerst naar `docs/assets/` op GitHub en plak dan de raw-URL; anders
  onthoudt Discord de mislukte fetch voor die URL. Verwijderen is geblokkeerd
  zolang spelers exemplaren van die soort hebben.
- **Spelers** — coins, MMR, ranked-pogingen, items geven/afnemen, pets bewerken
  (naam/honger/energie/level/XP), blessure opheffen, van het werk halen, pet
  verwijderen.
- **Clans** — bekijken en ontbinden.
- **Kanalen** — spawn-kanalen en logkanalen, met dropdowns van de kanalen die de
  bot ziet. Spawn-kanalen werken direct: de in-memory cache in `cogs/vangen.py`
  wordt meteen bijgewerkt.

## Wat nog níét via de portal kan

De meeste balanswaarden zijn nog **hardcoded Python-constanten** en dus geen
databasewaarden. Om die instelbaar te maken moeten ze eerst naar de
`Instelling`-tabel verhuizen en moet de code ze dynamisch lezen (fase 2, met de
gebruiker afgesproken):

- XP-tempo en level-curve (`utils/leveling.py`)
- de 3 werk-cycli: duur, energiekosten, output-multiplier (`cogs/werk.py`)
- honger-verval, energie-herstel, slaap, blessureduur (`utils/stats.py`)
- gevecht-economie: Elo, coins, XP, tactiek-variantie (`utils/gevechten.py`)
- elementen-bonus/malus (`utils/elementen.py`)
- release-beloning (`cogs/release.py`)
- de 10 crafting-recepten (`RECEPT_KOSTEN` in `cogs/verzorging.py`)
