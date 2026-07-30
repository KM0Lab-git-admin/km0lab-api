from datetime import datetime

from pydantic import BaseModel, Field


class ShopCategoryOut(BaseModel):
    slug: str
    sort_order: int
    active: bool
    # Resolved label for the requested lang (public) or default_lang.
    label: str | None = None
    # Full i18n map — exposed to admin/BO; may be omitted on public calls.
    label_i18n: dict | None = None
    i18n_source_lang: str = "ca"
    created_at: datetime

    model_config = {"from_attributes": True}


class ShopCategoryUpdate(BaseModel):
    label_i18n: dict | None = None
    i18n_source_lang: str | None = Field(default=None, pattern="^(ca|es|en)$")
    sort_order: int | None = None
    active: bool | None = None
