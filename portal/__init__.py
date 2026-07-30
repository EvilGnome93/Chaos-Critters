"""Web-adminpanel voor Chaos Critters (2026-07-29).

Draait als aiohttp-server in hetzelfde proces/dezelfde event loop als de bot,
zodat de panel-endpoints rechtstreeks bij de bot kunnen (rollen ophalen,
caches invalideren) en er maar één Railway-service nodig is.

Opzet:
- `server.py`    — app-factory, statische bestanden, start/stop
- `auth.py`      — Discord OAuth-flow, sessies (DB-backed), admin-check
- `api_content.py` — instellingen, items, werkplekken, tiers, pet-soorten, kanalen
- `api_spelers.py` — spelers, huisdieren, inventaris, clans, statistieken
"""
