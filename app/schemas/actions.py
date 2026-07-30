from datetime import datetime



from pydantic import BaseModel, Field





ACTION_TYPE_PATTERN = (

    "^(signup|birthday|qr_scan|first_scan|web_visit|web_signup|event|custom)$"

)





class PointActionOut(BaseModel):

    id: str

    town_id: str

    type: str

    name: str | None = None

    description: str | None = None

    name_i18n: dict | None = None

    description_i18n: dict | None = None

    conditions_i18n: dict | None = None

    i18n_source_lang: str = "ca"

    points: int

    per_user_limit: int | None

    total_limit: int | None

    valid_from: datetime | None

    valid_until: datetime | None

    conditions: str | None

    active: bool

    visible_home: bool = True

    url: str | None

    event_id: str | None

    cooldown_days: int | None = None

    is_fake: bool = False

    created_at: datetime

    updated_at: datetime



    model_config = {"from_attributes": True}





class PointActionCreate(BaseModel):

    type: str = Field(pattern=ACTION_TYPE_PATTERN)

    name: str | None = Field(default=None, max_length=200)

    description: str | None = Field(default=None)

    name_i18n: dict | None = None

    description_i18n: dict | None = None

    conditions_i18n: dict | None = None

    i18n_source_lang: str | None = Field(default=None, pattern="^(ca|es|en)$")

    points: int = Field(ge=0)

    per_user_limit: int | None = Field(default=None, ge=1)

    total_limit: int | None = Field(default=None, ge=1)

    valid_from: datetime | None = None

    valid_until: datetime | None = None

    conditions: str | None = None

    active: bool = True

    visible_home: bool = True

    url: str | None = None

    event_id: str | None = None

    cooldown_days: int | None = Field(default=None, ge=1)





class PointActionUpdate(BaseModel):

    type: str | None = Field(default=None, pattern=ACTION_TYPE_PATTERN)

    name: str | None = None

    description: str | None = None

    name_i18n: dict | None = None

    description_i18n: dict | None = None

    conditions_i18n: dict | None = None

    i18n_source_lang: str | None = Field(default=None, pattern="^(ca|es|en)$")

    points: int | None = Field(default=None, ge=0)

    per_user_limit: int | None = None

    total_limit: int | None = None

    valid_from: datetime | None = None

    valid_until: datetime | None = None

    conditions: str | None = None

    active: bool | None = None

    visible_home: bool | None = None

    url: str | None = None

    event_id: str | None = None

    cooldown_days: int | None = Field(default=None, ge=1)


