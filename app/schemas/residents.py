from datetime import datetime

from pydantic import BaseModel, EmailStr


class ResidentActivityOut(BaseModel):
    id: str
    type: str
    description: str | None
    points: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ResidentOut(BaseModel):
    id: str
    slug: str
    first_name: str | None
    last_name: str | None
    name: str | None
    points: int
    town_id: str | None
    contact_shared: bool
    email: EmailStr | None = None
    phone: str | None = None
    created_at: datetime
    activity: list[ResidentActivityOut] = []

    model_config = {"from_attributes": True}
