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

# SQLAlchemy async vereist het postgresql+asyncpg:// schema, Railway levert
# meestal postgresql:// of postgres://.
ASYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://", 1
).replace("postgres://", "postgresql+asyncpg://", 1)
