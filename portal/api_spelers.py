"""Portal-endpoints voor spelerbeheer: spelers, hun pets, inventaris, clans
en een statistiek-overzicht (2026-07-29).

Hergebruikt bewust de bestaande inventaris-helpers uit cogs/werk.py
(`_voeg_toe_aan_inventaris` / `_neem_uit_inventaris`) i.p.v. eigen SQL: die
zijn atomisch, en dat was precies de bug die bij de codebase-review van
2026-07-28 items uit het niets liet ontstaan.
"""

import logging

from aiohttp import web
from sqlalchemy import delete, func, select

from cogs.werk import _neem_uit_inventaris, _voeg_toe_aan_inventaris
from db.engine import async_session
from db.models import (
    Clan,
    Huisdier,
    InventarisItem,
    Item,
    PetSoort,
    PetStatus,
    Speler,
    Tier,
)
from portal import auth
from portal.api_content import ValidatieFout, _getal, _tekst
from utils.stats import sync_stats_met_voerbak

log = logging.getLogger("chaos_critters")

SPELERS_PER_PAGINA = 25


async def _naam_van(bot, discord_id: int) -> str:
    """Discord-weergavenaam, met de ID als terugval (de bot heeft de
    members-intent niet, dus de cache is vaak leeg — een mislukte fetch mag
    het overzicht niet breken)."""
    gebruiker = bot.get_user(discord_id)
    if gebruiker is not None:
        return gebruiker.display_name
    try:
        gebruiker = await bot.fetch_user(discord_id)
        return gebruiker.display_name
    except Exception:
        return str(discord_id)


# ── Statistieken (dashboard) ────────────────────────────────────────────────

async def statistieken(request: web.Request) -> web.Response:
    async with async_session() as session:
        aantal_spelers = await session.scalar(select(func.count()).select_from(Speler))
        aantal_pets = await session.scalar(select(func.count()).select_from(Huisdier))
        aantal_soorten = await session.scalar(select(func.count()).select_from(PetSoort))
        aantal_clans = await session.scalar(select(func.count()).select_from(Clan))
        totaal_coins = await session.scalar(select(func.coalesce(func.sum(Speler.currency), 0)))
        aan_het_werk = await session.scalar(
            select(func.count()).select_from(Huisdier).where(Huisdier.status == PetStatus.werkplek)
        )

        # Populairste soorten (meest gevangen), en hoeveel soorten nog nooit
        # gevangen zijn — handig om te zien of nieuwe soorten wel opduiken.
        top_soorten = (
            await session.execute(
                select(PetSoort.naam, func.count(Huisdier.id))
                .join(Huisdier, Huisdier.soort_id == PetSoort.id)
                .group_by(PetSoort.naam)
                .order_by(func.count(Huisdier.id).desc())
                .limit(5)
            )
        ).all()
        nooit_gevangen = await session.scalar(
            select(func.count())
            .select_from(PetSoort)
            .where(~PetSoort.id.in_(select(Huisdier.soort_id).distinct()))
        )
        rijkste = (
            await session.execute(
                select(Speler.discord_id, Speler.currency).order_by(Speler.currency.desc()).limit(5)
            )
        ).all()

    bot = request.app["bot"]
    return web.json_response(
        {
            "spelers": aantal_spelers,
            "pets": aantal_pets,
            "soorten": aantal_soorten,
            "soorten_nooit_gevangen": nooit_gevangen,
            "clans": aantal_clans,
            "totaal_coins": totaal_coins,
            "pets_aan_het_werk": aan_het_werk,
            "top_soorten": [{"naam": naam, "aantal": aantal} for naam, aantal in top_soorten],
            "rijkste_spelers": [
                {"naam": await _naam_van(bot, did), "coins": coins} for did, coins in rijkste
            ],
        }
    )


# ── Spelers ─────────────────────────────────────────────────────────────────

