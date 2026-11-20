"""Registering the administrator of a municipality (scripts/add_admin)."""

import pytest
from sqlalchemy import select

from app.models import User
from app.roles import flags_from_roles
from app.security import create_access_token
from app.services.admins import AdminRefused, register_admin
from app.services.towns import ensure_demo_town, find_municipality
from tests._municipalities import API, baix_montseny, malgrat

pytestmark = pytest.mark.asyncio

EMAIL = "tecnic@baixmontseny.test"


async def _user(db, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email))).scalars().first()


async def test_find_municipality_by_what_a_person_types(db_session):
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)

    for ref in ("Baix Montseny", "baix-montseny", "17450", "Hostalric", " Breda "):
        assert (await find_municipality(db_session, ref)).id == baix.id
    for ref in ("Malgrat de Mar", "08380", "malgrat-de-mar"):
        assert (await find_municipality(db_session, ref)).id == mal.id
    assert await find_municipality(db_session, "Girona") is None
    assert await find_municipality(db_session, "") is None


async def test_new_admin_administers_the_whole_municipality(client, db_session):
    await malgrat(db_session)
    baix = await baix_montseny(db_session)

    report = await register_admin(
        db_session, town=baix, email=f"  {EMAIL.upper()} ", first_name="Laia"
    )
    await db_session.commit()

    assert report.outcome == "created" and report.other_admins == []
    user = await _user(db_session, EMAIL)
    assert user.roles == ["resident", "admin"]
    assert user.is_fake is False and user.points == 0
    assert user.postal_code == "17400"  # the municipality's primary postal code

    headers = {
        "Authorization": "Bearer "
        + create_access_token(user.id, roles=user.roles, town_id=baix.id)
    }
    mine = await client.get(f"{API}/towns/me", headers=headers)
    assert mine.status_code == 200 and mine.json()["name"] == "Baix Montseny"
    assert len(mine.json()["localities"]) == 3

    # Asking again is harmless.
    again = await register_admin(db_session, town=baix, email=EMAIL)
    assert again.outcome == "unchanged"


async def test_a_municipality_has_one_admin_unless_asked(db_session):
    baix = await baix_montseny(db_session)
    await register_admin(db_session, town=baix, email=EMAIL)
    await db_session.commit()

    with pytest.raises(AdminRefused, match="already has an administrator"):
        await register_admin(db_session, town=baix, email="altre@test.cat")
    assert await _user(db_session, "altre@test.cat") is None

    report = await register_admin(
        db_session, town=baix, email="altre@test.cat", allow_additional=True
    )
    assert report.outcome == "created" and report.other_admins == [EMAIL]


async def test_resident_of_the_municipality_is_promoted_in_place(db_session):
    baix = await baix_montseny(db_session)
    db_session.add(
        User(email=EMAIL, slug="veina", postal_code="17450", points=120)
    )
    await db_session.commit()

    report = await register_admin(db_session, town=baix, email=EMAIL)

    user = await _user(db_session, EMAIL)
    assert report.outcome == "promoted"
    assert user.roles == ["resident", "admin"]
    # Their account is theirs: same town, same points.
    assert (user.postal_code, user.points) == ("17450", 120)


async def test_refuses_accounts_whose_meaning_would_change(db_session):
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)
    demo = await ensure_demo_town(db_session)
    db_session.add_all(
        [
            User(
                email="botiga@test.cat",
                slug="botiga",
                postal_code="17400",
                **flags_from_roles(["resident", "merchant"]),
            ),
            User(email="veina-malgrat@test.cat", slug="vm", postal_code="08380"),
        ]
    )
    await register_admin(db_session, town=mal, email="admin@malgrat.test")
    await db_session.commit()

    for email, reason in (
        ("botiga@test.cat", "merchant"),
        ("veina-malgrat@test.cat", "resident of another town"),
        ("admin@malgrat.test", "another municipality"),
        ("no-es-un-correu", "not an email"),
    ):
        with pytest.raises(AdminRefused, match=reason):
            await register_admin(db_session, town=baix, email=email)
    with pytest.raises(AdminRefused, match="demo or test"):
        await register_admin(db_session, town=demo, email=EMAIL)

    # Nothing moved.
    assert (await _user(db_session, "botiga@test.cat")).roles == ["resident", "merchant"]
    assert (await _user(db_session, "veina-malgrat@test.cat")).postal_code == "08380"
    assert (await _user(db_session, "admin@malgrat.test")).postal_code == "08380"
    assert await _user(db_session, EMAIL) is None
