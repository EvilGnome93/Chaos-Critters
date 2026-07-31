"""Check van /changelog (2026-07-30, verzoek van de gebruiker: vervangt
/tests, "op de zelfde manier als Botv3" - modal -> reviewkanaal ->
Goedkeuren/Afwijzen/Bewerken -> aankondigingskanaal, met een optioneel
apart admin-gedeelte).

Test de pure parse-/split-logica los (geen Discord nodig), en de volledige
modal -> review -> goedkeuren/afwijzen/bewerken-flow met een neppe
Discord-client. De echte review-/aankondigingskanalen zijn hardcoded
constanten (cogs/changelog.py); hier tijdelijk overschreven zodat de test
niet naar echte Discord-kanalen probeert te posten.

Ruimt zijn eigen testdata op aan het eind.
"""

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord

import cogs.changelog as changelog_mod
from cogs.changelog import (
    ChangelogCog,
    ChangelogModal,
    ChangelogReviewView,
    _laatste_changelog_entry,
    split_changelog_content,
)
from db.engine import async_session
from db.models import Instelling

GUILD_ID = 1
REVIEW_KANAAL_ID = 900001
AANKONDIGING_KANAAL_ID = 900002
ADMIN_KANAAL_ID = 900003


def fake_channel(channel_id: int) -> MagicMock:
    kanaal = MagicMock()
    kanaal.id = channel_id
    kanaal.mention = f"<#{channel_id}>"
    kanaal.send = AsyncMock()
    return kanaal


def fake_client(kanalen: dict[int, MagicMock]) -> MagicMock:
    client = MagicMock()
    client.get_channel = lambda cid: kanalen.get(cid)
    client.fetch_channel = AsyncMock(side_effect=lambda cid: kanalen[cid])
    return client


def fake_admin_interaction(client: MagicMock) -> MagicMock:
    interaction = MagicMock()
    interaction.guild_id = GUILD_ID
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.guild_permissions.administrator = True
    interaction.user.mention = "<@111>"
    interaction.response = AsyncMock()
    interaction.client = client
    return interaction


async def _opruimen() -> None:
    async with async_session() as session:
        instelling = await session.get(Instelling, "changelog_rol_id")
        if instelling is not None:
            instelling.waarde = ""
        await session.commit()


def test_laatste_changelog_entry() -> None:
    print("-- _laatste_changelog_entry(): parsing --")
    with tempfile.TemporaryDirectory() as tmp:
        pad = Path(tmp) / "CHANGELOG.md"
        origineel = changelog_mod.CHANGELOG_PAD
        changelog_mod.CHANGELOG_PAD = pad
        try:
            assert _laatste_changelog_entry() is None
            print("Geen bestand -> None.")

            pad.write_text("# Titel\n\nGeen entries hier.\n", encoding="utf-8")
            assert _laatste_changelog_entry() is None
            print("Bestand zonder '## '-kop -> None.")

            pad.write_text(
                "# Chaos Critters\n\n## Nieuwste entry\n\nInhoud A.\n\n---\n\n## Oudere entry\n\nInhoud B.\n",
                encoding="utf-8",
            )
            entry = _laatste_changelog_entry()
            print(f"Gevonden entry: {entry!r}")
            assert entry == "## Nieuwste entry\n\nInhoud A."
            print("Pakt alleen de bovenste (nieuwste) entry, zonder trailing '---'.")
        finally:
            changelog_mod.CHANGELOG_PAD = origineel


def test_split_changelog_content() -> None:
    print("\n-- split_changelog_content() --")
    zonder_admin = "## Titel\n\nGewoon publieke tekst."
    publiek, admin = split_changelog_content(zonder_admin)
    assert publiek == zonder_admin and admin is None
    print("Geen admin-kop -> alles publiek, admin-deel None.")

    met_admin = "## Titel\n\nPublieke tekst.\n\n---\n\n### Voor admins & moderators\n\nGeheime admin-tekst."
    publiek, admin = split_changelog_content(met_admin)
    print(f"Publiek: {publiek!r}\nAdmin: {admin!r}")
    assert publiek == "## Titel\n\nPublieke tekst."
    assert admin is not None and admin.startswith("### Voor admins")
    assert "Geheime admin-tekst" in admin
    print("Splitst correct op de admin-kop, trailing '---' weggehaald bij het publieke deel.")


