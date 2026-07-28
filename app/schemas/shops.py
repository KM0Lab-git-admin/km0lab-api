from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ShopOut(BaseModel):
    id: str
    town_id: str
    name: str
    emoji: str | None
    logo_url: str | None
    hero_url: str | None
    categories: list
    contact_email: str
    visit_points: int
    address: str | None
    postal_code: str | None
    phone: str | None
    website: str | None
    description: str | None
    opening_hours: dict | None
    status: str
    qr_code: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ShopCreate(BaseModel):
    name: str = Field(max_length=160)
    emoji: str | None = None
    logo_url: str | None = None
    categories: list[str] = Field(default_factory=list)
    contact_email: EmailStr
    visit_points: int = Field(default=10, ge=0)
    address: str | None = None


class ShopUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    emoji: str | None = None
    logo_url: str | None = None
    categories: list[str] | None = None
    contact_email: EmailStr | None = None
    visit_points: int | None = Field(default=None, ge=0)
    address: str | None = None
    status: str | None = Field(default=None, pattern="^(active|pending|inactive)$")


class ShopProfileUpdate(BaseModel):
    """Merchant profile / listing card (fitxa)."""

    name: str | None = Field(default=None, max_length=160)
    categories: list[str] | None = None
    description: str | None = None
    logo_url: str | None = None
    hero_url: str | None = None
    address: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    website: str | None = None
    opening_hours: dict | None = None


class QrOut(BaseModel):
    shop_id: str
    qr_code: str
    visit_points: int
