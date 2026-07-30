"""aiohttp-server voor het web-adminpanel.

Draait in hetzelfde proces en dezelfde event loop als de bot, zodat de
endpoints rechtstreeks bij de bot kunnen (rollen ophalen voor de admin-check,
kanaalnamen, de spawn-kanaal-cache in cogs/vangen.py invalideren) en er maar
één Railway-service nodig is. Het panel wordt door deze server zelf geserveerd
op `/`, dus er is geen aparte hosting of CORS-configuratie nodig.
"""

import logging
from pathlib import Path

import aiohttp
from aiohttp import web

import config
from portal import api_content, api_spelers, auth
from portal.api_content import ValidatieFout

log = logging.getLogger("chaos_critters")

WEB_MAP = Path(__file__).resolve().parent.parent / "web"


@web.middleware
async def fout_middleware(request: web.Request, handler):
    """Zet ValidatieFout om in een nette 400 met leesbare tekst, en vangt al
    het overige af als 500 zonder de interne fout naar de browser te lekken."""
    try:
        return await handler(request)
    except ValidatieFout as e:
        return web.json_response({"error": str(e)}, status=400)
    except web.HTTPException:
        raise
    except (ValueError, KeyError, TypeError) as e:
        # Onbruikbare JSON of een niet-numeriek ID in de URL.
        log.info("Portal: ongeldige request op %s: %s", request.path, e)
        return web.json_response({"error": "ongeldige invoer"}, status=400)
    except Exception:
        log.exception("Portal: onverwachte fout op %s", request.path)
        return web.json_response({"error": "interne serverfout"}, status=500)


async def _index(request: web.Request) -> web.Response:
    bestand = WEB_MAP / "admin.html"
    if not bestand.exists():
        return web.Response(text="admin.html niet gevonden", status=404)
    return web.FileResponse(bestand)


async def _health(request: web.Request) -> web.Response:
    """Los endpoint zodat Railway (en jij) kan zien dat de server leeft, zonder
    in te loggen."""
    return web.json_response({"status": "ok", "bot": str(request.app["bot"].user or "verbindt...")})


def maak_app(bot) -> web.Application:
    app = web.Application(middlewares=[fout_middleware, auth.auth_middleware])
    app["bot"] = bot
    app["http"] = aiohttp.ClientSession()

    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    auth.routes_toevoegen(app)
    api_content.routes_toevoegen(app)
    api_spelers.routes_toevoegen(app)

    async def _sluit_http(_app):
        await _app["http"].close()

    app.on_cleanup.append(_sluit_http)
    return app


class PortalServer:
    """Levenscyclus van de webserver, gekoppeld aan die van de bot."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        ontbrekend = config.portal_config_ontbreekt()
        if not config.PORTAL_ENABLED:
            log.info("Portal: uitgeschakeld via PORTAL_ENABLED, server niet gestart.")
            return
        if ontbrekend:
            # Bewust geen crash: de bot moet het gewoon doen, ook als het panel
            # nog niet geconfigureerd is. Wel een duidelijke waarschuwing.
            log.warning(
                "Portal: niet gestart, deze env-vars ontbreken nog: %s", ", ".join(ontbrekend)
            )
            return

        app = maak_app(self.bot)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", config.PORTAL_PORT)
        await site.start()
        log.info(
            "Portal: draait op poort %s (publiek: %s)", config.PORTAL_PORT, config.PORTAL_BASIS_URL
        )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            log.info("Portal: gestopt.")
