from pydantic import BaseModel, Field

from app.schemas.auth import UserOut


class UpdateUserIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    lang: str | None = Field(default=None, pattern="^(ca|es|en)$")
    postal_code: str | None = Field(default=None, max_length=10)
    town: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    contact_shared: bool | None = None
    town_id: str | None = None


# re-export for convenience
__all__ = ["UpdateUserIn", "UserOut"]
