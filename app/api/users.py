"""Authenticated user profile."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.qa import is_qa_email, is_qa_postal_code
from app.models import User
from app.schemas import (
    SignInMethodOut,
    SignInMethodsOut,
    UpdateUserIn,
    UserOut,
)
from app.services.identities import identities_of, is_hidden_email
from app.services.slugs import allocate_user_slug
from app.services.capacity import accept_terms
from app.services.residency import move_resident
from app.services.shop_review import user_out
from app.services.towns import get_postal_code
from app.utils.slug import slugify

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await user_out(db, user)


@router.get("/me/sign-in-methods", response_model=SignInMethodsOut)
async def my_sign_in_methods(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """How I get into my account: the door it was born with and the rest."""
    doors = await identities_of(db, user.id)
    return SignInMethodsOut(
        created_with=next((d.provider for d in doors if d.is_first), None),
        email=user.email,
        email_hidden=is_hidden_email(user.email),
        methods=[
            SignInMethodOut(
                provider=d.provider, linked_at=d.created_at, last_used_at=d.last_used_at
            )
            for d in doors
        ],
    )


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: UpdateUserIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump(exclude_unset=True)
    leave_demo = bool(data.pop("leave_demo", False))
    if "postal_code" in data:
        code = data["postal_code"]
        if is_qa_email(user.email) and not is_qa_postal_code(code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="QA accounts cannot leave the QA territory",
            )
        if code is not None:
            postal = await get_postal_code(db, code)
            if postal is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Unknown postal code",
                )
            # May stay where it is: an account does not cross from a real
            # municipality to the demo, and leaves the demo only when the
            # person confirms it (app/services/residency.py).
            await move_resident(db, user, postal, leave_demo=leave_demo)
        # ``null`` is ignored: an account that has a municipality keeps one.
        data.pop("postal_code")

    if "terms_version" in data:
        accept_terms(user, data.pop("terms_version"))

    # The birth date decides the day of a yearly bonus: once set it stays.
    # A different value is ignored (the answer carries the stored one), so
    # saving the rest of the profile keeps working.
    if "birth_date" in data and user.birth_date is not None:
        data.pop("birth_date")

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
