from datetime import datetime

from pydantic import BaseModel


class ScanIn(BaseModel):
    qr_code: str


class ScanOut(BaseModel):
    id: str
    shop_id: str
    points: int
    created_at: datetime
    balance: int
