"""Portal-endpoints voor spelcontent: instellingen, items, werkplekken,
tiers, pet-soorten en kanalen.

Wat wél en niet aanpasbaar is, is een bewuste keuze (2026-07-29). Een aantal
namen staat hardcoded in de botcode en zou bij hernoemen stille bugs geven:

- **Item-namen**: alle 16 komen als string terug in `RECEPT_KOSTEN`
  (cogs/verzorging.py), `HONGER_HERSTEL_WAARDEN`/`VOERBAK_ITEMS_PER_NIVEAU`
  (utils/stats.py), `VOERBAK_NIVEAUS`, en de Extra match token-lookup in
  cogs/gevechten.py. Daarom zijn naam en type read-only en kan je geen items
  toevoegen/verwijderen — alleen prijs en beschrijving.
- **Werkplek-type**: de `/werk`-keuzelijst is een hardcoded
  `app_commands.Choice`-lijst, dus een nieuwe of hernoemde werkplek zou
  onbereikbaar zijn. Type read-only, geen toevoegen/verwijderen.
- **Pet-soorten** zijn wél volledig beheersbaar (toevoegen/bewerken/
  verwijderen): de code verwijst er nergens hardcoded naar, behalve
  `WILDE_NAMEN` (cogs/gevechten.py, de PvE-tegenstanders) — dat filtert
  ontbrekende namen netjes weg, dus daar waarschuwen we alleen voor.
"""

import logging

from aiohttp import web
from sqlalchemy import delete, func, select

from db.engine import async_session
from db.models import (
    Element,
    Huisdier,
    Instelling,
    Item,
    ItemType,
    LogChannel,
    PetSoort,
    SpawnKanaal,
    Tier,
    Werkplek,
)
from portal import auth

log = logging.getLogger("chaos_critters")

# Pet-soorten waar cogs/gevechten.py:WILDE_NAMEN naar verwijst voor de
# PvE-tegenstanders. Verwijderen/hernoemen maakt de lijst stiller (minder
# variatie in wilde tegenstanders), maar crasht niets — puur een waarschuwing
# in de portal.
from cogs.gevechten import WILDE_NAMEN


class ValidatieFout(Exception):
    """Nette 400 i.p.v. een 500 bij onbruikbare invoer uit de portal."""


def _getal(data: dict, veld: str, *, minimum: float, maximum: float, heel: bool = False) -> float | int:
    if veld not in data:
        raise ValidatieFout(f"veld '{veld}' ontbreekt")
    try:
        waarde = int(data[veld]) if heel else float(data[veld])
    except (TypeError, ValueError):
        raise ValidatieFout(f"'{veld}' moet een {'heel ' if heel else ''}getal zijn")
    if not minimum <= waarde <= maximum:
        raise ValidatieFout(f"'{veld}' moet tussen {minimum} en {maximum} liggen")
    return waarde


def _tekst(data: dict, veld: str, *, max_lengte: int, verplicht: bool = True) -> str | None:
    ruw = (data.get(veld) or "").strip()
    if not ruw:
        if verplicht:
            raise ValidatieFout(f"'{veld}' mag niet leeg zijn")
        return None
    if len(ruw) > max_lengte:
        raise ValidatieFout(f"'{veld}' mag maximaal {max_lengte} tekens zijn")
    return ruw


# ── Instellingen ────────────────────────────────────────────────────────────

async def instellingen_ophalen(request: web.Request) -> web.Response:
    async with async_session() as session:
        rijen = (await session.execute(select(Instelling).order_by(Instelling.sleutel))).scalars().all()
    return web.json_response(
        [{"sleutel": i.sleutel, "waarde": i.waarde, "beschrijving": i.beschrijving} for i in rijen]
    )


