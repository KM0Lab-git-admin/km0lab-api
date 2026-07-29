from datetime import date

from pydantic import BaseModel, Field


class UpdateUserIn(BaseModel):
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=120)
    slug: str | None = Field(
        default=None, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    lang: str | None = Field(default=None, pattern="^(ca|es|en)$")
    postal_code: str | None = Field(default=None, max_length=10)
    phone: str | None = Field(default=None, max_length=40)
    birth_date: date | None = None
    contact_shared: bool | None = None
