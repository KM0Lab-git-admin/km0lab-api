"""Resident invitation links, resolve, events and summaries."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, get_optional_user, require_admin
from app.models import InvitationConversion, InvitationLink, User
from app.ratelimit import limiter
from app.schemas.invites import (
    AdminInviteListOut,
    InviteConversionListOut,
    InviteConversionOut,
    InviteEventIn,
    InviteLinkOut,
    InviteResolveIn,
    InviteResolveOut,
    InviteSummaryOut,
)
from app.services.invitations import (
    VALID_KINDS,
    conversion_to_dict,
    count_share_events,
    get_or_create_link,
    grant_conversion_reward,
    list_inviter_conversions,
    record_event,
    resolve_link,
    summary_for_inviter,
)
from app.schemas import MessageOut

router = APIRouter(prefix="/invites", tags=["invites"])


def _limit() -> str:
    return "60/hour"


@router.get("/me/link", response_model=InviteLinkOut)
async def my_invite_link(
    kind: str = Query(..., pattern="^(person|business)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Complete your town before inviting",
        )
    try:
        link = await get_or_create_link(db, user=user, kind=kind)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return InviteLinkOut(
        public_code=link.public_code, kind=link.kind, town_id=link.town_id
    )


@router.get("/me/summary", response_model=InviteSummaryOut)
async def my_invite_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await summary_for_inviter(db, inviter_user_id=user.id)
    return InviteSummaryOut(**data)


@router.get("/me/conversions", response_model=InviteConversionListOut)
async def my_invite_conversions(
    kind: str | None = Query(default=None, pattern="^(person|business)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows, total, by_id = await list_inviter_conversions(
        db, inviter_user_id=user.id, kind=kind, offset=offset, limit=limit
    )
    items = [
        InviteConversionOut(
            **conversion_to_dict(
                row,
                public_code=by_id[row.link_id].public_code,
                inviter_user_id=user.id,
            )
        )
        for row in rows
    ]
    return InviteConversionListOut(items=items, total=total)


@router.post("/resolve", response_model=InviteResolveOut)
@limiter.limit(_limit)
async def resolve_invite(
    request: Request,
    payload: InviteResolveIn,
    db: AsyncSession = Depends(get_db),
):
    resolved = await resolve_link(
        db,
        code=payload.code,
        record=True,
        user_agent=request.headers.get("user-agent"),
    )
    if resolved is None:
        return InviteResolveOut(valid=False)
    link, town = resolved
    await db.commit()
    return InviteResolveOut(
        valid=True,
        code=link.public_code,
        kind=link.kind,
        town_id=link.town_id,
        town_name=town.name,
    )


@router.post("/events", response_model=MessageOut)
@limiter.limit(_limit)
async def invite_event(
    request: Request,
    payload: InviteEventIn,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.invitations import is_preview_bot

    if is_preview_bot(request.headers.get("user-agent")):
        return MessageOut(message="ok")
    try:
        await record_event(
            db,
            event_type=payload.type,
            code=payload.code,
            channel=payload.channel,
            actor_user_id=user.id if user else None,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return MessageOut(message="ok")


admin_router = APIRouter(prefix="/admin/invites", tags=["admin-invites"])


def _admin_conv_out(
    row: InvitationConversion, link: InvitationLink | None
) -> InviteConversionOut:
    return InviteConversionOut(
        **conversion_to_dict(
            row,
            public_code=link.public_code if link else None,
            inviter_user_id=link.inviter_user_id if link else None,
        )
    )


@admin_router.get("", response_model=AdminInviteListOut)
async def admin_list_invites(
    kind: str | None = Query(default=None, pattern="^(person|business)$"),
    conv_status: str | None = Query(default=None, alias="status"),
    inviter_user_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")

    from sqlalchemy import select

    filters = [InvitationConversion.town_id == user.town_id]
    if kind in VALID_KINDS:
        filters.append(InvitationConversion.kind == kind)
    if conv_status in {"pending_reward", "granted", "failed"}:
        filters.append(InvitationConversion.status == conv_status)
    if inviter_user_id:
        inviter_links = (
            await db.execute(
                select(InvitationLink.id).where(
                    InvitationLink.inviter_user_id == inviter_user_id,
                    InvitationLink.town_id == user.town_id,
                )
            )
        ).scalars().all()
        filters.append(InvitationConversion.link_id.in_(inviter_links or ["__none__"]))

    total = (
        await db.execute(
            select(InvitationConversion).where(*filters)
        )
    ).scalars().all()
    total.sort(key=lambda c: c.created_at or c.id, reverse=True)
    page = total[offset : offset + limit]
    link_ids = {c.link_id for c in page}
    links = (
        (
            await db.execute(
                select(InvitationLink).where(InvitationLink.id.in_(link_ids))
            )
        ).scalars().all()
        if link_ids
        else []
    )
    by_id = {link.id: link for link in links}

    persons = sum(1 for c in total if c.kind == "person" and c.completed_at)
    businesses = sum(1 for c in total if c.kind == "business" and c.completed_at)
    points_granted = sum(c.reward_points for c in total if c.status == "granted")
    share_events = await count_share_events(db, town_id=user.town_id)

    return AdminInviteListOut(
        conversions=[_admin_conv_out(c, by_id.get(c.link_id)) for c in page],
        total=len(total),
        persons_registered=persons,
        businesses_registered=businesses,
        points_granted=points_granted,
        share_events=share_events,
    )


@admin_router.get(
    "/conversions/{conversion_id}", response_model=InviteConversionOut
)
async def admin_get_conversion(
    conversion_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(InvitationConversion, conversion_id)
    if conv is None or conv.town_id != user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversion not found")
    link = await db.get(InvitationLink, conv.link_id)
    return _admin_conv_out(conv, link)


@admin_router.post(
    "/conversions/{conversion_id}/retry-reward",
    response_model=InviteConversionOut,
)
async def admin_retry_reward(
    conversion_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(InvitationConversion, conversion_id)
    if conv is None or conv.town_id != user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversion not found")
    conv = await grant_conversion_reward(db, conv)
    await db.commit()
    await db.refresh(conv)
    link = await db.get(InvitationLink, conv.link_id)
    return _admin_conv_out(conv, link)