async def instellingen_opslaan(request: web.Request) -> web.Response:
    """POST /api/instellingen — body: {"sleutel": "waarde", ...}.

    Bewust alleen bestaande sleutels bijwerken: een onbekende sleutel wordt
    door geen enkele cog gelezen, dus die zou stil niets doen."""
    data = await request.json()
    if not isinstance(data, dict):
        raise ValidatieFout("body moet een object van sleutel/waarde zijn")

    bijgewerkt = []
    async with async_session() as session:
        for sleutel, waarde in data.items():
            instelling = await session.get(Instelling, sleutel)
            if instelling is None:
                raise ValidatieFout(f"onbekende instelling '{sleutel}'")
            nieuw = str(waarde).strip()
            if not nieuw or len(nieuw) > 256:
                raise ValidatieFout(f"waarde voor '{sleutel}' is leeg of te lang")
            instelling.waarde = nieuw
            bijgewerkt.append(sleutel)
        await session.commit()

    log.info("Portal: instellingen bijgewerkt: %s", ", ".join(bijgewerkt))
    return web.json_response({"ok": True, "bijgewerkt": bijgewerkt})


# ── Items ───────────────────────────────────────────────────────────────────

async def items_ophalen(request: web.Request) -> web.Response:
    async with async_session() as session:
        rijen = (await session.execute(select(Item).order_by(Item.type, Item.naam))).scalars().all()
    return web.json_response(
        [
            {
                "id": i.id,
                "naam": i.naam,
                "type": i.type.value,
                "prijs": i.prijs,
                "beschrijving": i.beschrijving,
                # Grondstoffen/materialen hebben prijs 0 en zijn niet koopbaar;
                # het panel toont dat als "niet in de shop".
                "koopbaar": i.prijs > 0,
            }
            for i in rijen
        ]
    )


async def item_opslaan(request: web.Request) -> web.Response:
    """POST /api/items/{id} — alleen prijs en beschrijving (zie module-docstring)."""
    item_id = int(request.match_info["id"])
    data = await request.json()
    prijs = _getal(data, "prijs", minimum=0, maximum=1_000_000, heel=True)
    beschrijving = _tekst(data, "beschrijving", max_lengte=256, verplicht=False)

    async with async_session() as session:
        item = await session.get(Item, item_id)
        if item is None:
            raise ValidatieFout("item bestaat niet")
        item.prijs = prijs
        item.beschrijving = beschrijving
        await session.commit()
        naam = item.naam

    log.info("Portal: item '%s' bijgewerkt (prijs %s)", naam, prijs)
    return web.json_response({"ok": True})


# ── Werkplekken ─────────────────────────────────────────────────────────────

async def werkplekken_ophalen(request: web.Request) -> web.Response:
    async with async_session() as session:
        rijen = (await session.execute(select(Werkplek).order_by(Werkplek.id))).scalars().all()
        grondstoffen = (
            await session.execute(
                select(Item)
                .where(Item.type.in_([ItemType.grondstof, ItemType.materiaal]))
                .order_by(Item.naam)
            )
        ).scalars().all()

    return web.json_response(
        {
            "werkplekken": [
                {
                    "id": w.id,
                    "type": w.type,
                    "output_per_uur": float(w.output_per_uur),
                    "capaciteit": w.capaciteit,
                    "opbrengst_item_id": w.opbrengst_item_id,
                    "opbrengst_item_2_id": w.opbrengst_item_2_id,
                    "opbrengst_2_kans": float(w.opbrengst_2_kans),
                }
                for w in rijen
            ],
            "grondstoffen": [{"id": i.id, "naam": i.naam} for i in grondstoffen],
        }
    )


