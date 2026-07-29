"""Check van /wiki (2026-07-28, verzoek van de gebruiker): doorbladerbare
uitleg van de spelmechanieken, met een dropdown om direct naar een
onderwerp te springen en Vorige/Volgende-knoppen om er sequentieel
doorheen te bladeren.

Geen DB nodig — puur UI-logica en een inhoud-sanity-check (embed-limieten).
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cogs.wiki import WIKI_ONDERWERPEN, WikiCog, WikiView


def fake_interaction(user_id: int) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    bericht = MagicMock()
    interaction.original_response = AsyncMock(return_value=bericht)
    return interaction


def test_inhoud_binnen_discord_limieten() -> None:
    print("-- Alle onderwerpen passen binnen Discord's embed-limieten --")
    assert len(WIKI_ONDERWERPEN) >= 1
    for titel, uitleg, commandos in WIKI_ONDERWERPEN:
        assert len(titel) <= 256, f"Titel te lang: {titel}"
        assert len(uitleg) <= 4096, f"Uitleg te lang: {titel}"
        cmd_tekst = "\n".join(commandos)
        assert len(cmd_tekst) <= 1024, f"Commando-veld te lang: {titel}"
        assert commandos, f"Geen commando's opgegeven voor: {titel}"
    print(f"Alle {len(WIKI_ONDERWERPEN)} onderwerpen passen binnen de limieten.")


async def test_navigatie() -> None:
    print("\n-- /wiki: dropdown + Vorige/Volgende-navigatie --")
    cog = WikiCog(bot=MagicMock())
    interactie = fake_interaction(999999999999999981)
    await cog.wiki.callback(cog, interactie)
    interactie.response.send_message.assert_awaited()
    view = interactie.response.send_message.call_args.kwargs["view"]

    print(f"Start: onderwerp {view.onderwerp_index} (verwacht 0), Vorige uitgeschakeld: {view.vorige.disabled}")
    assert view.onderwerp_index == 0
    assert view.vorige.disabled is True
    assert view.volgende.disabled is False
    assert len(view.onderwerp_select.options) == len(WIKI_ONDERWERPEN)

    # Doorlopen met Volgende tot het laatste onderwerp.
    for _ in range(len(WIKI_ONDERWERPEN) - 1):
        interactie_volgende = fake_interaction(999999999999999981)
        await view.volgende.callback(interactie_volgende)
    print(f"Na alle Volgende-klikken: onderwerp {view.onderwerp_index} (verwacht {len(WIKI_ONDERWERPEN) - 1})")
    assert view.onderwerp_index == len(WIKI_ONDERWERPEN) - 1
    assert view.volgende.disabled is True
    assert view.vorige.disabled is False

    # Terug naar het begin met Vorige.
    for _ in range(len(WIKI_ONDERWERPEN) - 1):
        interactie_vorige = fake_interaction(999999999999999981)
        await view.vorige.callback(interactie_vorige)
    print(f"Na alle Vorige-klikken: onderwerp {view.onderwerp_index} (verwacht 0)")
    assert view.onderwerp_index == 0
    assert view.vorige.disabled is True

    # Direct springen via de dropdown naar onderwerp 3.
    doel_index = 3
    view.onderwerp_select._values = [str(doel_index)]
    interactie_select = fake_interaction(999999999999999981)
    await view.onderwerp_select.callback(interactie_select)
    print(f"Na dropdown-selectie naar index {doel_index}: onderwerp {view.onderwerp_index}")
    assert view.onderwerp_index == doel_index
    embed = view.huidige_embed()
    assert embed.title == WIKI_ONDERWERPEN[doel_index][0]
    print("Dropdown + Vorige/Volgende-navigatie werken correct.")


async def test_interaction_check_andere_gebruiker() -> None:
    print("\n-- /wiki: alleen de eigen gebruiker mag bladeren --")
    view = WikiView(eigenaar_id=111)
    interactie_andere_gebruiker = fake_interaction(222)
    mag_door = await view.interaction_check(interactie_andere_gebruiker)
    print(f"Andere gebruiker mag door: {mag_door} (verwacht False)")
    assert mag_door is False
    interactie_andere_gebruiker.response.send_message.assert_awaited()

    interactie_eigenaar = fake_interaction(111)
    mag_door_eigenaar = await view.interaction_check(interactie_eigenaar)
    assert mag_door_eigenaar is True
    print("interaction_check laat alleen de eigenaar toe.")


async def main() -> None:
    test_inhoud_binnen_discord_limieten()
    await test_navigatie()
    await test_interaction_check_andere_gebruiker()
    print("\nAlle checks geslaagd.")


if __name__ == "__main__":
    asyncio.run(main())
