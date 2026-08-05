"""Portal-endpoints voor spelcontent: instellingen, items, werkplekken,
tiers, pet-soorten en kanalen.

Wat wél en niet aanpasbaar is, is een bewuste keuze (2026-07-29). Een aantal
namen staat hardcoded in de botcode en zou bij hernoemen stille bugs geven:

- **Item-namen**: komen als string terug in `VOERBAK_NIVEAUS` en de
  Mysterie voedselzak (cogs/verzorging.py) en de Extra match token-lookup in
  cogs/gevechten.py. Daarom zijn naam en type read-only en kan je geen items
  toevoegen/verwijderen — wel prijs, beschrijving en de voer-effecten. (De
  recept-kosten en de voer-effecten hingen ook aan itemnamen, maar die zitten
  sinds 2026-07-30 in de database: echte FK's in de `recepten`-tabel, en de
  kolommen honger_herstel/voerbak_vanaf op het item zelf.)
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
    Event,
    Huisdier,
    Instelling,
    Item,
    ItemType,
    LogChannel,
    PetSoort,
    Recept,
    SpawnKanaal,
    Tier,
    WerkCyclus,
    Werkplek,
)
from portal import auth
from utils import balans, events

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

    # Balans-cache herladen (2026-07-30, fase 2): portal draait in hetzelfde
    # proces als de bot, dus dit is een directe functieaanroep, geen polling.
    # Zonder dit zou een wijziging pas na een herstart effect hebben.
    await balans.laad()

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
                # Leeg = geen voer. Zie balans.voer_effecten()/voerbak_voer().
                "honger_herstel": i.honger_herstel,
                "voerbak_vanaf": i.voerbak_vanaf,
            }
            for i in rijen
        ]
    )


async def item_opslaan(request: web.Request) -> web.Response:
    """POST /api/items/{id} — prijs, beschrijving en de voer-effecten (zie
    module-docstring: naam en type blijven read-only)."""
    item_id = int(request.match_info["id"])
    data = await request.json()
    prijs = _getal(data, "prijs", minimum=0, maximum=1_000_000, heel=True)
    beschrijving = _tekst(data, "beschrijving", max_lengte=256, verplicht=False)

    # Leeg honger_herstel = "dit item is geen voer"; dan hoort er ook geen
    # voerbak-niveau bij, anders zou een voerbak een item pakken dat niets
    # doet (of erger: een KeyError geven in sync_stats_met_voerbak).
    ruw_herstel = data.get("honger_herstel")
    if ruw_herstel in (None, ""):
        honger_herstel, voerbak_vanaf = None, None
    else:
        honger_herstel = _getal(data, "honger_herstel", minimum=1, maximum=100, heel=True)
        voerbak_vanaf = data.get("voerbak_vanaf") or None
        if voerbak_vanaf not in (None, "simpel", "slim"):
            raise ValidatieFout("'voerbak_vanaf' moet leeg, 'simpel' of 'slim' zijn")

    async with async_session() as session:
        item = await session.get(Item, item_id)
        if item is None:
            raise ValidatieFout("item bestaat niet")
        item.prijs = prijs
        item.beschrijving = beschrijving
        item.honger_herstel = honger_herstel
        item.voerbak_vanaf = voerbak_vanaf
        await session.commit()
        naam = item.naam

    # Nodig sinds blok 5: de voer-effecten van dit item zitten in de
    # balans-cache (zie instellingen_opslaan voor de achtergrond).
    await balans.laad()

    log.info("Portal: item '%s' bijgewerkt (prijs %s)", naam, prijs)
    return web.json_response({"ok": True})


# ── Recepten (grondstofkosten per craftbaar item) ───────────────────────────

async def recepten_ophalen(request: web.Request) -> web.Response:
    async with async_session() as session:
        item_naam = Item.__table__.alias("item_naam")
        grondstof_naam = Item.__table__.alias("grondstof_naam")
        rijen = (
            await session.execute(
                select(
                    Recept.id, Recept.item_id, item_naam.c.naam,
                    Recept.grondstof_id, grondstof_naam.c.naam, Recept.aantal,
                )
                .join(item_naam, Recept.item_id == item_naam.c.id)
                .join(grondstof_naam, Recept.grondstof_id == grondstof_naam.c.id)
                .order_by(item_naam.c.naam, Recept.id)
            )
        ).all()

        # Alles wat als ingrediënt kan dienen (voor de dropdowns), en alle
        # koopbare items (om een recept aan te hangen).
        grondstoffen = (
            await session.execute(
                select(Item)
                .where(Item.type.in_([ItemType.grondstof, ItemType.materiaal]))
                .order_by(Item.naam)
            )
        ).scalars().all()
        koopbaar = (
            await session.execute(select(Item).where(Item.prijs > 0).order_by(Item.naam))
        ).scalars().all()

    per_item: dict[int, dict] = {}
    for recept_id, item_id, item_nm, grondstof_id, grondstof_nm, aantal in rijen:
        blok = per_item.setdefault(item_id, {"item_id": item_id, "naam": item_nm, "ingredienten": []})
        blok["ingredienten"].append(
            {"id": recept_id, "grondstof_id": grondstof_id, "naam": grondstof_nm, "aantal": aantal}
        )

    return web.json_response(
        {
            "recepten": list(per_item.values()),
            "grondstoffen": [{"id": i.id, "naam": i.naam} for i in grondstoffen],
            "koopbare_items": [{"id": i.id, "naam": i.naam} for i in koopbaar],
        }
    )


async def recept_opslaan(request: web.Request) -> web.Response:
    """POST /api/recepten/{item_id} — body: {"ingredienten": [{grondstof_id, aantal}, ...]}.

    Vervangt het volledige recept van dit item in één keer (delete + insert)
    i.p.v. per ingrediënt te patchen: een recept is een geheel, en zo kan de
    portal gewoon de hele rij-set posten zonder losse toevoeg-/verwijder-
    endpoints. Een lege lijst betekent "dit item kost geen grondstoffen meer"."""
    item_id = int(request.match_info["item_id"])
    data = await request.json()
    ruwe_ingredienten = data.get("ingredienten")
    if not isinstance(ruwe_ingredienten, list):
        raise ValidatieFout("'ingredienten' moet een lijst zijn")

    async with async_session() as session:
        item = await session.get(Item, item_id)
        if item is None:
            raise ValidatieFout("item bestaat niet")

        gezien: set[int] = set()
        nieuw: list[Recept] = []
        for index, ruw in enumerate(ruwe_ingredienten):
            if not isinstance(ruw, dict):
                raise ValidatieFout(f"ingrediënt {index + 1} is geen object")
            grondstof_id = int(ruw.get("grondstof_id") or 0)
            aantal = _getal(ruw, "aantal", minimum=1, maximum=10_000, heel=True)

            grondstof = await session.get(Item, grondstof_id)
            if grondstof is None:
                raise ValidatieFout(f"grondstof {grondstof_id} bestaat niet")
            if grondstof_id == item_id:
                raise ValidatieFout(f"**{item.naam}** kan zichzelf niet als ingrediënt hebben")
            if grondstof_id in gezien:
                raise ValidatieFout(f"**{grondstof.naam}** staat er twee keer in; tel ze samen op")
            gezien.add(grondstof_id)
            nieuw.append(Recept(item_id=item_id, grondstof_id=grondstof_id, aantal=aantal))

        await session.execute(delete(Recept).where(Recept.item_id == item_id))
        for rij in nieuw:
            session.add(rij)
        await session.commit()
        item_naam = item.naam

    await balans.laad()
    log.info("Portal: recept voor '%s' bijgewerkt (%d ingrediënten)", item_naam, len(nieuw))
    return web.json_response({"ok": True})


# ── Werk-cycli (shift-varianten) ────────────────────────────────────────────

async def werk_cycli_ophalen(request: web.Request) -> web.Response:
    async with async_session() as session:
        rijen = (
            await session.execute(select(WerkCyclus).order_by(WerkCyclus.volgorde))
        ).scalars().all()
    return web.json_response(
        [
            {
                "sleutel": c.sleutel,
                "label": c.label,
                "duur_uren": float(c.duur_uren),
                "energie_kost": c.energie_kost,
                "output_multiplier": float(c.output_multiplier),
                # Handig referentiegetal in het panel: hoe lang levert deze
                # shift "effectief" op (duur x multiplier), wat rechtstreeks
                # de grondstof- en XP-opbrengst bepaalt.
                "effectieve_uren": round(float(c.duur_uren) * float(c.output_multiplier), 2),
            }
            for c in rijen
        ]
    )


async def werk_cyclus_opslaan(request: web.Request) -> web.Response:
    """POST /api/werk-cycli/{sleutel} — label/duur/energie/multiplier.

    `sleutel` zelf is niet aanpasbaar: die staat in `Huisdier.werk_cyclus`
    van lopende shifts, dus hernoemen zou die shifts onvindbaar maken.
    Toevoegen/verwijderen kan om dezelfde reden niet."""
    sleutel = request.match_info["sleutel"]
    data = await request.json()
    label = _tekst(data, "label", max_lengte=32)
    duur = _getal(data, "duur_uren", minimum=0.01, maximum=168)  # max 1 week
    energie = _getal(data, "energie_kost", minimum=0, maximum=100, heel=True)
    multiplier = _getal(data, "output_multiplier", minimum=0.1, maximum=100)

    async with async_session() as session:
        cyclus = await session.get(WerkCyclus, sleutel)
        if cyclus is None:
            raise ValidatieFout("werk-cyclus bestaat niet")
        cyclus.label = label
        cyclus.duur_uren = duur
        cyclus.energie_kost = energie
        cyclus.output_multiplier = multiplier
        await session.commit()

    await balans.laad()
    log.info("Portal: werk-cyclus '%s' bijgewerkt (duur %s, energie %s)", sleutel, duur, energie)
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


# ── Chaos events ────────────────────────────────────────────────────────────

async def events_ophalen(request: web.Request) -> web.Response:
    """De lopende events, de laatste afgeronde, en de beschikbare types met
    hun huidige sterkte (zodat het panel kan tonen wat een event gaat doen
    vóór je 'm start)."""
    bot = request.app["bot"]
    async with async_session() as session:
        rijen = (
            await session.execute(select(Event).order_by(Event.gestart_op.desc()).limit(25))
        ).scalars().all()

    nu = events._nu()
    return web.json_response(
        {
            "types": [
                {
                    "sleutel": t.sleutel,
                    "naam": t.naam,
                    "emoji": t.emoji,
                    # `sterkte` is de rauwe factor (voor een incense 0.25);
                    # `sterkte_label` is wat een mens ervan moet begrijpen
                    # ("4x", want de drempel gaat juist omláág). Het panel
                    # toont het label, niet het rauwe getal.
                    "sterkte": t.sterkte(),
                    "sterkte_label": t.sterkte_tekst(t.sterkte()),
                    # Voorvulling voor het invoerveld: hetzelfde getal als in
                    # het label, maar zonder de "x" zodat het in een
                    # number-input past.
                    "sterkte_zichtbaar": round(t.naar_zichtbaar(t.sterkte()), 2),
                    "omgekeerd": t.omgekeerd,
                    "spawn_gebonden": t.spawn_gebonden,
                    "effect": t.effect_tekst(t.sterkte()),
                }
                for t in events.TYPES.values()
            ],
            "standaard_duur_minuten": events.standaard_duur_minuten(),
            "events": [
                {
                    "id": e.id,
                    "sleutel": e.sleutel,
                    "naam": events.TYPES[e.sleutel].naam if e.sleutel in events.TYPES else e.sleutel,
                    "emoji": events.TYPES[e.sleutel].emoji if e.sleutel in events.TYPES else "❓",
                    "sterkte": float(e.sterkte),
                    "sterkte_label": (
                        events.TYPES[e.sleutel].sterkte_tekst(float(e.sterkte))
                        if e.sleutel in events.TYPES
                        else f"{float(e.sterkte)}x"
                    ),
                    # Zin die uitlegt wat dit event dóét, met de sterkte
                    # waarmee het gestart is (niet de huidige instelling).
                    "effect": (
                        events.TYPES[e.sleutel].effect_tekst(float(e.sterkte))
                        if e.sleutel in events.TYPES
                        else ""
                    ),
                    "actief": e.eindigt_op > nu,
                    "gestart_op": e.gestart_op.isoformat(),
                    "eindigt_op": e.eindigt_op.isoformat(),
                    # Waar het event geldt (None = overal) en waar het extra
                    # is aangekondigd; twee verschillende dingen.
                    "kanaal": _kanaal_naam(bot, e.kanaal_id) if e.kanaal_id else None,
                    "aankondiging_kanaal": (
                        _kanaal_naam(bot, e.aankondiging_kanaal_id)
                        if e.aankondiging_kanaal_id
                        else None
                    ),
                }
                for e in rijen
            ],
        }
    )


async def event_starten(request: web.Request) -> web.Response:
    """POST /api/events — start een chaos-event.

    Bewust geen tweede event van hetzelfde type tegelijk: twee incenses
    zouden elkaar niet versterken (`actief()` pakt er één) maar wel
    verwarrend zijn in de aankondigingen. Verschillende types naast elkaar
    mag wél — die raken elk een ander systeem."""
    data = await request.json()
    sleutel = (data.get("sleutel") or "").strip()
    if sleutel not in events.TYPES:
        raise ValidatieFout(f"onbekend event-type '{sleutel}'")
    type_ = events.TYPES[sleutel]
    duur = _getal(data, "duur_minuten", minimum=1, maximum=7 * 24 * 60, heel=True)

    bot = request.app["bot"]

    def _kanaal(veld: str) -> int | None:
        ruw = data.get(veld) or None
        if ruw is None:
            return None
        try:
            kanaal_id = int(ruw)
        except (TypeError, ValueError):
            raise ValidatieFout(f"ongeldig kanaal-ID bij '{veld}'")
        if bot.get_channel(kanaal_id) is None:
            raise ValidatieFout("de bot kan dit kanaal niet zien")
        return kanaal_id

    # Waar het event geldt. Alleen spawn-gebonden types kennen dit: een
    # muntregen "in dit kanaal" bestaat niet, want gevechten en shifts hangen
    # niet aan een kanaal.
    kanaal_id = _kanaal("kanaal_id") if type_.spawn_gebonden else None

    # Een tweede event van hetzelfde type mag niet in hetzelfde kanaal, maar
    # wél in een ánder kanaal — dat is precies het nut van per-kanaal events
    # (bijv. een incense in het event-kanaal terwijl er al eentje elders
    # loopt). Een server-breed event (kanaal_id None) botst met alles van
    # dat type, want dat overlapt per definitie.
    if events.is_actief(sleutel, kanaal_id):
        raise ValidatieFout(
            f"{type_.naam} loopt hier al — stop 'm eerst als je opnieuw wilt beginnen"
        )
    if kanaal_id is not None and events.is_actief(sleutel):
        raise ValidatieFout(
            f"{type_.naam} loopt al server-breed, dus ook in dit kanaal"
        )

    # De sterkte wordt ingevoerd in de zichtbare eenheid ("4x sneller"), niet
    # als rauwe factor — die is voor een incense 0.25 en dat leest verkeerd
    # (2026-08-05, feedback van de gebruiker: "0.25 klinkt niet als 4x").
    ruw_sterkte = data.get("sterkte")
    if ruw_sterkte in (None, ""):
        sterkte = None
    else:
        zichtbaar = _getal(data, "sterkte", minimum=1, maximum=50)
        sterkte = type_.naar_factor(zichtbaar)

    async with async_session() as session:
        event = await events.start(
            session,
            sleutel,
            duur_minuten=duur,
            sterkte=sterkte,
            kanaal_id=kanaal_id,
            aankondiging_kanaal_id=_kanaal("aankondiging_kanaal_id"),
            gestart_door=request["sessie"].discord_id,
        )
        await session.commit()
        session.expunge_all()

    await events.laad()
    # Aankondigen ná de commit: de portal draait in hetzelfde proces als de
    # bot, dus dit is een gewone aanroep. Als Discord hapert loopt het event
    # gewoon door, alleen de melding ontbreekt dan.
    from cogs.events import kondig_start_aan

    await kondig_start_aan(bot, event)

    log.info(
        "Portal: event '%s' gestart voor %d minuten (kanaal %s, sterkte %s)",
        sleutel, duur, kanaal_id or "overal", event.sterkte,
    )
    return web.json_response({"ok": True, "id": event.id})


async def event_stoppen(request: web.Request) -> web.Response:
    """POST /api/events/{id}/stop — beëindigt een lopend event meteen.

    De rij blijft staan (eindigt_op gaat naar nu) i.p.v. verwijderd te
    worden: zo blijft de geschiedenis zichtbaar en pikt de achtergrondtaak
    de "voorbij"-aankondiging alsnog op."""
    event_id = int(request.match_info["id"])
    async with async_session() as session:
        event = await events.stop(session, event_id)
        if event is None:
            raise ValidatieFout("event bestaat niet")
        sleutel = event.sleutel
        await session.commit()

    await events.laad()
    log.info("Portal: event '%s' (#%d) handmatig gestopt", sleutel, event_id)
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

    app.router.add_get("/api/recepten", recepten_ophalen)
    app.router.add_post("/api/recepten/{item_id}", auth.vereist_admin(recept_opslaan))

    app.router.add_get("/api/werk-cycli", werk_cycli_ophalen)
    app.router.add_post("/api/werk-cycli/{sleutel}", auth.vereist_admin(werk_cyclus_opslaan))

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
    app.router.add_get("/api/events", events_ophalen)
    app.router.add_post("/api/events", auth.vereist_admin(event_starten))
    app.router.add_post("/api/events/{id}/stop", auth.vereist_admin(event_stoppen))
    app.router.add_get("/api/kanalen", auth.vereist_admin(kanalen_ophalen))
    app.router.add_post("/api/kanalen/spawn", auth.vereist_admin(spawnkanaal_toevoegen))
    app.router.add_delete("/api/kanalen/spawn/{id}", auth.vereist_admin(spawnkanaal_verwijderen))
    app.router.add_post("/api/kanalen/log", auth.vereist_admin(logkanaal_opslaan))
    app.router.add_delete("/api/kanalen/log/{id}", auth.vereist_admin(logkanaal_verwijderen))