async def werkplek_opslaan(request: web.Request) -> web.Response:
    werkplek_id = int(request.match_info["id"])
    data = await request.json()
    output = _getal(data, "output_per_uur", minimum=0.1, maximum=1000)
    capaciteit = _getal(data, "capaciteit", minimum=1, maximum=100, heel=True)
    kans = _getal(data, "opbrengst_2_kans", minimum=0, maximum=1)

    async with async_session() as session:
        werkplek = await session.get(Werkplek, werkplek_id)
        if werkplek is None:
            raise ValidatieFout("werkplek bestaat niet")

        for veld in ("opbrengst_item_id", "opbrengst_item_2_id"):
            ruw = data.get(veld)
            item_id = int(ruw) if ruw not in (None, "", "0") else None
            if item_id is not None and await session.get(Item, item_id) is None:
                raise ValidatieFout(f"item {item_id} bestaat niet")
            setattr(werkplek, veld, item_id)

        werkplek.output_per_uur = output
        werkplek.capaciteit = capaciteit
        werkplek.opbrengst_2_kans = kans
        await session.commit()
        naam = werkplek.type

    log.info("Portal: werkplek '%s' bijgewerkt", naam)
    return web.json_response({"ok": True})


# ── Tiers ───────────────────────────────────────────────────────────────────

async def tiers_ophalen(request: web.Request) -> web.Response:
    async with async_session() as session:
        rijen = (await session.execute(select(Tier).order_by(Tier.id))).scalars().all()
        aantallen = dict(
            (await session.execute(select(PetSoort.tier_id, func.count()).group_by(PetSoort.tier_id))).all()
        )
    return web.json_response(
        [
            {
                "id": t.id,
                "naam": t.naam,
                "spawnkans": float(t.spawnkans),
                "stat_multiplier": float(t.stat_multiplier),
                "aantal_soorten": aantallen.get(t.id, 0),
            }
            for t in rijen
        ]
    )


async def tier_opslaan(request: web.Request) -> web.Response:
    tier_id = int(request.match_info["id"])
    data = await request.json()
    spawnkans = _getal(data, "spawnkans", minimum=0, maximum=1)
    multiplier = _getal(data, "stat_multiplier", minimum=0.1, maximum=99)
    naam = _tekst(data, "naam", max_lengte=32)

    async with async_session() as session:
        tier = await session.get(Tier, tier_id)
        if tier is None:
            raise ValidatieFout("tier bestaat niet")
        tier.naam = naam
        tier.spawnkans = spawnkans
        tier.stat_multiplier = multiplier
        await session.commit()

    log.info("Portal: tier %s bijgewerkt (spawnkans %s)", tier_id, spawnkans)
    return web.json_response({"ok": True})


# ── Pet-soorten ─────────────────────────────────────────────────────────────

def _soort_json(soort: PetSoort, aantal_gevangen: int) -> dict:
    return {
        "id": soort.id,
        "naam": soort.naam,
        "tier_id": soort.tier_id,
        "gevecht_basis": float(soort.gevecht_basis),
        "werk_basis": float(soort.werk_basis),
        "werkplek_voorkeur_id": soort.werkplek_voorkeur_id,
        "beschrijving": soort.beschrijving,
        "afbeelding_url": soort.afbeelding_url,
        "element": soort.element.value if soort.element else None,
        "aantal_gevangen": aantal_gevangen,
        # Verwijderen/hernoemen haalt 'm uit de PvE-tegenstanderpool.
        "is_wilde_tegenstander": soort.naam in WILDE_NAMEN,
    }


async def soorten_ophalen(request: web.Request) -> web.Response:
    async with async_session() as session:
        soorten = (
            await session.execute(select(PetSoort).order_by(PetSoort.tier_id, PetSoort.naam))
        ).scalars().all()
        gevangen = dict(
            (await session.execute(select(Huisdier.soort_id, func.count()).group_by(Huisdier.soort_id))).all()
        )
        werkplekken = (await session.execute(select(Werkplek).order_by(Werkplek.type))).scalars().all()
        tiers = (await session.execute(select(Tier).order_by(Tier.id))).scalars().all()

    return web.json_response(
        {
            "soorten": [_soort_json(s, gevangen.get(s.id, 0)) for s in soorten],
            "werkplekken": [{"id": w.id, "naam": w.type} for w in werkplekken],
            "tiers": [{"id": t.id, "naam": t.naam} for t in tiers],
            "elementen": [e.value for e in Element],
        }
    )