async def spelers_ophalen(request: web.Request) -> web.Response:
    """GET /api/spelers?q=... — zoekt op Discord-ID; namen worden per speler
    opgehaald bij de bot, dus zoeken op naam gebeurt in het panel zelf op de
    al geladen lijst."""
    zoek = (request.query.get("q") or "").strip()

    async with async_session() as session:
        stmt = select(Speler).order_by(Speler.currency.desc())
        if zoek.isdigit():
            stmt = stmt.where(Speler.discord_id == int(zoek))
        spelers = (await session.execute(stmt.limit(200))).scalars().all()

        pet_aantallen = dict(
            (
                await session.execute(
                    select(Huisdier.eigenaar_id, func.count()).group_by(Huisdier.eigenaar_id)
                )
            ).all()
        )
        clans = {c.id: c.naam for c in (await session.execute(select(Clan))).scalars().all()}

    bot = request.app["bot"]
    return web.json_response(
        [
            {
                "discord_id": str(s.discord_id),
                "naam": await _naam_van(bot, s.discord_id),
                "currency": s.currency,
                "mmr": s.mmr,
                "aantal_pets": pet_aantallen.get(s.discord_id, 0),
                "clan": clans.get(s.clan_id),
                "ranked_pogingen_vandaag": s.ranked_pogingen_vandaag,
            }
            for s in spelers
        ]
    )


async def speler_detail(request: web.Request) -> web.Response:
    discord_id = int(request.match_info["discord_id"])
    async with async_session() as session:
        speler = await session.get(Speler, discord_id)
        if speler is None:
            raise ValidatieFout("speler bestaat niet")

        pets = (
            await session.execute(
                select(Huisdier, PetSoort, Tier)
                .join(PetSoort, Huisdier.soort_id == PetSoort.id)
                .join(Tier, Huisdier.tier_id == Tier.id)
                .where(Huisdier.eigenaar_id == discord_id)
                .order_by(Huisdier.volgnummer)
            )
        ).all()

        # Stats bijwerken voordat we ze tonen: honger/energie vervallen lazy,
        # dus zonder dit zou het panel verouderde waarden laten zien.
        for pet, _soort, _tier in pets:
            await sync_stats_met_voerbak(session, pet)
        await session.commit()

        inventaris = (
            await session.execute(
                select(InventarisItem, Item)
                .join(Item, InventarisItem.item_id == Item.id)
                .where(InventarisItem.speler_id == discord_id, InventarisItem.aantal > 0)
                .order_by(Item.type, Item.naam)
            )
        ).all()

        clan = await session.get(Clan, speler.clan_id) if speler.clan_id else None
        alle_items = (await session.execute(select(Item).order_by(Item.type, Item.naam))).scalars().all()

        resultaat = {
            "discord_id": str(speler.discord_id),
            "naam": await _naam_van(request.app["bot"], discord_id),
            "currency": speler.currency,
            "mmr": speler.mmr,
            "ranked_pogingen_vandaag": speler.ranked_pogingen_vandaag,
            "clan": {"id": clan.id, "naam": clan.naam} if clan else None,
            "aangemaakt": speler.created_at.isoformat() if speler.created_at else None,
            "pets": [
                {
                    "id": pet.id,
                    "volgnummer": pet.volgnummer,
                    "naam": pet.naam,
                    "soort": soort.naam,
                    "tier": tier.naam,
                    "element": soort.element.value if soort.element else None,
                    "level": pet.level,
                    "xp": pet.xp,
                    "honger": pet.honger,
                    "energie": pet.energie,
                    "status": pet.status.value,
                    "geblesseerd_tot": pet.geblesseerd_tot.isoformat() if pet.geblesseerd_tot else None,
                    "voerbak_niveau": pet.voerbak_niveau,
                    "zelfreinigend_actief": pet.zelfreinigend_actief,
                    "gevecht_genen": float(pet.gevecht_genen),
                    "werk_genen": float(pet.werk_genen),
                }
                for pet, soort, tier in pets
            ],
            "inventaris": [
                {"item_id": item.id, "naam": item.naam, "type": item.type.value, "aantal": inv.aantal}
                for inv, item in inventaris
            ],
            "alle_items": [{"id": i.id, "naam": i.naam, "type": i.type.value} for i in alle_items],
        }

    return web.json_response(resultaat)


