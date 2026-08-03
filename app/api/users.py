"""Authenticated user profile."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.demo import sync_user_fake_partition
from app.deps import get_current_user
from app.models import User
from app.schemas import UpdateUserIn, UserOut
from app.services.slugs import allocate_user_slug
from app.services.towns import get_postal_code
from app.utils.slug import slugify

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: UpdateUserIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump(exclude_unset=True)
    if "postal_code" in data:
        code = data["postal_code"]
        if code is None:
            user.postal_code = None
            user.postal_ref = None
        else:
            postal = await get_postal_code(db, code)
            if postal is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Unknown postal code",
                )
            user.postal_code = postal.postal_code
            user.postal_ref = postal
        # Demo KM0 (00000) lives on the is_fake partition; keep the user flag
        # in sync so /shops/for-me and POST /scans see the showcase catalog.
        sync_user_fake_partition(user, user.postal_code)
        data.pop("postal_code")

    if "slug" in data:
        wanted = slugify(data.pop("slug") or "")
        taken = (
            await db.execute(
                select(User.id).where(User.slug == wanted, User.id != user.id)
            )
        ).scalar_one_or_none()
        if taken:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Slug already in use"
            )
        user.slug = wanted

    for field, value in data.items():
        setattr(user, field, value)

    if not user.slug:
        user.slug = await allocate_user_slug(
            db,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            exclude_id=user.id,
        )

    await db.commit()
    await db.refresh(user, attribute_names=["postal_code"])
    if user.postal_code:
        user.postal_ref = await get_postal_code(db, user.postal_code)
    return UserOut.model_validate(user)