async def test_changelog_command_opent_modal() -> None:
    print("\n-- /changelog opent een voorgevulde modal --")
    with tempfile.TemporaryDirectory() as tmp:
        pad = Path(tmp) / "CHANGELOG.md"
        pad.write_text("## Test-release\n\nInhoud.\n", encoding="utf-8")
        origineel = changelog_mod.CHANGELOG_PAD
        changelog_mod.CHANGELOG_PAD = pad
        try:
            cog = ChangelogCog(bot=MagicMock())
            interactie = fake_admin_interaction(fake_client({}))
            await cog.changelog.callback(cog, interactie, tag_rol=True)
            modal = interactie.response.send_modal.call_args[0][0]
            print(f"Modal-titel: {modal.title}, voorgevuld: {modal.tekst_input.value!r}")
            assert isinstance(modal, ChangelogModal)
            assert modal.tekst_input.value == "## Test-release\n\nInhoud."
            assert modal.tag_rol is True
        finally:
            changelog_mod.CHANGELOG_PAD = origineel


async def test_versturen_naar_review() -> None:
    print("\n-- Modal versturen -> voorstel in reviewkanaal --")
    review_kanaal = fake_channel(REVIEW_KANAAL_ID)
    client = fake_client({REVIEW_KANAAL_ID: review_kanaal})
    origineel = changelog_mod.CHANGELOG_REVIEW_KANAAL_ID
    changelog_mod.CHANGELOG_REVIEW_KANAAL_ID = REVIEW_KANAAL_ID
    try:
        modal = ChangelogModal(tag_rol=True, huidig=None)
        modal.tekst_input._value = "## Nieuwe entry\n\nTekst hier."
        interactie = fake_admin_interaction(client)
        await modal.on_submit(interactie)

        review_kanaal.send.assert_called_once()
        kwargs = review_kanaal.send.call_args.kwargs
        assert kwargs["embed"].description == "## Nieuwe entry\n\nTekst hier."
        assert isinstance(kwargs["view"], ChangelogReviewView)
        bericht = interactie.response.send_message.call_args[0][0]
        print(f"Bevestiging: {bericht}")
        assert "review" in bericht.lower()
        print("Voorstel correct geplaatst in het (hardcoded) reviewkanaal.")
    finally:
        changelog_mod.CHANGELOG_REVIEW_KANAAL_ID = origineel


async def test_goedkeuren_zonder_admin_gedeelte() -> None:
    print("\n-- Goedkeuren zonder admin-gedeelte: alles publiek --")
    aankondiging_kanaal = fake_channel(AANKONDIGING_KANAAL_ID)
    client = fake_client({AANKONDIGING_KANAAL_ID: aankondiging_kanaal})
    origineel = changelog_mod.CHANGELOG_AANKONDIGING_KANAAL_ID
    changelog_mod.CHANGELOG_AANKONDIGING_KANAAL_ID = AANKONDIGING_KANAAL_ID
    try:
        view = ChangelogReviewView(tag_rol=False)
        interactie = fake_admin_interaction(client)
        interactie.message = MagicMock()
        interactie.message.embeds = [discord.Embed(description="## Release\n\nGewoon publieke tekst.")]

        await view.goedkeuren.callback(interactie)

        aankondiging_kanaal.send.assert_called_once()
        kwargs = aankondiging_kanaal.send.call_args.kwargs
        assert kwargs["content"] is None, "geen tag_rol -> geen rol-mention"
        assert "Gewoon publieke tekst" in kwargs["embed"].description
        eind_embed = interactie.response.edit_message.call_args.kwargs["embed"]
        assert eind_embed.color.value == discord.Color.green().value
        assert all(item.disabled for item in view.children)
        print("Publieke tekst gepost, geen rol getagd (tag_rol=False), knoppen uitgeschakeld, status groen.")
    finally:
        changelog_mod.CHANGELOG_AANKONDIGING_KANAAL_ID = origineel


