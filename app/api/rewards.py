"""Rewards catalog (admin write, resident read) + catalog image media."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.catalog.i18n import DEFAULT_LANG, normalize_lang, resolve_i18n
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import Redemption, RedemptionEvent, Reward, RewardShop, Town, User
from app.schemas import RewardCreate, RewardOut, RewardUpdate
from app.schemas.rewards import RewardMediaOut
from app.services.i18n_fields import apply_text_i18n
from app.services.reward_media import (
    delete_reward_media,
    get_reward_media,
    media_public_path,
    upsert_reward_media,
)
from app.services.towns import get_postal_code

router = APIRouter(prefix="/rewards", tags=["rewards"])

_I18N_FIELDS = {
    "name",
    "description",
    "conditions",
    "name_i18n",
    "description_i18n",
    "conditions_i18n",
    "i18n_source_lang",
}


def _to_out(reward: Reward, lang: str, fallback_lang: str) -> RewardOut:
    data = RewardOut.model_validate(reward)
    data.shop_ids = [rs.shop_id for rs in (reward.shops or [])]
    if reward.media is not None:
        data.image_url = media_public_path(reward.id)
        data.has_image = True
    else:
        data.image_url = None
        data.has_image = False
    data.name = resolve_i18n(reward.name_i18n, lang, fallback_lang, legacy=reward.name) or ""
    data.description = (
        resolve_i18n(reward.description_i18n, lang, fallback_lang, legacy=reward.description)
        or ""
    )
    data.conditions = resolve_i18n(
        reward.conditions_i18n, lang, fallback_lang, legacy=reward.conditions
    )
    return data


async def _load_reward(db: AsyncSession, reward_id: str) -> Reward | None:
    return (
        await db.execute(
            select(Reward)
            .options(selectinload(Reward.shops), selectinload(Reward.media))
            .where(Reward.id == reward_id)
        )
    ).scalars().first()


def _assert_admin_reward(user: User, reward: Reward) -> None:
    if reward.town_id != user.town_id or reward.is_fake != user.is_fake:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not found")


async def _apply_reward_i18n(
    reward: Reward,
    *,
    name: str | None,
    description: str | None,
    conditions: str | None,
    name_i18n: dict | None,
    description_i18n: dict | None,
    conditions_i18n: dict | None,
    i18n_source_lang: str | None,
    default_lang: str,
) -> None:
    src = i18n_source_lang or reward.i18n_source_lang or default_lang
    reward.i18n_source_lang = normalize_lang(src)

    filled_name, plain_name = await apply_text_i18n(
        payload_i18n=name_i18n,
        payload_plain=name,
        existing_i18n=reward.name_i18n,
        existing_plain=reward.name,
        source_lang=src,
        default_lang=default_lang,
    )
    filled_desc, plain_desc = await apply_text_i18n(
        payload_i18n=description_i18n,
        payload_plain=description,
        existing_i18n=reward.description_i18n,
        existing_plain=reward.description,
        source_lang=src,
        default_lang=default_lang,
    )
    reward.name_i18n = filled_name
    reward.description_i18n = filled_desc
    reward.name = plain_name or reward.name or ""
    reward.description = plain_desc or reward.description or ""

    if conditions_i18n is not None or conditions is not None:
        filled_cond, plain_cond = await apply_text_i18n(
            payload_i18n=conditions_i18n,
            payload_plain=conditions,
            existing_i18n=reward.conditions_i18n,
            existing_plain=reward.conditions,
            source_lang=src,
            default_lang=default_lang,
        )
        reward.conditions_i18n = filled_cond
        reward.conditions = plain_cond or None


@router.get("/public", response_model=list[RewardOut])
async def list_rewards_public(
    postal_code: str = Query(
        ...,
        min_length=4,
        max_length=10,
        description="Postal code that resolves to a town (e.g. 08380)",
    ),
    lang: str | None = Query(
        default=None,
        description="Response language (ca|es|en). Defaults to the town's default_lang.",
    ),
    demo: bool = Query(
        default=False,
        description="If true, return the fake/demo partition (is_fake=true)",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Public rewards catalog for the residents app (no auth).

    Resolves ``postal_code`` → town, then returns active rewards with
    name/description/conditions translated to ``lang``.
    """
    postal = await get_postal_code(db, postal_code.strip())
    if postal is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Unknown postal code",
        )
    town = await db.get(Town, postal.town_id)
    fallback = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    resolved = normalize_lang(lang) if lang else fallback

    rows = (
        await db.execute(
            select(Reward)
            .options(selectinload(Reward.shops), selectinload(Reward.media))
            .where(
                Reward.town_id == postal.town_id,
                Reward.is_fake.is_(demo),
                Reward.status == "active",
            )
            .order_by(Reward.created_at.desc())
        )
    ).scalars().all()
    return [_to_out(r, resolved, fallback) for r in rows]


