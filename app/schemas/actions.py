from datetime import datetime

from pydantic import BaseModel, Field


class PointActionOut(BaseModel):
    id: str
    town_id: str
    type: str
    name: str
    description: str
    points: int
    per_user_limit: int | None
    total_limit: int | None
    valid_from: datetime | None
    valid_until: datetime | None
    conditions: str | None
    active: bool
    url: str | None
    event_id: str | None
    cooldown_days: int | None = None
    is_fake: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PointActionCreate(BaseModel):
    type: str = Field(
        pattern="^(signup|birthday|qr_scan|web_visit|web_signup|event|custom)$"
    )
    name: str = Field(max_length=200)
    description: str = ""
    points: int = Field(ge=0)
    per_user_limit: int | None = Field(default=None, ge=1)
    total_limit: int | None = Field(default=None, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    conditions: str | None = None
    active: bool = True
    url: str | None = None
    event_id: str | None = None
    cooldown_days: int | None = Field(default=None, ge=1)


class PointActionUpdate(BaseModel):
    type: str | None = Field(
        default=None,
        pattern="^(signup|birthday|qr_scan|web_visit|web_signup|event|custom)$",
    )
    name: str | None = None
    description: str | None = None
    points: int | None = Field(default=None, ge=0)
    per_user_limit: int | None = None
    total_limit: int | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    conditions: str | None = None
    active: bool | None = None
    url: str | None = None
    event_id: str | None = None
    cooldown_days: int | None = Field(default=None, ge=1)