async def speler_opslaan(request: web.Request) -> web.Response:
    discord_id = int(request.match_info["discord_id"])
    data = await request.json()
    currency = _getal(data, "currency", minimum=0, maximum=1_000_000_000, heel=True)
    mmr = _getal(data, "mmr", minimum=0, maximum=100_000, heel=True)
    pogingen = _getal(data, "ranked_pogingen_vandaag", minimum=0, maximum=10_000, heel=True)

    async with async_session() as session:
        speler = await session.get(Speler, discord_id)
        if speler is None:
            raise ValidatieFout("speler bestaat niet")
        speler.currency = currency
        speler.mmr = mmr
        speler.ranked_pogingen_vandaag = pogingen
        await session.commit()

    log.info("Portal: speler %s bijgewerkt (coins %s, mmr %s)", discord_id, currency, mmr)
    return web.json_response({"ok": True})


async def speler_item_aanpassen(request: web.Request) -> web.Response:
    """POST /api/spelers/{discord_id}/items — body: {item_id, aantal}.
    Een negatief aantal neemt items af."""
    discord_id = int(request.match_info["discord_id"])
    data = await request.json()
    item_id = _getal(data, "item_id", minimum=1, maximum=10**9, heel=True)
    aantal = _getal(data, "aantal", minimum=-10_000, maximum=10_000, heel=True)
    if aantal == 0:
        raise ValidatieFout("aantal mag niet 0 zijn")

    async with async_session() as session:
        if await session.get(Speler, discord_id) is None:
            raise ValidatieFout("speler bestaat niet")
        item = await session.get(Item, item_id)
        if item is None:
            raise ValidatieFout("item bestaat niet")

        if aantal > 0:
            await _voeg_toe_aan_inventaris(session, discord_id, item_id, aantal)
        elif not await _neem_uit_inventaris(session, discord_id, item_id, -aantal):
            raise ValidatieFout(f"speler heeft geen {-aantal}x {item.naam}")
        await session.commit()
        naam = item.naam

    log.info("Portal: speler %s kreeg %+d x %s", discord_id, aantal, naam)
    return web.json_response({"ok": True})


# ── Pets ────────────────────────────────────────────────────────────────────

async def pet_opslaan(request: web.Request) -> web.Response:
    pet_id = int(request.match_info["id"])
    data = await request.json()
    naam = _tekst(data, "naam", max_lengte=32)
    honger = _getal(data, "honger", minimum=0, maximum=100, heel=True)
    energie = _getal(data, "energie", minimum=0, maximum=100, heel=True)
    level = _getal(data, "level", minimum=1, maximum=999, heel=True)
    xp = _getal(data, "xp", minimum=0, maximum=10**9, heel=True)

    async with async_session() as session:
        pet = await session.get(Huisdier, pet_id)
        if pet is None:
            raise ValidatieFout("pet bestaat niet")

        pet.naam = naam
        pet.honger = honger
        pet.energie = energie
        pet.level = level
        pet.xp = xp
        if data.get("blessure_opheffen"):
            pet.geblesseerd_tot = None
        # Van het werk halen: dezelfde velden leegmaken als /werk doet bij het
        # ophalen van een shift, anders blijft de pet in een halve staat hangen.
        if data.get("van_werk_halen") and pet.status == PetStatus.werkplek:
            pet.status = PetStatus.rust
            pet.werkplek_type_id = None
            pet.werk_cyclus = None
            pet.werk_gestart_op = None
            pet.werk_kanaal_id = None
        await session.commit()

    log.info("Portal: pet #%s ('%s') bijgewerkt", pet_id, naam)
    return web.json_response({"ok": True})