@router.get("", response_model=list[RewardOut])
async def list_rewards(
    lang: str | None = Query(
        default=None,
        description="Response language (ca|es|en). Defaults to the town's default_lang.",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    town_id = user.town_id
    if not town_id and user.has_role("admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    stmt = (
        select(Reward)
        .options(selectinload(Reward.shops), selectinload(Reward.media))
        .where(Reward.is_fake.is_(user.is_fake))
    )
    if town_id:
        stmt = stmt.where(Reward.town_id == town_id)
    if user.has_role("resident") and not user.has_role("admin"):
        stmt = stmt.where(Reward.status == "active")
    stmt = stmt.order_by(Reward.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    town = await db.get(Town, town_id) if town_id else None
    fallback = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    resolved = normalize_lang(lang) if lang else fallback
    return [_to_out(r, resolved, fallback) for r in rows]


@router.post("", response_model=RewardOut, status_code=status.HTTP_201_CREATED)
async def create_reward(
    payload: RewardCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    town = await db.get(Town, user.town_id)
    default_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    data = payload.model_dump(exclude={"shop_ids", "image_url", *_I18N_FIELDS})
    reward = Reward(
        town_id=user.town_id, is_fake=user.is_fake, image_url=None, **data
    )
    await _apply_reward_i18n(
        reward,
        name=payload.name,
        description=payload.description,
        conditions=payload.conditions,
        name_i18n=payload.name_i18n,
        description_i18n=payload.description_i18n,
        conditions_i18n=payload.conditions_i18n,
        i18n_source_lang=payload.i18n_source_lang,
        default_lang=default_lang,
    )
    if not reward.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name is required")
    db.add(reward)
    await db.flush()
    for shop_id in payload.shop_ids:
        db.add(RewardShop(reward_id=reward.id, shop_id=shop_id))
    await db.commit()
    reward = await _load_reward(db, reward.id)
    return _to_out(reward, default_lang, default_lang)  # type: ignore[arg-type]


@router.patch("/{reward_id}", response_model=RewardOut)
async def update_reward(
    reward_id: str,
    payload: RewardUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    reward = await _load_reward(db, reward_id)
    if not reward:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not found")
    _assert_admin_reward(user, reward)
    town = await db.get(Town, user.town_id) if user.town_id else None
    default_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    data = payload.model_dump(exclude_unset=True)
    data.pop("image_url", None)
    shop_ids = data.pop("shop_ids", None)
    name = data.pop("name", None)
    description = data.pop("description", None)
    conditions = data.pop("conditions", None)
    name_i18n = data.pop("name_i18n", None)
    description_i18n = data.pop("description_i18n", None)
    conditions_i18n = data.pop("conditions_i18n", None)
    i18n_source_lang = data.pop("i18n_source_lang", None)
    for field, value in data.items():
        setattr(reward, field, value)
    if any(
        v is not None
        for v in (
            name,
            description,
            conditions,
            name_i18n,
            description_i18n,
            conditions_i18n,
            i18n_source_lang,
        )
    ):
        await _apply_reward_i18n(
            reward,
            name=name,
            description=description,
            conditions=conditions,
            name_i18n=name_i18n,
            description_i18n=description_i18n,
            conditions_i18n=conditions_i18n,
            i18n_source_lang=i18n_source_lang or reward.i18n_source_lang,
            default_lang=default_lang,
        )
    if shop_ids is not None:
        await db.execute(delete(RewardShop).where(RewardShop.reward_id == reward.id))
        for shop_id in shop_ids:
            db.add(RewardShop(reward_id=reward.id, shop_id=shop_id))
    await db.commit()
    reward = await _load_reward(db, reward_id)
    return _to_out(reward, default_lang, default_lang)  # type: ignore[arg-type]


@router.put("/{reward_id}/media", response_model=RewardMediaOut)
async def upload_reward_media(
    reward_id: str,
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    reward = await _load_reward(db, reward_id)
    if not reward:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not found")
    _assert_admin_reward(user, reward)
    row = await upsert_reward_media(db, reward_id=reward.id, upload=file)
    reward.image_url = media_public_path(reward.id)
    await db.commit()
    return RewardMediaOut(
        reward_id=reward.id,
        content_type=row.content_type,
        byte_size=row.byte_size,
        url=media_public_path(reward.id),
    )


@router.delete("/{reward_id}/media", status_code=status.HTTP_204_NO_CONTENT)
async def remove_reward_media(
    reward_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    reward = await _load_reward(db, reward_id)
    if not reward:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not found")
    _assert_admin_reward(user, reward)
    deleted = await delete_reward_media(db, reward_id=reward.id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Media not found")
    reward.image_url = None
    await db.commit()


@router.get("/{reward_id}/media")
async def download_reward_media(
    reward_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve catalog image bytes (public so <img src> works without auth)."""
    row = await get_reward_media(db, reward_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Media not found")
    return Response(
        content=row.data,
        media_type=row.content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Length": str(row.byte_size),
        },
    )


@router.delete("/{reward_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reward(
    reward_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete reward (and its media, shop links, redemptions)."""
    reward = await _load_reward(db, reward_id)
    if not reward:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not found")
    _assert_admin_reward(user, reward)

    red_ids = (
        await db.execute(
            select(Redemption.id).where(Redemption.reward_id == reward.id)
        )
    ).scalars().all()
    if red_ids:
        await db.execute(
            delete(RedemptionEvent).where(
                RedemptionEvent.redemption_id.in_(red_ids)
            )
        )
        await db.execute(delete(Redemption).where(Redemption.id.in_(red_ids)))

    await db.delete(reward)
    await db.commit()


@router.get("/{reward_id}", response_model=RewardOut)
async def get_reward(
    reward_id: str,
    lang: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    reward = await _load_reward(db, reward_id)
    if not reward or reward.is_fake != user.is_fake:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Reward not found")
    if user.has_role("admin") and reward.town_id != user.town_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Out of town scope")
    town = await db.get(Town, reward.town_id)
    fallback = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    resolved = normalize_lang(lang) if lang else fallback
    return _to_out(reward, resolved, fallback)
