"""Herbruikbare admin-check, gedeeld door de Discord-commando's en het
web-adminpanel (portal/).

Discord's eigen default_permissions wordt door Discord zelf afgedwongen
vóórdat een interactie de bot bereikt, dus een extra rol toevoegen kan
alleen via de Discord-UI (Integrations), niet via code. Deze check draait
in plaats daarvan volledig in de bot: Administrator-permissie OF de rol
uit ADMIN_ROLE_ID (config.py) mag admin-commando's gebruiken.
"""

import discord

import config


def member_is_admin(member: discord.Member) -> bool:
    """De eigenlijke regel, losgetrokken van Discord-interacties (2026-07-29)
    zodat het web-adminpanel (portal/auth.py) dezelfde bron van waarheid
    gebruikt en de twee niet uit de pas kunnen lopen."""
    if member.guild_permissions.administrator:
        return True
    if config.ADMIN_ROLE_ID is None:
        return False
    return any(rol.id == config.ADMIN_ROLE_ID for rol in member.roles)


def is_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return member_is_admin(interaction.user)
