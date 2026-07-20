# GAMENAME — Projectbrief

**Voor:** Casual Chaos Collective (CCC)
**Type:** Losse Discord bot, apart project van The Assistant v2
**Concept:** Tactical Pet Collector & Manager, met een lichte passieve werk-laag

## Pitch

Spelers vangen unieke huisdieren/wildlife die random spawnen in de server. Ze verzorgen hun pets (stats, voeding, upgrades) en stellen tactische teams van 3 samen voor ranked matches. Pets kunnen ook aan het werk gezet worden op een werkplek voor passieve grondstoffen, in plaats van in het vechtteam te zitten. Nooit beide tegelijk, wat spelers een echte keuze per pet geeft.

## Tech Stack

- **Taal/library**: Python met discord.py, sluit aan bij bestaande tooling en is goed leesbaar voor complexe game logica
- **Database**: PostgreSQL, gehost als losse Railway service naast de bot zelf, ondersteunt schaalbaarheid en automatische backups
- **Hosting**: Los Railway project, onafhankelijk van The Assistant v2

## 1. Database & Basisstructuur

**Spelers**
- Currency, level, XP
- MMR (Matchmaking Rating) voor ranked matches
- `gilde_id` veld alvast aanwezig voor latere uitbreiding, features zelf komen later

**Huisdieren**
- Unieke ID, naam, soort, zeldzaamheid (tier)
- Actuele stats: honger, energie, blijdschap
- Verborgen genetische waarden: `gevecht_genen` en `werk_genen`
- Status veld: `team` / `werkplek` / `rust`
- Toegewezen `werkplek_type` (indien van toepassing)
- Level (beïnvloedt zowel stats als gevecht_genen/werk_genen)

**Inventaris**
- Voeding, upgrade materialen, grondstoffen

**Werkplekken**
- Type, vereiste werk_genen voor efficiëntie, output per tijdseenheid, capaciteit

**Instellingen (nieuw, koppelt aan admin panel)**
- Cooldowns (vang, werk-cyclus, ranked)
- Spawn rates per tier
- Overige balans-waarden die via het admin panel aanpasbaar zijn

## 2. Zeldzaamheidstiers

Tier-nummers met tussenruimte zodat je later tussenliggende tiers kan toevoegen zonder bestaande data te herschrijven.

| Tier | Naam | Spawnkans | Stat multiplier |
|---|---|---|---|
| 1 | Common | ~70% | 1x |
| 3 | Rare | ~25% | 1,4x |
| 5 | Legendary | ~5% | 2x |

Later uit te breiden met tier 2 (Uncommon) en tier 4 (Epic).

## 3. Pet Soorten (startset, huisdieren/wildlife + chaos twist)

**Tier 1, Common**
1. Hond (Zwerfhond), gevecht gemiddeld, werk hoog (moestuin)
2. Kat (Steegkat), gevecht gemiddeld, werk gemiddeld (werkbank)
3. Konijn, gevecht laag, werk hoog (moestuin)
4. Eend, gevecht laag, werk gemiddeld (vijver)
5. Egel, gevecht laag, werk laag, hoge blijdschap bonus

**Tier 3, Rare**
6. Vos, gevecht hoog, werk gemiddeld (bos)
7. Uil, gevecht gemiddeld, werk hoog (nachtwacht, bonus op overnacht shifts)
8. Wasbeer, gevecht gemiddeld, werk hoog (werkbank, mijnschacht toegang)
9. Otter, gevecht laag, werk hoog (vijver, snelste)
10. Chaos Kip, onvoorspelbare stats die dagelijks licht wisselen

**Tier 5, Legendary**
11. Wolf, gevecht zeer hoog, werk laag
12. Steenarend, gevecht hoog, werk gemiddeld, unieke bonus: verhoogt zeldzame spawn kans in zijn kanaal
13. Chaos Eenhoorn-Ratrace-hybride, hoogste stats, willekeurige chaos events bij gebruik

## 4. Werkplek Types (startset, 5)

| Werkplek | Beste werk_genen soort | Output | Past bij |
|---|---|---|---|
| Moestuin | Hoge werk_genen, lage vereisten | Voedsel/grondstof basis | Hond, Konijn |
| Vijver | Water-affiniteit | Zeldzamere voedingsgrondstof | Eend, Otter |
| Werkbank | Behendigheid | Upgrade materialen | Kat, Wasbeer |
| Bos (verzamelen) | Verkenning | Mix van grondstoffen, kans op bonus item | Vos |
| Nachtwacht | Nacht-affiniteit | Bonus op overnacht cyclus | Uil |

## 5. Verzorgingssysteem & Shop (startset, 11 items)

**Voeding**
1. Basis brokjes, kleine energie boost, goedkoop
2. Graanvrije premium voeding, grotere energie boost + tijdelijke stat boost voor 1 match
3. Vers vlees/vis, volledige energie herstel, duur

**Automatisering**
4. Simpele voerbak, klein passief energie herstel, eenmalige aankoop
5. Slimme voerbak, beter passief herstel, vereist grondstoffen + currency
6. Zelfreinigend systeem, verhoogt blijdschap automatisch, voorkomt stat verval bij afwezigheid

**Boosts**
7. Focus drankje, tijdelijke gevecht_genen boost voor 1 ranked match
8. Werk-elixer, tijdelijke werk_genen boost voor 1 werk cyclus
9. Extra match token, koopt een ranked poging boven de dagelijkse gratis cooldown