async def _soort_velden_lezen(session, data: dict) -> dict:
    tier_id = _getal(data, "tier_id", minimum=1, maximum=99, heel=True)
    if await session.get(Tier, tier_id) is None:
        raise ValidatieFout(f"tier {tier_id} bestaat niet")

    werkplek_ruw = data.get("werkplek_voorkeur_id")
    werkplek_id = int(werkplek_ruw) if werkplek_ruw not in (None, "", "0") else None
    if werkplek_id is not None and await session.get(Werkplek, werkplek_id) is None:
        raise ValidatieFout(f"werkplek {werkplek_id} bestaat niet")

    element_ruw = (data.get("element") or "").strip()
    if element_ruw and element_ruw not in {e.value for e in Element}:
        raise ValidatieFout(f"onbekend element '{element_ruw}'")

    return {
        "naam": _tekst(data, "naam", max_lengte=64),
        "tier_id": tier_id,
        "gevecht_basis": _getal(data, "gevecht_basis", minimum=1, maximum=9999),
        "werk_basis": _getal(data, "werk_basis", minimum=1, maximum=9999),
        "werkplek_voorkeur_id": werkplek_id,
        "beschrijving": _tekst(data, "beschrijving", max_lengte=256, verplicht=False),
        "afbeelding_url": _tekst(data, "afbeelding_url", max_lengte=512, verplicht=False),
        "element": Element(element_ruw) if element_ruw else None,
    }


async def soort_toevoegen(request: web.Request) -> web.Response:
    data = await request.json()
    async with async_session() as session:
        velden = await _soort_velden_lezen(session, data)
        bestaat = await session.scalar(select(PetSoort).where(PetSoort.naam == velden["naam"]))
        if bestaat is not None:
            raise ValidatieFout(f"er bestaat al een soort met de naam '{velden['naam']}'")
        soort = PetSoort(**velden)
        session.add(soort)
        await session.commit()
        await session.refresh(soort)
        resultaat = _soort_json(soort, 0)

    log.info("Portal: pet-soort '%s' toegevoegd (tier %s)", velden["naam"], velden["tier_id"])
    return web.json_response(resultaat)


async def soort_opslaan(request: web.Request) -> web.Response:
    soort_id = int(request.match_info["id"])
    data = await request.json()
    async with async_session() as session:
        soort = await session.get(PetSoort, soort_id)
        if soort is None:
            raise ValidatieFout("pet-soort bestaat niet")
        velden = await _soort_velden_lezen(session, data)

        botsing = await session.scalar(
            select(PetSoort).where(PetSoort.naam == velden["naam"], PetSoort.id != soort_id)
        )
        if botsing is not None:
            raise ValidatieFout(f"er bestaat al een andere soort met de naam '{velden['naam']}'")

        for veld, waarde in velden.items():
            setattr(soort, veld, waarde)
        await session.commit()

    log.info("Portal: pet-soort '%s' (#%s) bijgewerkt", velden["naam"], soort_id)
    return web.json_response({"ok": True})


async def soort_verwijderen(request: web.Request) -> web.Response:
    """Weigert zolang er nog gevangen exemplaren van bestaan: die zouden een
    FK naar een verdwenen soort houden en /lijst laten crashen."""
    soort_id = int(request.match_info["id"])
    async with async_session() as session:
        soort = await session.get(PetSoort, soort_id)
        if soort is None:
            raise ValidatieFout("pet-soort bestaat niet")
        aantal = await session.scalar(
            select(func.count()).select_from(Huisdier).where(Huisdier.soort_id == soort_id)
        )
        if aantal:
            raise ValidatieFout(
                f"'{soort.naam}' is {aantal}x gevangen door spelers en kan niet verwijderd worden. "
                "Pas de stats aan, of laat de eigenaren de pet eerst vrijlaten."
            )
        naam = soort.naam
        await session.delete(soort)
        await session.commit()

    log.info("Portal: pet-soort '%s' verwijderd", naam)
    return web.json_response({"ok": True})


