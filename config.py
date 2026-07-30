import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

# "dev" of "prod". In dev worden commands direct naar DEV_GUILD_ID gesynct
# (instant zichtbaar), in prod globaal (kan tot een uur duren om te verschijnen).
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev").lower()

_dev_guild_id = os.environ.get("DEV_GUILD_ID")
DEV_GUILD_ID = int(_dev_guild_id) if _dev_guild_id else None

if ENVIRONMENT == "dev" and DEV_GUILD_ID is None:
    raise RuntimeError(
        "ENVIRONMENT=dev vereist DEV_GUILD_ID in .env (de test-server waar commands instant synced worden)."
    )

# Rol die naast Administrator ook admin-commando's mag gebruiken (optioneel).
_admin_role_id = os.environ.get("ADMIN_ROLE_ID")
ADMIN_ROLE_ID = int(_admin_role_id) if _admin_role_id else None

# ── Web-adminpanel (portal/) ────────────────────────────────────────────────
# Draait als aiohttp-server in hetzelfde proces als de bot. Zonder
# PORTAL_CLIENT_SECRET start de server niet: inloggen zou dan onmogelijk zijn,
# en een panel zonder werkende login heeft geen zin.
PORTAL_ENABLED = os.environ.get("PORTAL_ENABLED", "true").lower() not in ("false", "0", "no")

# Railway zet PORT zelf; lokaal valt het terug op 8080.
PORTAL_PORT = int(os.environ.get("PORT", "8080"))

# Discord OAuth. CLIENT_ID mag dezelfde applicatie zijn als de bot (of een
# andere app, bijv. hergebruikt van een ander project) — het is puur de app
# waarvan de login-knop gebruikmaakt.
PORTAL_CLIENT_ID = os.environ.get("PORTAL_CLIENT_ID")
PORTAL_CLIENT_SECRET = os.environ.get("PORTAL_CLIENT_SECRET")

# Publieke basis-URL waar het panel op draait, zonder trailing slash
# (bijv. https://critters.casualchaos.nl). Wordt gebruikt om de OAuth
# redirect-URI op te bouwen; die moet exact zo in de Discord-app staan.
PORTAL_BASIS_URL = os.environ.get("PORTAL_BASIS_URL", "").rstrip("/")
PORTAL_REDIRECT_URI = f"{PORTAL_BASIS_URL}/auth/callback" if PORTAL_BASIS_URL else None

# Server waarop de admin-rechten van een inlogger gecontroleerd worden.
# Valt terug op DEV_GUILD_ID zodat je in dev niets extra hoeft te zetten.
_admin_guild_id = os.environ.get("ADMIN_GUILD_ID")
ADMIN_GUILD_ID = int(_admin_guild_id) if _admin_guild_id else DEV_GUILD_ID

# Hoe lang een portal-login geldig blijft.
PORTAL_SESSIE_DAGEN = int(os.environ.get("PORTAL_SESSIE_DAGEN", "7"))


def portal_config_ontbreekt() -> list[str]:
    """Welke portal-env-vars nog ontbreken. Leeg = klaar om te starten."""
    ontbrekend = []
    if not PORTAL_CLIENT_ID:
        ontbrekend.append("PORTAL_CLIENT_ID")
    if not PORTAL_CLIENT_SECRET:
        ontbrekend.append("PORTAL_CLIENT_SECRET")
    if not PORTAL_BASIS_URL:
        ontbrekend.append("PORTAL_BASIS_URL")
    if ADMIN_GUILD_ID is None:
        ontbrekend.append("ADMIN_GUILD_ID")
    return ontbrekend


# SQLAlchemy async vereist het postgresql+asyncpg:// schema, Railway levert
# meestal postgresql:// of postgres://.
ASYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://", 1
).replace("postgres://", "postgresql+asyncpg://", 1)