**Overig**
10. Naamkaartje, hernoem je pet
11. Mysterie voedselzak, willekeurige voeding, goedkoper dan los kopen

## 6. Werk-laag & Balans

- Speler wijst een pet toe aan team óf werkplek, nooit beide tegelijk
- Werkende pets produceren passief over tijd, opgehaald via commando

**Energie als gedeelde resource** (0-100 per pet)
- Werk verbruikt energie geleidelijk over de cyclus
- Vechten kost een vaste hap energie per match, ongeacht winst of verlies
- Onder 20 energie kan een pet niet ingezet worden

**Werk cyclus tijden**

| Cyclus | Duur | Energie kost | Output multiplier |
|---|---|---|---|
| Korte shift | 2 uur | -20 | 1x |
| Lange shift | 6 uur | -50 | 2,8x |
| Overnacht | 10 uur | -70 | 4,5x |

**Waarom vechten niet altijd de betere keuze is**
- Ranked matches hebben een dagelijkse cooldown (bijv. 3 gratis per dag)
- Werk levert grondstoffen op die nergens anders vandaan komen behalve de shop tegen currency
- Omgekeerde correlatie tussen gevecht_genen en werk_genen: sterke vechters zijn meestal zwakke werkers en andersom

**Herstel**
- Passief herstel in rust status (bijv. +1 energie per 10 minuten)
- Voeding kan energie direct aanvullen tegen currency of grondstoffen

## 7. Vangmechaniek

- `/vang <naam>` als een pet spawnt in het kanaal, bijvoorbeeld `/vang vos`
- Eerste speler die het juiste commando gebruikt, vangt de pet
- Hoofdletterongevoelige matching voor gebruiksgemak
- Korte cooldown per speler na een vangst, instelbaar via het admin panel

## 8. Spawn Systeem

Combinatie van activiteit- en tijd-triggers:
- **Activiteit-trigger**: elke X berichten in een aangewezen kanaal (bijv. 25-40, met randomisatie)
- **Tijd-trigger**: los daarvan, op vaste momenten spawnt er sowieso een pet, ook bij stille chat
- Zeldzamere pets kunnen een kleine extra kans krijgen bij de tijd-trigger

## 9. Level-up Systeem

Bij een level-up groeien zowel stats als gevecht_genen en werk_genen mee, in een klein percentage per level (bijv. +2% per level). Dit geeft spelers reden om ook lagere tier pets te blijven trainen.

## 10. Fokken/Breeding

- Twee pets van hetzelfde type: hoge kans (~80%) op een pet van datzelfde type, genen zijn gemiddelde van de ouders plus kleine variatie
- Twee pets van verschillend type: lagere kans (~15-20%) op een volledig nieuwe hybride soort met gemengde genen, anders een van de ouder-types met gemixte genen
- Kost currency en/of grondstoffen, cooldown per pet

## 11. Trading

- Direct ruilen en verkopen tussen spelers via `/trade`, met bevestiging van beide kanten
- Verkopen via `/verkoop` naar een marktplaats tegen currency
- Kleine trading fee bij marktplaats verkoop, voorkomt dat trading de enige currency bron wordt

## 12. Competitie & Team Tactiek

- Teams van 3 pets, volledige controle door de speler
- Niet-werkende pets zijn beschikbaar voor het team

**Vecht-formule**

Team sterkte per pet:
`pet_power = gevecht_genen × tier_multiplier × (1 + level × 0,05)`

Team totaal: som van de 3 pet_power waarden, plus 10% bonus bij 3 verschillende pet-types in het team (beloont variatie).

RNG element: elk team_totaal krijgt een willekeurige variantie van -15% tot +15% per match, zodat een sterker team meestal maar niet altijd wint.

Optioneel voor later: front/back positionering voor extra tactische diepte.

Gekoppeld aan MMR voor ranked matches.

## 13. Currency Bronnen & Sinks

**Bronnen**
- Werk-laag opbrengsten
- Ranked match overwinningen (groter bij hogere MMR tegenstanders)
- Dagelijkse activiteit/login bonus

**Sinks**
- Shop aankopen
- Fokken kosten
- Extra ranked pogingen boven de gratis cooldown
- Trading fee bij marktplaats verkoop

## 14. Admin Panel

Aparte interne pagina (bijv. `admin.html`) die op dezelfde database leest/schrijft als de bot:
- Cooldowns aanpassen (vang, werk-cyclus, ranked)
- Spawn rates per tier bijstellen
- Shop items toevoegen, verwijderen, prijzen aanpassen
- Nieuwe pet soorten of werkplekken toevoegen zonder bot-herstart

## 15. Notificaties & Progressie

- Webhook berichten in algemeen kanaal bij mijlpalen: zeldzame vangst, eerste pet die "meester" wordt op een werkplek, servertotaal vangsten
- Optionele melding wanneer een werkende pet klaar is om opgehaald te worden

## 16. Later, Optioneel

- Standalone HTML dashboard voor visueel collectie- en werkplekbeheer naast Discord commando's
- Gilde systeem: gedeelde werkplekken, gilde leaderboards (database veld staat al klaar)

## Nog open, niet blokkerend voor de start

- Visuele content: krijgen pets een plaatje/icoon in de vangst-embed, of blijft het tekst-based in het begin
- Volledig command overzicht met exacte syntax (`/vang`, `/team`, `/werk`, `/trade`, `/verkoop`, `/fok`, etc.), handig om samen met Claude Code op te stellen bij de eerste implementatie
