from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class TownPostalCodeOut(BaseModel):
    postal_code: str
    is_primary: bool

    model_config = {"from_attributes": True}


class TownOut(BaseModel):
    id: str
    name: str
    slug: str
    entity_name: str
    entity_type: str
    contact_email: EmailStr | str
    manager_name: str
    logo_url: str | None
    has_logo: bool = False
    art_url: str | None = None
    points_per_euro: int = 200
    default_visit_points: int = 10
    default_lang: str = "ca"
    expiry_months: int | None
    postal_codes: list[TownPostalCodeOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TownUpdate(BaseModel):
    entity_name: str | None = Field(default=None, max_length=160)
    entity_type: str | None = Field(default=None, pattern="^(city_council|private)$")
    contact_email: EmailStr | None = None
    manager_name: str | None = Field(default=None, max_length=120)
    logo_url: str | None = None  # ignored for data URLs; use PUT .../media/logo
    points_per_euro: int | None = Field(default=None, ge=1)
    default_visit_points: int | None = Field(default=None, ge=0)
    default_lang: str | None = Field(default=None, pattern="^(ca|es|en)$")
    expiry_months: int | None = Field(default=None, ge=1)
    slug: str | None = Field(
        default=None, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )


class TownPostalCodeCreate(BaseModel):
    postal_code: str = Field(min_length=4, max_length=10)
    is_primary: bool = False


class LocalityOut(BaseModel):
    """A town (població) of the municipality, as the residents app sees it."""

    id: str
    name: str
    slug: str = ""
    postal_codes: list[str] = []
    art_url: str | None = None


class TownPublicOut(BaseModel):
    """Public town card for the residents app (no auth).

    The card describes **the town of the postal code asked for**: ``name``,
    ``slug``, ``postal_codes`` and ``art_url`` are the locality's, because
    that is what a resident calls "my town". ``art_url`` is its
    illustration; ``None`` means the app paints its generic one.

    The municipality (the managed scope: point rules, actions, rewards) is
    ``id`` / ``municipality_id`` and ``municipality_name``; the app does not
    show its name. ``localities`` lists every town of the municipality: one
    for a single-town municipality, several when it groups towns.
    """

    id: str
    name: str
    slug: str = ""
    postal_codes: list[str] = []
    logo_url: str | None = None
    has_logo: bool = False
    art_url: str | None = None
    locality_id: str | None = None
    municipality_id: str | None = None
    municipality_name: str | None = None
    localities: list[LocalityOut] = []
    points_per_euro: int = 200
    default_visit_points: int = 10
    default_lang: str = "ca"
    expiry_months: int | None = None


class TownMediaOut(BaseModel):
    town_id: str
    kind: str
    content_type: str
    byte_size: int
    url: str
