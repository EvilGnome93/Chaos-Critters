"""Check van het web-adminpanel (portal/, 2026-07-29).

Draait de echte aiohttp-app via aiohttp's TestServer, met een nep-bot en een
zelf aangemaakte sessie in de database. Test dus het volledige pad:
auth-middleware -> route -> validatie -> database.

De Discord OAuth-flow zelf (redirect naar Discord en terug) is niet te testen
zonder echte Discord-credentials; die stap moet handmatig gecontroleerd worden.
Wat hier wél getest wordt: dat /api/* zonder geldige sessie dichtzit, en dat
elke endpoint met een geldige sessie doet wat hij belooft.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import delete, select

from db.engine import async_session
from db.models import (
    Clan,
    Huisdier,
    Instelling,
    InventarisItem,
    Item,
    PetSoort,
    PetStatus,
    PortalSessie,
    Speler,
    Tier,
    Werkplek,
)
from portal.server import maak_app

SPELER = 999999999999999981
TOKEN = "test-token-portal-abcdefghijklmnop"
TESTSOORT = "PortalTestdier"


def nep_bot() -> MagicMock:
    """Minimale bot-dubbel: alleen wat de portal-endpoints aanraken."""
    bot = MagicMock()
    bot.user = "ChaosCrittersTest#0001"

    kanaal = MagicMock()
    kanaal.id = 424242424242
    kanaal.name = "portal-testkanaal"
    kanaal.guild = MagicMock()
    kanaal.guild.id = 111111111111
    kanaal.guild.name = "Testserver"

    guild = MagicMock()
    guild.id = 111111111111
    guild.name = "Testserver"
    guild.text_channels = [kanaal]

    bot.guilds = [guild]
    bot.get_channel = lambda cid: kanaal if cid == kanaal.id else None
    bot.get_user = lambda _uid: None
    bot.fetch_user = AsyncMock(side_effect=Exception("geen Discord in de test"))

    # cogs/vangen.py houdt spawn-kanalen in het geheugen; de portal moet die
    # cache bijwerken. Een echte set zodat we dat kunnen controleren.
    vangen_cog = MagicMock()
    vangen_cog.spawn_kanaal_ids = set()
    bot.get_cog = lambda naam: vangen_cog if naam == "VangenCog" else None
    bot._vangen_cog = vangen_cog
    return bot


async def _maak_sessie() -> None:
    async with async_session() as session:
        await session.execute(delete(PortalSessie).where(PortalSessie.token == TOKEN))
        session.add(
            PortalSessie(
                token=TOKEN,
                discord_id=SPELER,
                weergavenaam="Portaltester",
                verloopt_op=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1),
            )
        )
        await session.commit()


async def _opruimen(bot) -> None:
    async with async_session() as session:
        await session.execute(delete(PortalSessie).where(PortalSessie.token == TOKEN))
        await session.execute(delete(Huisdier).where(Huisdier.eigenaar_id == SPELER))
        await session.execute(delete(InventarisItem).where(InventarisItem.speler_id == SPELER))
        await session.execute(delete(Speler).where(Speler.discord_id == SPELER))
        await session.execute(delete(PetSoort).where(PetSoort.naam == TESTSOORT))
        from db.models import SpawnKanaal

        await session.execute(delete(SpawnKanaal).where(SpawnKanaal.channel_id == 424242424242))
        await session.commit()


async def test_auth_dicht(client) -> None:
    print("-- /api/* zit dicht zonder geldige sessie --")
    for pad in ("/api/verify", "/api/instellingen", "/api/spelers", "/api/statistieken"):
        resp = await client.get(pad)
        assert resp.status == 401, f"{pad} gaf {resp.status}, verwacht 401"
    print("Alle geteste endpoints geven 401 zonder token.")

    resp = await client.get("/api/instellingen", headers={"Authorization": "Bearer onzin-token"})
    assert resp.status == 401
    print("Een onbekend token geeft ook 401.")

    # Het loginscherm en de healthcheck moeten juist wél open zijn.
    resp = await client.get("/health")
    assert resp.status == 200
    resp = await client.get("/")
    assert resp.status == 200, "admin.html moet zonder login te bereiken zijn (dat is de loginpagina)"
    print("Loginpagina en /health zijn wel publiek.")


async def test_verify_en_instellingen(client, auth) -> None:
    print("\n-- /api/verify + instellingen lezen/schrijven --")
    resp = await client.get("/api/verify", headers=auth)
    assert resp.status == 200
    info = await resp.json()
    print(f"Ingelogd als: {info['naam']}")
    assert info["naam"] == "Portaltester"

    resp = await client.get("/api/instellingen", headers=auth)
    instellingen = await resp.json()
    origineel = {i["sleutel"]: i["waarde"] for i in instellingen}
    print(f"Instellingen gevonden: {sorted(origineel)}")
    assert "ranked_gratis_per_dag" in origineel

    # Wijzigen en terugzetten, zodat de live dev-DB ongemoeid blijft.
    nieuw = str(int(origineel["ranked_gratis_per_dag"]) + 1)
    resp = await client.post(
        "/api/instellingen", headers=auth, json={"ranked_gratis_per_dag": nieuw}
    )
    assert resp.status == 200, await resp.text()
    async with async_session() as session:
        waarde = await session.scalar(
            select(Instelling.waarde).where(Instelling.sleutel == "ranked_gratis_per_dag")
        )
    print(f"ranked_gratis_per_dag: {origineel['ranked_gratis_per_dag']} -> {waarde}")
    assert waarde == nieuw

    resp = await client.post(
        "/api/instellingen",
        headers=auth,
        json={"ranked_gratis_per_dag": origineel["ranked_gratis_per_dag"]},
    )
    assert resp.status == 200
    print("Teruggezet naar de oorspronkelijke waarde.")

    resp = await client.post("/api/instellingen", headers=auth, json={"bestaat_niet": "1"})
    assert resp.status == 400
    print(f"Onbekende sleutel geweigerd: {(await resp.json())['error']}")


async def test_validatie(client, auth) -> None:
    print("\n-- Validatie weigert onzin-waarden --")
    async with async_session() as session:
        werkplek = await session.scalar(select(Werkplek).limit(1))
        tier = await session.scalar(select(Tier).limit(1))
        werkplek_id, tier_id = werkplek.id, tier.id
        origineel = {
            "output_per_uur": float(werkplek.output_per_uur),
            "capaciteit": werkplek.capaciteit,
            "opbrengst_2_kans": float(werkplek.opbrengst_2_kans),
            "opbrengst_item_id": werkplek.opbrengst_item_id,
            "opbrengst_item_2_id": werkplek.opbrengst_item_2_id,
        }

    gevallen = [
        (f"/api/werkplekken/{werkplek_id}", {**origineel, "capaciteit": 0}, "capaciteit 0"),
        (f"/api/werkplekken/{werkplek_id}", {**origineel, "opbrengst_2_kans": 5}, "kans 500%"),
        (f"/api/werkplekken/{werkplek_id}", {**origineel, "output_per_uur": -1}, "negatieve output"),
        (f"/api/tiers/{tier_id}", {"naam": "X", "spawnkans": 2, "stat_multiplier": 1}, "spawnkans 200%"),
        (f"/api/tiers/{tier_id}", {"naam": "", "spawnkans": 0.5, "stat_multiplier": 1}, "lege naam"),
    ]
    for pad, body, beschrijving in gevallen:
        resp = await client.post(pad, headers=auth, json=body)
        assert resp.status == 400, f"{beschrijving} werd geaccepteerd ({resp.status})!"
        print(f"  geweigerd ({beschrijving}): {(await resp.json())['error']}")

    # En een geldige wijziging moet wél lukken (en identiek blijven).
    resp = await client.post(f"/api/werkplekken/{werkplek_id}", headers=auth, json=origineel)
    assert resp.status == 200, await resp.text()
    print("Geldige werkplek-update werkt (waarden ongewijzigd teruggezet).")


async def test_soorten_crud(client, auth) -> None:
    print("\n-- Pet-soorten: toevoegen, bewerken, verwijderen --")
    resp = await client.get("/api/soorten", headers=auth)
    data = await resp.json()
    aantal_voor = len(data["soorten"])
    print(f"Soorten in de database: {aantal_voor}")

    nieuw = {
        "naam": TESTSOORT,
        "tier_id": data["tiers"][0]["id"],
        "gevecht_basis": 40,
        "werk_basis": 60,
        "werkplek_voorkeur_id": data["werkplekken"][0]["id"],
        "beschrijving": "Alleen voor de portal-test",
        "afbeelding_url": "",
        "element": "grond",
    }
    resp = await client.post("/api/soorten", headers=auth, json=nieuw)
    assert resp.status == 200, await resp.text()
    soort = await resp.json()
    soort_id = soort["id"]
    print(f"Toegevoegd: '{soort['naam']}' (#{soort_id}), element {soort['element']}")

    # Dubbele naam moet geweigerd worden.
    resp = await client.post("/api/soorten", headers=auth, json=nieuw)
    assert resp.status == 400
    print(f"Dubbele naam geweigerd: {(await resp.json())['error']}")

    # Onbekend element ook.
    resp = await client.post(
        "/api/soorten", headers=auth, json={**nieuw, "naam": "PortalTestdier2", "element": "modder"}
    )
    assert resp.status == 400
    print(f"Onbekend element geweigerd: {(await resp.json())['error']}")

    resp = await client.post(
        f"/api/soorten/{soort_id}", headers=auth, json={**nieuw, "gevecht_basis": 80}
    )
    assert resp.status == 200, await resp.text()
    async with async_session() as session:
        bijgewerkt = await session.get(PetSoort, soort_id)
        print(f"gevecht_basis 40 -> {float(bijgewerkt.gevecht_basis)}")
        assert float(bijgewerkt.gevecht_basis) == 80

    # Een gevangen exemplaar moet verwijderen blokkeren (anders houdt Huisdier
    # een FK naar een verdwenen soort).
    async with async_session() as session:
        session.add(Speler(discord_id=SPELER, currency=500, mmr=1000, volgend_pet_nummer=1))
        await session.commit()
        speler = await session.get(Speler, SPELER)
        soort_obj = await session.get(PetSoort, soort_id)
        session.add(
            Huisdier(
                eigenaar_id=SPELER, soort_id=soort_id, tier_id=soort_obj.tier_id,
                naam="PortalPet", volgnummer=speler.volgend_pet_nummer,
                gevecht_genen=50, werk_genen=50, status=PetStatus.rust, honger=80, energie=80,
            )
        )
        speler.volgend_pet_nummer += 1
        await session.commit()

    resp = await client.delete(f"/api/soorten/{soort_id}", headers=auth)
    assert resp.status == 400
    print(f"Verwijderen geblokkeerd: {(await resp.json())['error']}")

    async with async_session() as session:
        await session.execute(delete(Huisdier).where(Huisdier.eigenaar_id == SPELER))
        await session.commit()

    resp = await client.delete(f"/api/soorten/{soort_id}", headers=auth)
    assert resp.status == 200, await resp.text()
    async with async_session() as session:
        assert await session.get(PetSoort, soort_id) is None
    print("Na het vrijlaten van de pet is verwijderen wel toegestaan.")


async def test_spelerbeheer(client, auth) -> None:
    print("\n-- Spelerbeheer: saldo, items, pets --")
    async with async_session() as session:
        if await session.get(Speler, SPELER) is None:
            session.add(Speler(discord_id=SPELER, currency=500, mmr=1000, volgend_pet_nummer=1))
            await session.commit()
        speler = await session.get(Speler, SPELER)
        soort = await session.scalar(select(PetSoort).limit(1))
        pet = Huisdier(
            eigenaar_id=SPELER, soort_id=soort.id, tier_id=soort.tier_id, naam="PortalPet",
            volgnummer=speler.volgend_pet_nummer, gevecht_genen=50, werk_genen=50,
            status=PetStatus.rust, honger=40, energie=40,
        )
        speler.volgend_pet_nummer += 1
        session.add(pet)
        await session.commit()
        await session.refresh(pet)
        pet_id = pet.id
        brokjes = await session.scalar(select(Item).where(Item.naam == "Basis brokjes"))
        brokjes_id = brokjes.id

    resp = await client.get(f"/api/spelers/{SPELER}", headers=auth)
    assert resp.status == 200, await resp.text()
    detail = await resp.json()
    print(f"Speler geladen: {detail['currency']} coins, {len(detail['pets'])} pet(s)")
    assert len(detail["pets"]) == 1

    resp = await client.post(
        f"/api/spelers/{SPELER}", headers=auth,
        json={"currency": 1234, "mmr": 1100, "ranked_pogingen_vandaag": 0},
    )
    assert resp.status == 200, await resp.text()
    async with async_session() as session:
        speler = await session.get(Speler, SPELER)
        print(f"Saldo aangepast: 500 -> {speler.currency}, MMR {speler.mmr}")
        assert speler.currency == 1234 and speler.mmr == 1100

    resp = await client.post(
        f"/api/spelers/{SPELER}/items", headers=auth, json={"item_id": brokjes_id, "aantal": 5}
    )
    assert resp.status == 200, await resp.text()
    resp = await client.post(
        f"/api/spelers/{SPELER}/items", headers=auth, json={"item_id": brokjes_id, "aantal": -2}
    )
    assert resp.status == 200, await resp.text()
    async with async_session() as session:
        inv = await session.scalar(
            select(InventarisItem).where(
                InventarisItem.speler_id == SPELER, InventarisItem.item_id == brokjes_id
            )
        )
        print(f"Basis brokjes na +5 en -2: {inv.aantal}")
        assert inv.aantal == 3

    # Meer afnemen dan de speler heeft moet netjes falen, niet negatief worden.
    resp = await client.post(
        f"/api/spelers/{SPELER}/items", headers=auth, json={"item_id": brokjes_id, "aantal": -99}
    )
    assert resp.status == 400
    print(f"Te veel afnemen geweigerd: {(await resp.json())['error']}")
    async with async_session() as session:
        inv = await session.scalar(
            select(InventarisItem).where(
                InventarisItem.speler_id == SPELER, InventarisItem.item_id == brokjes_id
            )
        )
        assert inv.aantal == 3, "voorraad mag niet gewijzigd zijn na een mislukte afname"

    resp = await client.post(
        f"/api/pets/{pet_id}", headers=auth,
        json={"naam": "PortalPetNieuw", "honger": 100, "energie": 90, "level": 5, "xp": 20,
              "blessure_opheffen": True, "van_werk_halen": False},
    )
    assert resp.status == 200, await resp.text()
    async with async_session() as session:
        pet = await session.get(Huisdier, pet_id)
        print(f"Pet bijgewerkt: '{pet.naam}', honger {pet.honger}, level {pet.level}")
        assert pet.naam == "PortalPetNieuw" and pet.honger == 100 and pet.level == 5

    resp = await client.post(
        f"/api/pets/{pet_id}", headers=auth,
        json={"naam": "X", "honger": 500, "energie": 50, "level": 1, "xp": 0},
    )
    assert resp.status == 400
    print(f"Honger 500 geweigerd: {(await resp.json())['error']}")

    resp = await client.delete(f"/api/pets/{pet_id}", headers=auth)
    assert resp.status == 200, await resp.text()
    async with async_session() as session:
        assert await session.get(Huisdier, pet_id) is None
    print("Pet verwijderd.")


async def test_kanalen(client, auth, bot) -> None:
    print("\n-- Kanalen: spawn-kanaal toevoegen werkt de bot-cache bij --")
    resp = await client.get("/api/kanalen", headers=auth)
    assert resp.status == 200, await resp.text()
    data = await resp.json()
    print(f"Beschikbare kanalen die de bot ziet: {len(data['beschikbaar'])}")

    resp = await client.post(
        "/api/kanalen/spawn", headers=auth, json={"channel_id": "424242424242"}
    )
    assert resp.status == 200, await resp.text()
    assert 424242424242 in bot._vangen_cog.spawn_kanaal_ids, (
        "cogs/vangen.py's in-memory cache is niet bijgewerkt — een via de portal "
        "toegevoegd kanaal zou pas na een herstart spawns geven"
    )
    print("Spawn-kanaal toegevoegd én in de VangenCog-cache gezet.")

    resp = await client.post(
        "/api/kanalen/spawn", headers=auth, json={"channel_id": "424242424242"}
    )
    assert resp.status == 400
    print(f"Dubbel toevoegen geweigerd: {(await resp.json())['error']}")

    resp = await client.get("/api/kanalen", headers=auth)
    spawn = (await resp.json())["spawn"]
    rij = next(k for k in spawn if k["channel_id"] == "424242424242")
    resp = await client.delete(f"/api/kanalen/spawn/{rij['id']}", headers=auth)
    assert resp.status == 200
    assert 424242424242 not in bot._vangen_cog.spawn_kanaal_ids
    print("Verwijderen haalt 'm ook weer uit de cache.")

    # Een kanaal dat de bot niet kent, moet geweigerd worden.
    resp = await client.post("/api/kanalen/spawn", headers=auth, json={"channel_id": "999"})
    assert resp.status == 400
    print(f"Onbekend kanaal geweigerd: {(await resp.json())['error']}")


async def test_overige_lezers(client, auth) -> None:
    print("\n-- Overige leesendpoints --")
    for pad in ("/api/statistieken", "/api/items", "/api/werkplekken", "/api/tiers", "/api/clans", "/api/spelers"):
        resp = await client.get(pad, headers=auth)
        assert resp.status == 200, f"{pad} gaf {resp.status}: {await resp.text()}"
        data = await resp.json()
        omvang = len(data) if isinstance(data, list) else len(data.keys())
        print(f"  {pad}: OK ({omvang} velden/rijen)")


async def main() -> None:
    bot = nep_bot()
    app = maak_app(bot)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    auth = {"Authorization": f"Bearer {TOKEN}"}

    try:
        await _opruimen(bot)
        await test_auth_dicht(client)
        await _maak_sessie()
        await test_verify_en_instellingen(client, auth)
        await test_validatie(client, auth)
        await test_soorten_crud(client, auth)
        await test_spelerbeheer(client, auth)
        await test_kanalen(client, auth, bot)
        await test_overige_lezers(client, auth)
        print("\nAlle checks geslaagd.")
    finally:
        await client.close()
        await _opruimen(bot)
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
