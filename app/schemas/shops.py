from datetime import datetime



from pydantic import BaseModel, EmailStr, Field



from app.schemas.opening_hours import OpeningHours





class ShopOut(BaseModel):

    id: str

    town_id: str

    name: str

    emoji: str | None

    # Absolute API paths when BLOB media exists; else legacy URL or null.

    logo_url: str | None

    hero_url: str | None

    has_logo: bool = False

    has_hero: bool = False

    categories: list[str]

    contact_email: str

    visit_points: int

    address: str | None

    postal_code: str | None

    phone: str | None

    website: str | None

    description: str | None

    description_i18n: dict | None = None

    i18n_source_lang: str = "ca"

    opening_hours: OpeningHours | None

    status: str

    qr_code: str | None

    is_fake: bool = False

    created_at: datetime

    updated_at: datetime



    model_config = {"from_attributes": True}





class ShopCreate(BaseModel):

    name: str = Field(max_length=160)

    emoji: str | None = None

    categories: list[str] = Field(default_factory=list)

    contact_email: EmailStr

    visit_points: int | None = Field(default=None, ge=0)

    address: str | None = None

    description: str | None = None

    description_i18n: dict | None = None

    i18n_source_lang: str | None = Field(default=None, pattern="^(ca|es|en)$")

    opening_hours: OpeningHours | None = None





class ShopUpdate(BaseModel):

    name: str | None = Field(default=None, max_length=160)

    emoji: str | None = None

    categories: list[str] | None = None

    contact_email: EmailStr | None = None

    visit_points: int | None = Field(default=None, ge=0)

    address: str | None = None

    description: str | None = None

    description_i18n: dict | None = None

    i18n_source_lang: str | None = Field(default=None, pattern="^(ca|es|en)$")

    status: str | None = Field(default=None, pattern="^(active|pending|inactive)$")

    opening_hours: OpeningHours | None = None





class ShopProfileUpdate(BaseModel):

    """Merchant profile / listing card (fitxa). Logo/hero via media upload."""



    name: str | None = Field(default=None, max_length=160)

    categories: list[str] | None = None

    description: str | None = None

    description_i18n: dict | None = None

    i18n_source_lang: str | None = Field(default=None, pattern="^(ca|es|en)$")

    address: str | None = None

    postal_code: str | None = None

    phone: str | None = None

    website: str | None = None

    opening_hours: OpeningHours | None = None





class ShopMediaOut(BaseModel):

    shop_id: str

    kind: str

    content_type: str

    byte_size: int

    url: str





class QrOut(BaseModel):

    shop_id: str

    qr_code: str

    scan_url: str

    png_url: str

    visit_points: int

    total_scans: int = 0

    points_awarded: int = 0


