"""Herbruikbare app_commands-checks.

Discord's eigen default_permissions wordt door Discord zelf afgedwongen
vóórdat een interactie de bot bereikt, dus een extra rol toevoegen kan
alleen via de Discord-UI (Integrations), niet via code. Deze check draait
in plaats daarvan volledig in de bot: Administrator-permissie OF de rol
uit ADMIN_ROLE_ID (config.py) mag admin-commando's gebruiken.
"""

import discord

import config


def is_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    if config.ADMIN_ROLE_ID is None:
        return False
    return any(rol.id == config.ADMIN_ROLE_ID for rol in interaction.user.roles)
