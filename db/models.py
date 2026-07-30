import enum
from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PetStatus(str, enum.Enum):
    team = "team"
    werkplek = "werkplek"
    rust = "rust"


class ItemType(str, enum.Enum):
    voeding = "voeding"
    materiaal = "materiaal"
    grondstof = "grondstof"
    boost = "boost"
    overig = "overig"


class Element(str, enum.Enum):
    """Contra-cirkel Vuur > Lucht > Grond > Water > Vuur (zie
    utils/elementen.py). Chaos is een 5e, grillig element zonder vaste
    contra: geeft per matchup willekeurig een bonus of malus."""

    grond = "grond"
    water = "water"
    lucht = "lucht"
    vuur = "vuur"
    chaos = "chaos"


class Tier(Base):
    """Zeldzaamheidstiers. Nummers liggen bewust uit elkaar (1, 3, 5, ...)
    zodat er later tussenliggende tiers (2, 4, ...) toegevoegd kunnen worden
    zonder bestaande data te herschrijven."""

    __tablename__ = "tiers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    naam: Mapped[str] = mapped_column(String(32), unique=True)
    spawnkans: Mapped[float] = mapped_column(Numeric(5, 4))
    stat_multiplier: Mapped[float] = mapped_column(Numeric(4, 2))

    pet_soorten: Mapped[list["PetSoort"]] = relationship(back_populates="tier")


class Werkplek(Base):
    __tablename__ = "werkplekken"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32), unique=True)
    # Vrije omschrijving van het soort werk_genen dat hier goed van pas komt
    # ("Water-affiniteit", "Kracht/graafvermogen", ...). De brief (sectie 1)
    # bedoelt dit als basis voor een efficiëntie-bonus per werkplek; die
    # mechaniek bestaat nog niet, dus het veld wordt nu alleen geseed en
    # nergens gelezen. Gereserveerd, geen dood hout (2026-07-28, review).
    vereiste_werk_genen: Mapped[str] = mapped_column(String(32))
    output_per_uur: Mapped[float] = mapped_column(Numeric(6, 2))
    # Gedeelde capaciteit: max. dit aantal pets mag tegelijk op deze
    # werkplek werken. Sinds het clan-systeem (2026-07-27) is dat geen
    # globale pool meer maar één per clan, plus één gedeelde pool voor
    # alle clanloze spelers. Afgedwongen in cogs/werk.py.
    capaciteit: Mapped[int] = mapped_column(default=1)
    opbrengst_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    # Tweede, zeldzamere grondstof per werkplek (2026-07-26, verzoek van de
    # gebruiker): elke voltooide shift heeft opbrengst_2_kans kans om ook dit
    # item op te leveren, los van de hoofdgrondstof.
    opbrengst_item_2_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    opbrengst_2_kans: Mapped[float] = mapped_column(Numeric(4, 3), default=0.25)

    pet_soorten: Mapped[list["PetSoort"]] = relationship(back_populates="werkplek_voorkeur")
    opbrengst_item: Mapped["Item | None"] = relationship(foreign_keys=[opbrengst_item_id])
    opbrengst_item_2: Mapped["Item | None"] = relationship(foreign_keys=[opbrengst_item_2_id])


class PetSoort(Base):
    """Statische soort-definitie (Hond, Vos, Chaos Eenhoorn, ...).
    Huisdier is de individuele instantie die een speler vangt."""

    __tablename__ = "pet_soorten"

    id: Mapped[int] = mapped_column(primary_key=True)
    naam: Mapped[str] = mapped_column(String(64), unique=True)
    tier_id: Mapped[int] = mapped_column(ForeignKey("tiers.id"))
    gevecht_basis: Mapped[float] = mapped_column(Numeric(6, 2))
    werk_basis: Mapped[float] = mapped_column(Numeric(6, 2))
    werkplek_voorkeur_id: Mapped[int | None] = mapped_column(ForeignKey("werkplekken.id"), nullable=True)
    beschrijving: Mapped[str | None] = mapped_column(String(256), nullable=True)
    afbeelding_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    element: Mapped[Element | None] = mapped_column(Enum(Element, name="element"), nullable=True)

    tier: Mapped["Tier"] = relationship(back_populates="pet_soorten")
    werkplek_voorkeur: Mapped["Werkplek | None"] = relationship(back_populates="pet_soorten")
    huisdieren: Mapped[list["Huisdier"]] = relationship(back_populates="soort")


