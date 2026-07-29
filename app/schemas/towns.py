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
    logo_url: str | None = None
    expiry_months: int | None = Field(default=None, ge=1)
    slug: str | None = Field(
        default=None, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )


class TownPostalCodeCreate(BaseModel):
    postal_code: str = Field(min_length=4, max_length=10)
    is_primary: bool = False
