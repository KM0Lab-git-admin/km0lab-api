"""Opening hours JSON stored in shops.opening_hours."""

from __future__ import annotations

import re
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _check_time(value: str | None) -> str | None:
    if value is None:
        return None
    if not _TIME_RE.match(value):
        raise ValueError("time must be HH:MM (00:00–23:59)")
    return value


class DayHours(BaseModel):
    """One weekday. closed=true → times ignored/null (UI toggle off)."""

    closed: bool = True
    opens: str | None = None
    closes: str | None = None
    opens_2: str | None = None
    closes_2: str | None = None

    @field_validator("opens", "closes", "opens_2", "closes_2", mode="before")
    @classmethod
    def empty_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @field_validator("opens", "closes", "opens_2", "closes_2")
    @classmethod
    def validate_time(cls, v: str | None) -> str | None:
        return _check_time(v)

    @model_validator(mode="before")
    @classmethod
    def clear_times_when_closed(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("closed") is True:
            return {
                **data,
                "opens": None,
                "closes": None,
                "opens_2": None,
                "closes_2": None,
            }
        return data

    @model_validator(mode="after")
    def consistency(self) -> Self:
        if self.closed:
            return self
        if not self.opens or not self.closes:
            raise ValueError("opens and closes are required when closed=false")
        if (self.opens_2 is None) != (self.closes_2 is None):
            raise ValueError("opens_2 and closes_2 must both be set or both null")
        return self


class OpeningHours(BaseModel):
    """Weekly schedule JSON for shops.opening_hours (MySQL JSON column).

    Example:
    {
      "monday": {"closed": false, "opens": "07:00", "closes": "20:00"},
      "tuesday": {"closed": false, "opens": "07:00", "closes": "20:00",
                  "opens_2": null, "closes_2": null},
      ...
      "sunday": {"closed": true}
    }
    """

    monday: DayHours = Field(default_factory=DayHours)
    tuesday: DayHours = Field(default_factory=DayHours)
    wednesday: DayHours = Field(default_factory=DayHours)
    thursday: DayHours = Field(default_factory=DayHours)
    friday: DayHours = Field(default_factory=DayHours)
    saturday: DayHours = Field(default_factory=DayHours)
    sunday: DayHours = Field(default_factory=DayHours)

    @classmethod
    def default_week(
        cls,
        *,
        opens: str = "09:00",
        closes: str = "20:00",
        weekend_closed: bool = True,
    ) -> OpeningHours:
        open_day = DayHours(closed=False, opens=opens, closes=closes)
        closed_day = DayHours(closed=True)
        days = {
            d: (closed_day if weekend_closed and d in ("saturday", "sunday") else open_day)
            for d in _WEEKDAYS
        }
        return cls(**days)