class Speler(Base):
    __tablename__ = "spelers"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    currency: Mapped[int] = mapped_column(default=0)
    # Speler-level/XP staat in de brief (sectie 1) maar is nog nergens
    # geïmplementeerd: alleen pets levelen op dit moment. Bewust behouden als
    # gereserveerd veld, net als blijdschap hieronder — niet verwijderen in
    # de veronderstelling dat het dood hout is (2026-07-28, review).
    level: Mapped[int] = mapped_column(default=1)
    xp: Mapped[int] = mapped_column(default=0)
    mmr: Mapped[int] = mapped_column(default=1000)
    # Rollend 24-uursvenster voor de dagelijkse gratis ranked-pogingen (sectie 12/13).
    ranked_pogingen_vandaag: Mapped[int] = mapped_column(default=0)
    ranked_reset_op: Mapped[datetime | None] = mapped_column(nullable=True)
    # Volgende per-speler pet-volgnummer (zie Huisdier.volgnummer): blijft
    # oplopen, ook na een toekomstige /release, zodat nummers nooit botsen.
    volgend_pet_nummer: Mapped[int] = mapped_column(default=1)
    # Clan-systeem (2026-07-27, verzoek van de gebruiker: "clan" i.p.v. het
    # Nederlandse "gilde" — enige Engelse naam in een verder Nederlandstalig
    # schema, op expliciet verzoek. Niet "guild": discord.py gebruikt die naam
    # al voor een Discord-server zelf (discord.Guild/interaction.guild_id),
    # dus "clan" voorkomt een verwarrende naam-botsing). NULL = geen clan.
    clan_id: Mapped[int | None] = mapped_column(ForeignKey("clans.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    huisdieren: Mapped[list["Huisdier"]] = relationship(back_populates="eigenaar")
    inventaris: Mapped[list["InventarisItem"]] = relationship(back_populates="speler")
    clan: Mapped["Clan | None"] = relationship(back_populates="leden", foreign_keys=[clan_id])


class Clan(Base):
    """Zie projectbrief sectie 16: gedeelde werkplekken + leaderboard per
    clan. Elke clan krijgt zijn eigen capaciteit-pool per werkplek, los
    van de globale pool van andere clans/clanloze spelers (cogs/werk.py).
    """

    __tablename__ = "clans"

    id: Mapped[int] = mapped_column(primary_key=True)
    naam: Mapped[str] = mapped_column(String(32), unique=True)
    oprichter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("spelers.discord_id"))
    # Cumulatieve Chaos Coins-opbrengst van alle leden via /werk, voor het
    # leaderboard — blijft staan ook als leden het geld weer uitgeven.
    totale_werk_opbrengst: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    leden: Mapped[list["Speler"]] = relationship(back_populates="clan", foreign_keys=[Speler.clan_id])


class Huisdier(Base):
    __tablename__ = "huisdieren"
    __table_args__ = (UniqueConstraint("eigenaar_id", "volgnummer", name="uq_huisdieren_eigenaar_volgnummer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Zichtbaar pet-nummer, per speler (jouw #1, #2, ...) i.p.v. het interne,
    # over alle spelers heen doorlopende id hierboven. Toegewezen vanuit
    # Speler.volgend_pet_nummer bij het vangen (cogs/vangen.py).
    volgnummer: Mapped[int]
    eigenaar_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("spelers.discord_id"))
    soort_id: Mapped[int] = mapped_column(ForeignKey("pet_soorten.id"))
    tier_id: Mapped[int] = mapped_column(ForeignKey("tiers.id"))
    naam: Mapped[str] = mapped_column(String(32))

    # Actuele stats (0-100)
    honger: Mapped[int] = mapped_column(default=100)
    energie: Mapped[int] = mapped_column(default=100)
    blijdschap: Mapped[int] = mapped_column(default=100)

    # Verborgen genetische waarden
    gevecht_genen: Mapped[float] = mapped_column(Numeric(6, 2))
    werk_genen: Mapped[float] = mapped_column(Numeric(6, 2))

    status: Mapped[PetStatus] = mapped_column(Enum(PetStatus, name="pet_status"), default=PetStatus.rust)
    werkplek_type_id: Mapped[int | None] = mapped_column(ForeignKey("werkplekken.id"), nullable=True)
    werk_cyclus: Mapped[str | None] = mapped_column(String(16), nullable=True)
    werk_gestart_op: Mapped[datetime | None] = mapped_column(nullable=True)
    werk_notificatie_verstuurd: Mapped[bool] = mapped_column(default=False)
    werk_kanaal_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Peilmoment voor het lazy honger/energie/blijdschap-verval, zie utils/stats.py.
    laatste_verzorging_op: Mapped[datetime] = mapped_column(server_default=func.now())
    laatste_slaap_op: Mapped[datetime | None] = mapped_column(nullable=True)
    # Gezet wanneer een pet een gevecht-matchup verliest (0 HP); tot dit
    # moment niet inzetbaar voor werk/team. Zie utils/gevechten.py.
    geblesseerd_tot: Mapped[datetime | None] = mapped_column(nullable=True)

    level: Mapped[int] = mapped_column(default=1)
    xp: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Per-pet uitrusting (2026-07-27, verzoek van de gebruiker: Item-overhaul
    # deel 1 — voerbakken/zelfreinigend systeem krijgen hun beloofde effect).
    # Bewust een simpele naam/vlag i.p.v. een FK naar Item: het effect wordt
    # toegepast in utils/stats.py, waar een join per pet niets toevoegt (de
    # namen liggen vast in VOERBAK_ITEMS_PER_NIVEAU). "simpel"/"slim"/None;
    # de twee voerbakken delen één slot, het zelfreinigend systeem een eigen.
    voerbak_niveau: Mapped[str | None] = mapped_column(String(16), nullable=True)
    zelfreinigend_actief: Mapped[bool] = mapped_column(default=False)

    eigenaar: Mapped["Speler"] = relationship(back_populates="huisdieren")
    soort: Mapped["PetSoort"] = relationship(back_populates="huisdieren")
    tier: Mapped["Tier"] = relationship()
    werkplek_type: Mapped["Werkplek | None"] = relationship()


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    naam: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[ItemType] = mapped_column(Enum(ItemType, name="item_type"))
    beschrijving: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prijs: Mapped[int] = mapped_column(default=0)


class InventarisItem(Base):
    __tablename__ = "inventaris"
    __table_args__ = (UniqueConstraint("speler_id", "item_id", name="uq_inventaris_speler_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    speler_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("spelers.discord_id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    aantal: Mapped[int] = mapped_column(default=0)

    speler: Mapped["Speler"] = relationship(back_populates="inventaris")
    item: Mapped["Item"] = relationship()


class Instelling(Base):
    """Admin-configurabele balanswaarden: cooldowns, spawn rates, e.d.
    Key/value zodat het admin panel nieuwe instellingen kan toevoegen
    zonder schemawijziging of bot-herstart."""

    __tablename__ = "instellingen"

    sleutel: Mapped[str] = mapped_column(String(64), primary_key=True)
    waarde: Mapped[str] = mapped_column(String(256))
    beschrijving: Mapped[str | None] = mapped_column(String(256), nullable=True)


class LogChannel(Base):
    """Koppelt per server en categorie een Discord-kanaal waar logberichten
    naartoe gestuurd worden. Categorieën zijn vrije tekst (bijv. 'main',
    'vangst'), ingesteld via /setlog, zodat nieuwe categorieën later zonder
    schemawijziging toegevoegd kunnen worden."""

    __tablename__ = "log_channels"
    __table_args__ = (UniqueConstraint("guild_id", "categorie", name="uq_log_channels_guild_categorie"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    categorie: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[int] = mapped_column(BigInteger)


class SpawnKanaal(Base):
    """Kanalen waar pets automatisch kunnen spawnen. Meerdere kanalen per
    server zijn toegestaan. Zie projectbrief sectie 8."""

    __tablename__ = "spawn_kanalen"
    __table_args__ = (UniqueConstraint("guild_id", "channel_id", name="uq_spawn_kanalen_guild_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    channel_id: Mapped[int] = mapped_column(BigInteger)


class PortalSessie(Base):
    """Inloggsessies van het web-adminpanel (portal/auth.py, 2026-07-29).

    Bewust in de database i.p.v. in het geheugen: Railway herstart de bot bij
    elke deploy, en met een in-memory sessiestore zou je daarbij elke keer
    uitgelogd worden. De token is een random secrets.token_urlsafe-waarde;
    verlopen rijen worden opgeruimd bij het aanmaken van een nieuwe sessie."""

    __tablename__ = "portal_sessies"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    discord_id: Mapped[int] = mapped_column(BigInteger)
    weergavenaam: Mapped[str] = mapped_column(String(64))
    # 2026-07-30, verzoek van de gebruiker ("openheid voor spelers"): niet-admin
    # serverleden mogen nu ook inloggen, maar alleen lezen. Vastgelegd op het
    # moment van inloggen (member_is_admin), niet bij elk request herberekend —
    # een rol-wijziging tijdens een lopende sessie vraagt dus om opnieuw
    # inloggen. Schrijf-routes controleren dit via portal/auth.py:vereist_admin.
    is_admin: Mapped[bool] = mapped_column(default=False)
    verloopt_op: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