# ── Kanalen (spawn + logs) ──────────────────────────────────────────────────

def _kanaal_naam(bot, channel_id: int) -> str | None:
    kanaal = bot.get_channel(channel_id)
    return getattr(kanaal, "name", None)


async def kanalen_ophalen(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    async with async_session() as session:
        spawn = (await session.execute(select(SpawnKanaal).order_by(SpawnKanaal.id))).scalars().all()
        logs = (
            await session.execute(select(LogChannel).order_by(LogChannel.categorie))
        ).scalars().all()

    # Alle tekstkanalen die de bot kent, zodat het panel een dropdown kan
    # tonen i.p.v. dat je ID's moet opzoeken.
    beschikbaar = []
    for guild in bot.guilds:
        for kanaal in guild.text_channels:
            beschikbaar.append(
                {"id": str(kanaal.id), "naam": kanaal.name, "server": guild.name, "guild_id": str(guild.id)}
            )

    return web.json_response(
        {
            "spawn": [
                {
                    "id": k.id,
                    "guild_id": str(k.guild_id),
                    "channel_id": str(k.channel_id),
                    "naam": _kanaal_naam(bot, k.channel_id),
                }
                for k in spawn
            ],
            "logs": [
                {
                    "id": k.id,
                    "guild_id": str(k.guild_id),
                    "categorie": k.categorie,
                    "channel_id": str(k.channel_id),
                    "naam": _kanaal_naam(bot, k.channel_id),
                }
                for k in logs
            ],
            "beschikbaar": beschikbaar,
            "log_categorieen": ["main", "vangst", "werk", "gevecht", "trade"],
        }
    )


def _vangen_cache_bijwerken(bot, channel_id: int, *, toevoegen: bool) -> None:
    """cogs/vangen.py houdt de spawn-kanaal-ID's in het geheugen (voor de
    activiteit-trigger op elk bericht). Zonder deze sync zou een via de portal
    toegevoegd kanaal pas na een herstart spawns geven."""
    cog = bot.get_cog("VangenCog")
    if cog is None or not hasattr(cog, "spawn_kanaal_ids"):
        return
    if toevoegen:
        cog.spawn_kanaal_ids.add(channel_id)
    else:
        cog.spawn_kanaal_ids.discard(channel_id)


async def spawnkanaal_toevoegen(request: web.Request) -> web.Response:
    data = await request.json()
    bot = request.app["bot"]
    channel_id = int(data["channel_id"])
    kanaal = bot.get_channel(channel_id)
    if kanaal is None:
        raise ValidatieFout("de bot kan dit kanaal niet zien")

    async with async_session() as session:
        bestaat = await session.scalar(
            select(SpawnKanaal).where(SpawnKanaal.channel_id == channel_id)
        )
        if bestaat is not None:
            raise ValidatieFout("dit kanaal is al een spawn-kanaal")
        session.add(SpawnKanaal(guild_id=kanaal.guild.id, channel_id=channel_id))
        await session.commit()

    _vangen_cache_bijwerken(bot, channel_id, toevoegen=True)
    log.info("Portal: spawn-kanaal #%s toegevoegd", kanaal.name)
    return web.json_response({"ok": True})


async def spawnkanaal_verwijderen(request: web.Request) -> web.Response:
    kanaal_id = int(request.match_info["id"])
    async with async_session() as session:
        rij = await session.get(SpawnKanaal, kanaal_id)
        if rij is None:
            raise ValidatieFout("spawn-kanaal bestaat niet")
        channel_id = rij.channel_id
        await session.delete(rij)
        await session.commit()

    _vangen_cache_bijwerken(request.app["bot"], channel_id, toevoegen=False)
    log.info("Portal: spawn-kanaal %s verwijderd", channel_id)
    return web.json_response({"ok": True})


async def logkanaal_opslaan(request: web.Request) -> web.Response:
    """Zelfde gedrag als /setlog: per (server, categorie) één kanaal."""
    data = await request.json()
    bot = request.app["bot"]
    categorie = _tekst(data, "categorie", max_lengte=32).lower()
    channel_id = int(data["channel_id"])
    kanaal = bot.get_channel(channel_id)
    if kanaal is None:
        raise ValidatieFout("de bot kan dit kanaal niet zien")

    async with async_session() as session:
        bestaand = await session.scalar(
            select(LogChannel).where(
                LogChannel.guild_id == kanaal.guild.id, LogChannel.categorie == categorie
            )
        )
        if bestaand is None:
            session.add(
                LogChannel(guild_id=kanaal.guild.id, categorie=categorie, channel_id=channel_id)
            )
        else:
            bestaand.channel_id = channel_id
        await session.commit()

    log.info("Portal: logkanaal '%s' -> #%s", categorie, kanaal.name)
    return web.json_response({"ok": True})


async def logkanaal_verwijderen(request: web.Request) -> web.Response:
    kanaal_id = int(request.match_info["id"])
    async with async_session() as session:
        rij = await session.get(LogChannel, kanaal_id)
        if rij is None:
            raise ValidatieFout("logkanaal bestaat niet")
        categorie = rij.categorie
        await session.delete(rij)
        await session.commit()

    log.info("Portal: logkanaal '%s' verwijderd", categorie)
    return web.json_response({"ok": True})


def routes_toevoegen(app: web.Application) -> None:
    # GET-routes hieronder zijn bewust open voor elke ingelogde sessie, niet
    # alleen admins (2026-07-30, "openheid voor spelers") — dit zijn precies
    # de balanswaarden die ook via /wiki en /critterdex publiek zijn, alleen
    # nu met de live cijfers erbij i.p.v. de bewust vage wiki-tekst. Elke
    # schrijf-actie blijft achter auth.vereist_admin.
    app.router.add_get("/api/instellingen", instellingen_ophalen)
    app.router.add_post("/api/instellingen", auth.vereist_admin(instellingen_opslaan))

    app.router.add_get("/api/items", items_ophalen)
    app.router.add_post("/api/items/{id}", auth.vereist_admin(item_opslaan))

    app.router.add_get("/api/werkplekken", werkplekken_ophalen)
    app.router.add_post("/api/werkplekken/{id}", auth.vereist_admin(werkplek_opslaan))

    app.router.add_get("/api/tiers", tiers_ophalen)
    app.router.add_post("/api/tiers/{id}", auth.vereist_admin(tier_opslaan))

    app.router.add_get("/api/soorten", soorten_ophalen)
    app.router.add_post("/api/soorten", auth.vereist_admin(soort_toevoegen))
    app.router.add_post("/api/soorten/{id}", auth.vereist_admin(soort_opslaan))
    app.router.add_delete("/api/soorten/{id}", auth.vereist_admin(soort_verwijderen))

    # Kanalen zijn operationele configuratie (spawn/log-kanalen, incl. namen
    # van alle servers waar de bot in zit), geen spelbalans — volledig
    # admin-only, ook het ophalen.
    app.router.add_get("/api/kanalen", auth.vereist_admin(kanalen_ophalen))
    app.router.add_post("/api/kanalen/spawn", auth.vereist_admin(spawnkanaal_toevoegen))
    app.router.add_delete("/api/kanalen/spawn/{id}", auth.vereist_admin(spawnkanaal_verwijderen))
    app.router.add_post("/api/kanalen/log", auth.vereist_admin(logkanaal_opslaan))
    app.router.add_delete("/api/kanalen/log/{id}", auth.vereist_admin(logkanaal_verwijderen))
