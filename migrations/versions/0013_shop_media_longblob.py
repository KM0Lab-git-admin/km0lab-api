"""Use LONGBLOB for shop_media.data (up to 5 MB images)

Revision ID: 0013_shop_media_longblob
Revises: 0012_shop_media
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGBLOB

revision: str = "0013_shop_media_longblob"
down_revision: Union[str, None] = "0012_shop_media"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "shop_media",
        "data",
        existing_type=sa.LargeBinary(),
        type_=LONGBLOB(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "shop_media",
        "data",
        existing_type=LONGBLOB(),
        type_=sa.LargeBinary(),
        existing_nullable=False,
    )
