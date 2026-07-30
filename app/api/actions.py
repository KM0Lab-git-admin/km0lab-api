"""Point actions CRUD (admin) + public catalog by postal code (i18n).

Partitioned by ``user.is_fake``: demo admin only sees/edits fake actions.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.action_labels import (
    DEFAULT_LANG,
    fixed_i18n,
    fixed_label,
    is_fixed_action_type,
)
from app.catalog.i18n import normalize_lang, resolve_i18n
from app.db import get_db
from app.deps import require_admin
from app.models import PointAction, Town, User
from app.schemas import PointActionCreate, PointActionOut, PointActionUpdate
from app.services.i18n_fields import apply_text_i18n
from app.services.towns import get_postal_code

router = APIRouter(prefix="/actions", tags=["actions"])


def _resolve_out(action: PointAction, lang: str, fallback_lang: str) -> PointActionOut:
    """Build a PointActionOut with name/description/conditions resolved for ``lang``.

    Fixed types pull from the catalog; custom types pull from *_i18n with
    safe fallbacks. Admin Out still includes the full i18n maps.
    """
    out = PointActionOut.model_validate(action)
    if is_fixed_action_type(action.type):
        label = fixed_label(action.type, lang)
        out.name = label["name"]
        out.description = label["description"]
        full = fixed_i18n(action.type)
        out.name_i18n = {k: v["name"] for k, v in full.items()}
        out.description_i18n = {k: v["description"] for k, v in full.items()}
    else:
        out.name = resolve_i18n(
            action.name_i18n, lang, fallback_lang, legacy=action.name
        )
        out.description = resolve_i18n(
            action.description_i18n, lang, fallback_lang, legacy=action.description
        )
    out.conditions = resolve_i18n(
        action.conditions_i18n, lang, fallback_lang, legacy=action.conditions
    )
    return out


async def _apply_action_fields(
    action: PointAction,
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
    """Set name/description/conditions/i18n honoring fixed vs custom types."""
    src = i18n_source_lang or default_lang
    action.i18n_source_lang = normalize_lang(src)

    if is_fixed_action_type(action.type):
        full = fixed_i18n(action.type)
        action.name_i18n = {k: v["name"] for k, v in full.items()}
        action.description_i18n = {k: v["description"] for k, v in full.items()}
        action.name = full[DEFAULT_LANG]["name"]
        action.description = full[DEFAULT_LANG]["description"]
    else:
        filled_name, plain_name = await apply_text_i18n(
            payload_i18n=name_i18n,
            payload_plain=name,
            existing_i18n=action.name_i18n,
            existing_plain=action.name,
            source_lang=src,
            default_lang=default_lang,
        )
        filled_desc, plain_desc = await apply_text_i18n(
            payload_i18n=description_i18n,
            payload_plain=description,
            existing_i18n=action.description_i18n,
            existing_plain=action.description,
            source_lang=src,
            default_lang=default_lang,
        )
        action.name_i18n = filled_name
        action.description_i18n = filled_desc
        action.name = plain_name or action.name or ""
        action.description = plain_desc or action.description or ""

    if conditions_i18n is not None or conditions is not None:
        filled_cond, plain_cond = await apply_text_i18n(
            payload_i18n=conditions_i18n,
            payload_plain=conditions,
            existing_i18n=action.conditions_i18n,
            existing_plain=action.conditions,
            source_lang=src,
            default_lang=default_lang,
        )
        action.conditions_i18n = filled_cond
        action.conditions = plain_cond or None


@router.get("/public", response_model=list[PointActionOut])
async def list_actions_public(
    postal_code: str = Query(
        ...,
        min_length=4,
        max_length=10,
        description="Postal code that resolves to a town (e.g. 08380)",
    ),
    visible_home: bool | None = Query(
        default=None,
        description=(
            "true = only home-featured actions; "
            "false = only non-home actions; "
            "omit = all active actions for the town"
        ),
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
    """Public catalog for the residents app (no auth).

    Resolves ``postal_code`` → town, then returns active actions with
    name/description translated to ``lang`` (fallback to the town's
    default_lang, then ca). Use ``visible_home=true`` for the home strip.
    """
    postal = await get_postal_code(db, postal_code.strip())
    if postal is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Unknown postal code",
        )

    town = await db.get(Town, postal.town_id)
    fallback_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    resolved_lang = normalize_lang(lang) if lang else fallback_lang

    stmt = (
        select(PointAction)
        .where(
            PointAction.town_id == postal.town_id,
            PointAction.is_fake.is_(demo),
            PointAction.active.is_(True),
        )
        .order_by(PointAction.created_at.desc())
    )
    if visible_home is not None:
        stmt = stmt.where(PointAction.visible_home.is_(visible_home))

    rows = (await db.execute(stmt)).scalars().all()
    return [_resolve_out(a, resolved_lang, fallback_lang) for a in rows]


@router.get("", response_model=list[PointActionOut])
async def list_actions(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    rows = (
        await db.execute(
            select(PointAction)
            .where(
                PointAction.town_id == user.town_id,
                PointAction.is_fake.is_(user.is_fake),
            )
            .order_by(PointAction.created_at.desc())
        )
    ).scalars().all()
    town = await db.get(Town, user.town_id)
    fallback_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    return [_resolve_out(a, fallback_lang, fallback_lang) for a in rows]


@router.post("", response_model=PointActionOut, status_code=status.HTTP_201_CREATED)
async def create_action(
    payload: PointActionCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    town = await db.get(Town, user.town_id)
    default_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    data = payload.model_dump(
        exclude={
            "name",
            "description",
            "conditions",
            "name_i18n",
            "description_i18n",
            "conditions_i18n",
            "i18n_source_lang",
        }
    )
    action = PointAction(town_id=user.town_id, is_fake=user.is_fake, **data)
    await _apply_action_fields(
        action,
        name=payload.name,
        description=payload.description,
        conditions=payload.conditions,
        name_i18n=payload.name_i18n,
        description_i18n=payload.description_i18n,
        conditions_i18n=payload.conditions_i18n,
        i18n_source_lang=payload.i18n_source_lang,
        default_lang=default_lang,
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return _resolve_out(action, default_lang, default_lang)


async def _get_town_action(
    db: AsyncSession, *, action_id: str, town_id: str, is_fake: bool
) -> PointAction:
    action = await db.get(PointAction, action_id)
    if (
        not action
        or action.town_id != town_id
        or action.is_fake != is_fake
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Action not found")
    return action


@router.patch("/{action_id}", response_model=PointActionOut)
async def update_action(
    action_id: str,
    payload: PointActionUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = await _get_town_action(
        db, action_id=action_id, town_id=user.town_id, is_fake=user.is_fake
    )
    town = await db.get(Town, user.town_id)
    default_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    data = payload.model_dump(exclude_unset=True)
    name = data.pop("name", None)
    description = data.pop("description", None)
    conditions = data.pop("conditions", None)
    name_i18n = data.pop("name_i18n", None)
    description_i18n = data.pop("description_i18n", None)
    conditions_i18n = data.pop("conditions_i18n", None)
    i18n_source_lang = data.pop("i18n_source_lang", None)
    for field, value in data.items():
        setattr(action, field, value)
    text_touched = any(
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
    )
    if text_touched or not is_fixed_action_type(action.type):
        await _apply_action_fields(
            action,
            name=name,
            description=description,
            conditions=conditions,
            name_i18n=name_i18n,
            description_i18n=description_i18n,
            conditions_i18n=conditions_i18n,
            i18n_source_lang=i18n_source_lang or action.i18n_source_lang,
            default_lang=default_lang,
        )
    await db.commit()
    await db.refresh(action)
    return _resolve_out(action, default_lang, default_lang)


@router.post("/{action_id}/activate", response_model=PointActionOut)
async def activate_action(
    action_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = await _get_town_action(
        db, action_id=action_id, town_id=user.town_id, is_fake=user.is_fake
    )
    action.active = True
    await db.commit()
    await db.refresh(action)
    town = await db.get(Town, user.town_id)
    fallback_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    return _resolve_out(action, fallback_lang, fallback_lang)


@router.post("/{action_id}/deactivate", response_model=PointActionOut)
async def deactivate_action(
    action_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = await _get_town_action(
        db, action_id=action_id, town_id=user.town_id, is_fake=user.is_fake
    )
    action.active = False
    await db.commit()
    await db.refresh(action)
    town = await db.get(Town, user.town_id)
    fallback_lang = (town.default_lang if town else DEFAULT_LANG) or DEFAULT_LANG
    return _resolve_out(action, fallback_lang, fallback_lang)


@router.delete("/{action_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_action(
    action_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = await _get_town_action(
        db, action_id=action_id, town_id=user.town_id, is_fake=user.is_fake
    )
    await db.delete(action)
    await db.commit()