async def test_goedkeuren_met_admin_gedeelte_en_rol() -> None:
    print("\n-- Goedkeuren MET admin-gedeelte + rol-tag --")
    aankondiging_kanaal = fake_channel(AANKONDIGING_KANAAL_ID)
    admin_kanaal = fake_channel(ADMIN_KANAAL_ID)
    client = fake_client({AANKONDIGING_KANAAL_ID: aankondiging_kanaal, ADMIN_KANAAL_ID: admin_kanaal})
    origineel_aankondiging = changelog_mod.CHANGELOG_AANKONDIGING_KANAAL_ID
    origineel_admin = changelog_mod.CHANGELOG_ADMIN_KANAAL_ID
    changelog_mod.CHANGELOG_AANKONDIGING_KANAAL_ID = AANKONDIGING_KANAAL_ID
    changelog_mod.CHANGELOG_ADMIN_KANAAL_ID = ADMIN_KANAAL_ID

    async with async_session() as session:
        instelling = await session.get(Instelling, "changelog_rol_id")
        assert instelling is not None, "changelog_rol_id moet geseed zijn (scripts/seed.py)"
        instelling.waarde = "555555"
        await session.commit()

    try:
        view = ChangelogReviewView(tag_rol=True)
        interactie = fake_admin_interaction(client)
        interactie.message = MagicMock()
        content = (
            "## Release\n\nPublieke tekst.\n\n---\n\n### Voor admins & moderators\n\nGeheime admin-info."
        )
        interactie.message.embeds = [discord.Embed(description=content)]

        await view.goedkeuren.callback(interactie)

        publiek_kwargs = aankondiging_kanaal.send.call_args.kwargs
        print(f"Publiek bericht content: {publiek_kwargs['content']}")
        assert publiek_kwargs["content"] == "<@&555555>"
        assert "Publieke tekst" in publiek_kwargs["embed"].description
        assert "ook wijzigingen voor admins" in publiek_kwargs["embed"].description
        assert "Geheime admin-info" not in publiek_kwargs["embed"].description

        admin_kwargs = admin_kanaal.send.call_args.kwargs
        assert "Geheime admin-info" in admin_kwargs["embed"].description
        print("Rol getagd, publiek deel zonder admin-info, admin-deel apart gepost.")
    finally:
        changelog_mod.CHANGELOG_AANKONDIGING_KANAAL_ID = origineel_aankondiging
        changelog_mod.CHANGELOG_ADMIN_KANAAL_ID = origineel_admin
        await _opruimen()


async def test_afwijzen() -> None:
    print("\n-- Afwijzen: geen berichten de deur uit --")
    client = fake_client({})
    view = ChangelogReviewView(tag_rol=True)
    interactie = fake_admin_interaction(client)
    interactie.message = MagicMock()
    interactie.message.embeds = [discord.Embed(description="## X\n\nY.")]

    await view.afwijzen.callback(interactie)

    eind_embed = interactie.response.edit_message.call_args.kwargs["embed"]
    print(f"Status-kleur: {eind_embed.color}, veld: {eind_embed.fields[0].name}")
    assert eind_embed.color.value == discord.Color.red().value
    assert eind_embed.fields[0].name == "❌ Afgewezen"
    assert all(item.disabled for item in view.children)
    print("Status op afgewezen gezet, geen enkel kanaal aangeroepen.")


async def test_bewerken() -> None:
    print("\n-- Bewerken: nieuwe modal met huidige tekst, daarna bericht bijwerken --")
    review_kanaal = fake_channel(REVIEW_KANAAL_ID)
    client = fake_client({})
    view = ChangelogReviewView(tag_rol=True)
    interactie = fake_admin_interaction(client)
    interactie.message = review_kanaal
    review_kanaal.embeds = [discord.Embed(description="## Origineel\n\nTekst.")]
    review_kanaal.edit = AsyncMock()

    await view.bewerken.callback(interactie)
    modal = interactie.response.send_modal.call_args[0][0]
    assert modal.tekst_input.value == "## Origineel\n\nTekst."
    print("Bewerk-modal voorgevuld met de huidige tekst.")

    modal.tekst_input._value = "## Bijgewerkt\n\nNieuwe tekst."
    interactie2 = fake_admin_interaction(client)
    await modal.on_submit(interactie2)
    review_kanaal.edit.assert_called_once()
    nieuw_embed = review_kanaal.edit.call_args.kwargs["embed"]
    assert nieuw_embed.description == "## Bijgewerkt\n\nNieuwe tekst."
    print("Reviewbericht bijgewerkt met de nieuwe tekst, zonder de status te wijzigen.")


async def main() -> None:
    try:
        test_laatste_changelog_entry()
        test_split_changelog_content()
        await test_changelog_command_opent_modal()
        await test_versturen_naar_review()
        await test_goedkeuren_zonder_admin_gedeelte()
        await test_goedkeuren_met_admin_gedeelte_en_rol()
        await test_afwijzen()
        await test_bewerken()
        print("\nAlle checks geslaagd.")
    finally:
        await _opruimen()
        print("Testdata opgeruimd.")


if __name__ == "__main__":
    asyncio.run(main())
