"""Invitations: links, events, conversions, OTP bind, shop tax_id.

Revision ID: 0025_invitations
Revises: 0024_shop_category_emoji
Create Date: 2026-09-20
"""

from __future__ import annotations

import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_invitations"
down_revision: Union[str, None] = "0024_shop_category_emoji"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INVITE_ACTIONS = (
    {
        "type": "invite_person",
        "name": "Invitació de veí",
        "description": "Alta d'un veí completada des d'una invitació",
        "points": 100,
    },
    {
        "type": "invite_business",
        "name": "Invitació de comerç",
        "description": "Alta d'un comerç completada des d'una invitació",
        "points": 500,
    },
)


def _stable_action_id(town_id: str, *, is_fake: bool, type_: str) -> str:
    key = f"point-action:{town_id}:{'fake' if is_fake else 'real'}:{type_}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def upgrade() -> None:
    op.add_column(
        "otp_codes",
        sa.Column("invite_code", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "shops",
        sa.Column("tax_id", sa.String(length=32), nullable=True),
    )

    op.create_table(
        "invitation_links",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("public_code", sa.String(length=16), nullable=False),
        sa.Column("inviter_user_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["inviter_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"]),
        sa.UniqueConstraint("public_code", name="uq_invitation_links_public_code"),
        sa.UniqueConstraint(
            "inviter_user_id", "kind", name="uq_invitation_link_user_kind"
        ),
    )
    op.create_index("ix_invitation_links_inviter", "invitation_links", ["inviter_user_id"])
    op.create_index("ix_invitation_links_kind", "invitation_links", ["kind"])
    op.create_index("ix_invitation_links_town", "invitation_links", ["town_id"])
    op.create_index("ix_invitation_links_status", "invitation_links", ["status"])

    op.create_table(
        "invitation_events",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("link_id", sa.String(length=32), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["link_id"], ["invitation_links.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
    )
    op.create_index("ix_invitation_events_link", "invitation_events", ["link_id"])
    op.create_index("ix_invitation_events_type", "invitation_events", ["event_type"])
    op.create_index("ix_invitation_events_created", "invitation_events", ["created_at"])

    op.create_table(
        "invitation_conversions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("link_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("invitee_user_id", sa.String(length=32), nullable=True),
        sa.Column("shop_id", sa.String(length=32), nullable=True),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reward_points", sa.Integer(), nullable=False),
        sa.Column("points_tx_id", sa.String(length=32), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["link_id"], ["invitation_links.id"]),
        sa.ForeignKeyConstraint(["invitee_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"]),
        sa.ForeignKeyConstraint(["points_tx_id"], ["points_transactions.id"]),
        sa.UniqueConstraint("kind", "invitee_user_id", name="uq_invite_conv_kind_user"),
        sa.UniqueConstraint("shop_id", name="uq_invite_conv_shop"),
    )
    op.create_index(
        "ix_invitation_conversions_link", "invitation_conversions", ["link_id"]
    )
    op.create_index(
        "ix_invitation_conversions_status", "invitation_conversions", ["status"]
    )
    op.create_index(
        "ix_invitation_conversions_town", "invitation_conversions", ["town_id"]
    )

    op.create_unique_constraint(
        "uq_points_tx_user_type_ref",
        "points_transactions",
        ["user_id", "type", "ref_id"],
    )

    conn = op.get_bind()
    towns = conn.execute(
        sa.text("SELECT id FROM towns")
    ).fetchall()
    for (town_id,) in towns:
        for is_fake in (0, 1):
            for spec in _INVITE_ACTIONS:
                rid = _stable_action_id(
                    town_id, is_fake=bool(is_fake), type_=spec["type"]
                )
                existing = conn.execute(
                    sa.text("SELECT id FROM point_actions WHERE id = :id"),
                    {"id": rid},
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO point_actions (
                            id, town_id, type, name, description, points,
                            per_user_limit, active, visible_home, is_fake,
                            created_at, updated_at
                        ) VALUES (
                            :id, :town_id, :type, :name, :description, :points,
                            NULL, 1, 0, :is_fake, NOW(), NOW()
                        )
                        """
                    ),
                    {
                        "id": rid,
                        "town_id": town_id,
                        "type": spec["type"],
                        "name": spec["name"],
                        "description": spec["description"],
                        "points": spec["points"],
                        "is_fake": is_fake,
                    },
                )


def downgrade() -> None:
    op.drop_constraint(
        "uq_points_tx_user_type_ref", "points_transactions", type_="unique"
    )
    op.drop_table("invitation_conversions")
    op.drop_table("invitation_events")
    op.drop_table("invitation_links")
    op.drop_column("shops", "tax_id")
    op.drop_column("otp_codes", "invite_code")
