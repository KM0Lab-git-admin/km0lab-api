from datetime import datetime

from pydantic import BaseModel


class ScanIn(BaseModel):
    qr_code: str


class ScanOut(BaseModel):
    id: str
    shop_id: str
    shop_name: str | None = None
    points: int
    created_at: datetime
    balance: int
    available_at: str | None = None  # ISO date when this shop QR can award again
