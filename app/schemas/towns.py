from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class TownOut(BaseModel):
    id: str
    name: str
    entity_name: str
    entity_type: str
    contact_email: EmailStr | str
    manager_name: str
    logo_url: str | None
    points_per_euro: int
    expiry_months: int | None
    default_visit_points: int
    default_lang: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TownUpdate(BaseModel):
    entity_name: str | None = Field(default=None, max_length=160)
    entity_type: str | None = Field(default=None, pattern="^(city_council|private)$")
    contact_email: EmailStr | None = None
    manager_name: str | None = Field(default=None, max_length=120)
    logo_url: str | None = None
    points_per_euro: int | None = Field(default=None, ge=1)
    expiry_months: int | None = Field(default=None, ge=1)
    default_visit_points: int | None = Field(default=None, ge=0)
    default_lang: str | None = Field(default=None, pattern="^(ca|es|en)$")
