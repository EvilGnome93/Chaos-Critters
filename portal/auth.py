"""Discord OAuth-login en sessiebeheer voor het web-adminpanel.

Flow:
1. `GET /auth/discord` → redirect naar Discord met een random `state`
   (CSRF-bescherming: Discord stuurt die onveranderd terug, en zonder een
   state die wij zelf hebben uitgegeven weigeren we de callback).
2. `GET /auth/callback` → code inwisselen voor een access token, daarmee
   `/users/@me` ophalen, en het lidmaatschap controleren.
3. Rechten worden **via de bot zelf** gecontroleerd (`guild.fetch_member`),
   niet via een extra OAuth-scope: dan is `identify` genoeg en gebruiken we
   exact dezelfde regel als de Discord-commando's (utils/checks.py).
   `fetch_member` doet een API-call en werkt dus ook zonder de (privileged)
   members-intent, die deze bot niet aan heeft staan.
4. Bij succes een sessietoken in `portal_sessies` (DB, dus een deploy logt je
   niet uit) en terug naar het panel met `?token=...` in de URL.

**Twee toegangsniveaus (2026-07-30, verzoek van de gebruiker: "openheid voor
spelers")**: elk lid van de server mag inloggen (stap 2 controleert alleen
lidmaatschap, niet meer een adminrol), maar `PortalSessie.is_admin` — bepaald
bij het inloggen via `member_is_admin()` — beslist wat iemand daarna mag.
Alleen-lezen leden zien de balans-/overzicht-tabs; schrijf-acties en de
spelers-/kanalen-tabs vereisen `is_admin` (zie `vereist_admin()` hieronder,
gebruikt door `portal/api_content.py` en `portal/api_spelers.py`)."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import discord
from aiohttp import web
from sqlalchemy import delete

import config
from db.engine import async_session
from db.models import PortalSessie
from utils.checks import member_is_admin

log = logging.getLogger("chaos_critters")

DISCORD_API = "https://discord.com/api/v10"

# Uitgegeven, nog niet gebruikte OAuth-states. In het geheugen is hier prima:
# een state leeft maar een paar seconden (de duur van de Discord-redirect), dus
# een deploy midden in een login betekent alleen "opnieuw inloggen".
_open_states: dict[str, datetime] = {}
_STATE_GELDIG_MINUTEN = 10


def _nu() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _nieuwe_state() -> str:
    # Verlopen states meteen opruimen, anders groeit deze dict onbeperkt bij
    # afgebroken logins.
    grens = _nu() - timedelta(minutes=_STATE_GELDIG_MINUTEN)
    for state, aangemaakt in list(_open_states.items()):
        if aangemaakt < grens:
            del _open_states[state]

    state = secrets.token_urlsafe(24)
    _open_states[state] = _nu()
    return state


def _state_gebruiken(state: str | None) -> bool:
    """Eenmalig verzilveren: geeft True als wij deze state hebben uitgegeven."""
    if not state or state not in _open_states:
        return False
    aangemaakt = _open_states.pop(state)
    return aangemaakt >= _nu() - timedelta(minutes=_STATE_GELDIG_MINUTEN)


async def _maak_sessie(discord_id: int, weergavenaam: str, is_admin: bool) -> str:
    token = secrets.token_urlsafe(32)
    async with async_session() as session:
        # Verlopen sessies opruimen bij elke nieuwe login: geen aparte
        # achtergrondtaak nodig voor zo'n kleine tabel.
        await session.execute(delete(PortalSessie).where(PortalSessie.verloopt_op < _nu()))
        session.add(
            PortalSessie(
                token=token,
                discord_id=discord_id,
                weergavenaam=weergavenaam[:64],
                is_admin=is_admin,
                verloopt_op=_nu() + timedelta(days=config.PORTAL_SESSIE_DAGEN),
            )
        )
        await session.commit()
    return token


async def sessie_van_request(request: web.Request) -> PortalSessie | None:
    """Leest het bearer-token uit de request en geeft de geldige sessie terug."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header.removeprefix("Bearer ").strip()
    if not token:
        return None

    async with async_session() as session:
        sessie = await session.get(PortalSessie, token)
        if sessie is None or sessie.verloopt_op < _nu():
            return None
        # Losgekoppeld teruggeven: de aanroeper heeft alleen de waarden nodig
        # en de sessie hierboven wordt gesloten.
        session.expunge(sessie)
        return sessie


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Alles onder /api/ vereist een geldige sessie; /auth/ en de statische
    bestanden (het loginscherm zelf) zijn bewust open."""
    if not request.path.startswith("/api/"):
        return await handler(request)

    sessie = await sessie_van_request(request)
    if sessie is None:
        return web.json_response({"error": "niet ingelogd"}, status=401)

    request["sessie"] = sessie
    return await handler(request)


def vereist_admin(handler):
    """Route-decorator voor schrijf-acties en admin-only content (2026-07-30,
    verzoek van de gebruiker: "openheid voor spelers" — niet-admin leden mogen
    nu ook inloggen en de balans-tabs lezen, maar niets wijzigen en geen
    spelers-/kanalen-/statistiekdata zien). `auth_middleware` heeft de sessie
    al gevalideerd, hier alleen nog de rol-check bovenop."""
    async def wrapper(request: web.Request) -> web.Response:
        sessie = request["sessie"]
        if not sessie.is_admin:
            return web.json_response({"error": "alleen voor admins"}, status=403)
        return await handler(request)
    return wrapper


async def _lid_check(bot: discord.Client, discord_id: int) -> discord.Member | None:
    """Geeft het Member-object terug als deze gebruiker lid is van de
    ADMIN_GUILD_ID-server (ongeacht rol), anders None. Adminrechten worden
    er apart bovenop bepaald via member_is_admin() — elk lid mag nu inloggen,
    alleen wat je daarna mag zien/doen verschilt (zie vereist_admin)."""
    guild = bot.get_guild(config.ADMIN_GUILD_ID)
    if guild is None:
        log.warning("Portal: bot zit niet in ADMIN_GUILD_ID %s", config.ADMIN_GUILD_ID)
        return None
    try:
        return await guild.fetch_member(discord_id)
    except discord.NotFound:
        return None
    except discord.HTTPException as e:
        log.warning("Portal: kon member %s niet ophalen: %s", discord_id, e)
        return None


async def start_login(request: web.Request) -> web.Response:
    """GET /auth/discord — stuurt de gebruiker naar Discord."""
    params = urlencode(
        {
            "client_id": config.PORTAL_CLIENT_ID,
            "redirect_uri": config.PORTAL_REDIRECT_URI,
            "response_type": "code",
            "scope": "identify",
            "state": _nieuwe_state(),
        }
    )
    raise web.HTTPFound(f"https://discord.com/oauth2/authorize?{params}")


def _terug_naar_panel(query: str) -> web.HTTPFound:
    """Redirect terug naar het paneel. Bewust altijd op basis van de
    geconfigureerde PORTAL_BASIS_URL en nooit op iets uit de request: een lege
    basis-URL zou `//?...` opleveren, en dat is een protocol-relatieve URL —
    dus een redirect naar een wíllekeurige host. De server start niet zonder
    PORTAL_BASIS_URL (zie config.portal_config_ontbreekt), dus hier is die
    altijd gezet."""
    return web.HTTPFound(f"{config.PORTAL_BASIS_URL}/?{query}")


async def callback(request: web.Request) -> web.Response:
    """GET /auth/callback — Discord stuurt de gebruiker hier terug."""
    if request.query.get("error"):
        raise _terug_naar_panel("error=cancelled")

    if not _state_gebruiken(request.query.get("state")):
        # Geen (of een verlopen/onbekende) state: mogelijk een CSRF-poging, of
        # simpelweg een oude tab. In beide gevallen: opnieuw beginnen.
        raise _terug_naar_panel("error=state")

    code = request.query.get("code")
    if not code:
        raise _terug_naar_panel("error=token_failed")

    sessie_http = request.app["http"]
    try:
        async with sessie_http.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": config.PORTAL_CLIENT_ID,
                "client_secret": config.PORTAL_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.PORTAL_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status != 200:
                log.warning("Portal: token-exchange mislukte (%s)", resp.status)
                raise _terug_naar_panel("error=token_failed")
            token_data = await resp.json()

        async with sessie_http.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        ) as resp:
            if resp.status != 200:
                raise _terug_naar_panel("error=token_failed")
            gebruiker = await resp.json()
    except web.HTTPFound:
        raise
    except Exception:
        log.exception("Portal: onverwachte fout tijdens OAuth-callback")
        raise _terug_naar_panel("error=server_error")

    discord_id = int(gebruiker["id"])
    member = await _lid_check(request.app["bot"], discord_id)
    if member is None:
        log.info("Portal: login geweigerd voor %s (geen lid van de server)", discord_id)
        raise _terug_naar_panel("error=unauthorized")

    admin = member_is_admin(member)
    token = await _maak_sessie(discord_id, member.display_name, admin)
    log.info("Portal: %s (%s) ingelogd (admin: %s)", member.display_name, discord_id, admin)
    raise _terug_naar_panel(f"token={token}")


async def verify(request: web.Request) -> web.Response:
    """GET /api/verify — het panel checkt hiermee of het opgeslagen token nog
    geldig is, en of het in admin- of alleen-lezen-modus moet renderen."""
    sessie = request["sessie"]
    return web.json_response(
        {"discord_id": str(sessie.discord_id), "naam": sessie.weergavenaam, "is_admin": sessie.is_admin}
    )


async def logout(request: web.Request) -> web.Response:
    """POST /api/logout — sessie ongeldig maken."""
    sessie = request["sessie"]
    async with async_session() as session:
        await session.execute(delete(PortalSessie).where(PortalSessie.token == sessie.token))
        await session.commit()
    return web.json_response({"ok": True})


def routes_toevoegen(app: web.Application) -> None:
    app.router.add_get("/auth/discord", start_login)
    app.router.add_get("/auth/callback", callback)
    app.router.add_get("/api/verify", verify)
    app.router.add_post("/api/logout", logout)
