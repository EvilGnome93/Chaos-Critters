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
    vereiste_werk_genen: Mapped[str] = mapped_column(String(32))
    output_per_uur: Mapped[float] = mapped_column(Numeric(6, 2))
    capaciteit: Mapped[int] = mapped_column(default=1)
    # Nog niet afgedwongen: hoeveel pets tegelijk hier mogen werken. Relevant
    # zodra werkplekken gedeeld worden (bijv. gilde-feature, sectie 16).
    opbrengst_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)

    pet_soorten: Mapped[list["PetSoort"]] = relationship(back_populates="werkplek_voorkeur")
    opbrengst_item: Mapped["Item | None"] = relationship()


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

    tier: Mapped["Tier"] = relationship(back_populates="pet_soorten")
    werkplek_voorkeur: Mapped["Werkplek | None"] = relationship(back_populates="pet_soorten")
    huisdieren: Mapped[list["Huisdier"]] = relationship(back_populates="soort")


class Speler(Base):
    __tablename__ = "spelers"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    currency: Mapped[int] = mapped_column(default=0)
    level: Mapped[int] = mapped_column(default=1)
    xp: Mapped[int] = mapped_column(default=0)
    mmr: Mapped[int] = mapped_column(default=1000)
    # Alvast aanwezig voor het gilde-systeem, komt later; blijft voorlopig NULL.
    gilde_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    huisdieren: Mapped[list["Huisdier"]] = relationship(back_populates="eigenaar")
    inventaris: Mapped[list["InventarisItem"]] = relationship(back_populates="speler")


class Huisdier(Base):
    __tablename__ = "huisdieren"

    id: Mapped[int] = mapped_column(primary_key=True)
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

    level: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

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