async def pet_verwijderen(request: web.Request) -> web.Response:
    pet_id = int(request.match_info["id"])
    async with async_session() as session:
        pet = await session.get(Huisdier, pet_id)
        if pet is None:
            raise ValidatieFout("pet bestaat niet")
        naam, eigenaar = pet.naam, pet.eigenaar_id
        await session.delete(pet)
        await session.commit()

    log.info("Portal: pet '%s' (#%s) van speler %s verwijderd", naam, pet_id, eigenaar)
    return web.json_response({"ok": True})


# ── Clans ───────────────────────────────────────────────────────────────────

async def clans_ophalen(request: web.Request) -> web.Response:
    async with async_session() as session:
        clans = (
            await session.execute(select(Clan).order_by(Clan.totale_werk_opbrengst.desc()))
        ).scalars().all()
        leden = dict(
            (
                await session.execute(
                    select(Speler.clan_id, func.count())
                    .where(Speler.clan_id.is_not(None))
                    .group_by(Speler.clan_id)
                )
            ).all()
        )

    bot = request.app["bot"]
    return web.json_response(
        [
            {
                "id": c.id,
                "naam": c.naam,
                "oprichter": await _naam_van(bot, c.oprichter_id),
                "oprichter_id": str(c.oprichter_id),
                "leden": leden.get(c.id, 0),
                "totale_werk_opbrengst": c.totale_werk_opbrengst,
            }
            for c in clans
        ]
    )


async def clan_verwijderen(request: web.Request) -> web.Response:
    """Ontbindt een clan; leden worden clanloos (zelfde effect als
    /clan-ontbinden, maar zonder dat je de oprichter hoeft te zijn)."""
    clan_id = int(request.match_info["id"])
    async with async_session() as session:
        clan = await session.get(Clan, clan_id)
        if clan is None:
            raise ValidatieFout("clan bestaat niet")
        naam = clan.naam
        await session.execute(
            Speler.__table__.update().where(Speler.clan_id == clan_id).values(clan_id=None)
        )
        await session.execute(delete(Clan).where(Clan.id == clan_id))
        await session.commit()

    log.info("Portal: clan '%s' ontbonden", naam)
    return web.json_response({"ok": True})


def routes_toevoegen(app: web.Application) -> None:
    # Statistieken en de clan-lijst zijn bewust open voor elke ingelogde
    # sessie (2026-07-30, "openheid voor spelers") — inclusief de "rijkste
    # spelers"-lijst in statistieken, op expliciet verzoek van de gebruiker
    # (volledige transparantie i.p.v. dat verbergen). De clan-lijst toont
    # niets dat niet al via /clan-leaderboard en /clan-info publiek is.
    app.router.add_get("/api/statistieken", statistieken)
    app.router.add_get("/api/clans", clans_ophalen)
    app.router.add_delete("/api/clans/{id}", auth.vereist_admin(clan_verwijderen))

    # Individuele spelersaccounts (coins/MMR/inventaris/pets van specifieke
    # spelers) zijn geen "spelbalans" maar privacygevoelige accountdata —
    # volledig admin-only, ook het ophalen.
    app.router.add_get("/api/spelers", auth.vereist_admin(spelers_ophalen))
    app.router.add_get("/api/spelers/{discord_id}", auth.vereist_admin(speler_detail))
    app.router.add_post("/api/spelers/{discord_id}", auth.vereist_admin(speler_opslaan))
    app.router.add_post("/api/spelers/{discord_id}/items", auth.vereist_admin(speler_item_aanpassen))

    app.router.add_post("/api/pets/{id}", auth.vereist_admin(pet_opslaan))
    app.router.add_delete("/api/pets/{id}", auth.vereist_admin(pet_verwijderen))
