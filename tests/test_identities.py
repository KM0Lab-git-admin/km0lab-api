"""How each person gets in, and where each account came from
(``app/services/identities.py``)."""

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models import User, UserIdentity
from app.qa import QA_POSTAL_CODE
from app.roles import flags_from_roles
from app.services.identities import (
    PROVIDER_EMAIL,
    PROVIDER_GOOGLE,
    IdentityTaken,
    ensure_identity,
    is_hidden_email,
    signups_by_provider,
)
from app.services.qa_purge import purge_qa_territory
from app.services.qa_territory import ensure_qa_territory
from tests._municipalities import API, admin_headers, baix_montseny, malgrat

pytestmark = pytest.mark.asyncio


async def _enter(client, capture_otp, email: str, postal_code: str | None = "08380"):
    body = {"email": email}
    if postal_code:
        body["postal_code"] = postal_code
    r = await client.post(f"{API}/auth/request-otp", json=body)
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/auth/verify-otp", json={**body, "code": capture_otp()})
    assert r.status_code == 200, r.text
    return r.json()


async def _doors(db, email: str) -> list[UserIdentity]:
    rows = (
        await db.execute(
            select(UserIdentity)
            .join(User, User.id == UserIdentity.user_id)
            .where(User.email == email)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    return list(rows)


async def test_an_account_born_by_email_says_so(client, capture_otp, db_session):
    await malgrat(db_session)
    await db_session.commit()

    await _enter(client, capture_otp, "Marta@Test.cat")
    (door,) = await _doors(db_session, "marta@test.cat")
    assert (door.provider, door.subject, door.is_first) == (
        PROVIDER_EMAIL,
        "marta@test.cat",
        True,
    )
    first_use = door.last_used_at
    assert first_use is not None

    # Coming back is the same door: one row, used again.
    await _enter(client, capture_otp, "marta@test.cat")
    (door,) = await _doors(db_session, "marta@test.cat")
    assert door.is_first and door.last_used_at >= first_use


async def test_an_account_made_by_a_script_gets_its_door_at_first_login(
    client, capture_otp, db_session
):
    await malgrat(db_session)
    db_session.add(
        User(
            email="antic@test.cat",
            slug="antic",
            postal_code="08380",
            points=0,
            **flags_from_roles(["resident"]),
        )
    )
    await db_session.commit()
    assert await _doors(db_session, "antic@test.cat") == []

    await _enter(client, capture_otp, "antic@test.cat")
    (door,) = await _doors(db_session, "antic@test.cat")
    assert door.provider == PROVIDER_EMAIL and door.is_first


async def test_the_origin_never_changes_and_a_door_is_never_moved(db_session):
    await malgrat(db_session)
    marta = User(email="marta@test.cat", slug="marta", points=0)
    pere = User(email="pere@test.cat", slug="pere", points=0)
    db_session.add_all([marta, pere])
    await db_session.flush()

    born = await ensure_identity(
        db_session, marta, provider=PROVIDER_GOOGLE, subject="g-1", email="marta@test.cat"
    )
    later = await ensure_identity(
        db_session, marta, provider=PROVIDER_EMAIL, subject="MARTA@test.cat"
    )
    assert born.is_first is True and later.is_first is False
    assert later.subject == "marta@test.cat"
    # Google's id is kept as it is; an email is compared in lower case.
    assert born.subject == "g-1"

    with pytest.raises(IdentityTaken):
        await ensure_identity(db_session, pere, provider=PROVIDER_GOOGLE, subject="g-1")
    assert len(await _doors(db_session, "pere@test.cat")) == 0


async def test_fixed_code_accounts_count_as_email_too(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "staging")
    await ensure_qa_territory(db_session)
    await db_session.commit()

    r = await client.post(
        f"{API}/auth/verify-otp", json={"email": "qa+porta@km0lab.com", "code": "123456"}
    )
    assert r.status_code == 200, r.text
    (door,) = await _doors(db_session, "qa+porta@km0lab.com")
    assert door.provider == PROVIDER_EMAIL and door.is_first

    # Erasing the test territory takes the doors with the accounts.
    await purge_qa_territory(db_session, dry_run=False)
    await db_session.commit()
    assert await _doors(db_session, "qa+porta@km0lab.com") == []
    orphans = await db_session.scalar(
        select(func.count())
        .select_from(UserIdentity)
        .where(UserIdentity.user_id.notin_(select(User.id)))
    )
    assert orphans == 0


# ── What the administrator sees ───────────────────────────────────────


async def test_the_card_says_how_the_resident_came_in(client, capture_otp, db_session):
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)
    mal_admin = await admin_headers(db_session, mal, "08380")
    baix_admin = await admin_headers(db_session, baix, "17400")

    marta = (await _enter(client, capture_otp, "marta@test.cat"))["user"]
    user = await db_session.get(User, marta["id"])
    await ensure_identity(
        db_session, user, provider=PROVIDER_GOOGLE, subject="g-marta", email="marta@test.cat"
    )
    await db_session.commit()

    card = (await client.get(f"{API}/residents/{marta['id']}", headers=mal_admin)).json()
    assert card["signup_provider"] == "email_code"
    assert card["signup_at"] is not None
    assert card["email_hidden"] is False
    assert [d["provider"] for d in card["identities"]] == ["email_code", "google"]
    # The provider's id of the person is nobody's business.
    assert all(set(d) == {"provider", "linked_at", "last_used_at"} for d in card["identities"])

    rows = (await client.get(f"{API}/residents", headers=mal_admin)).json()
    listed = next(r for r in rows if r["id"] == marta["id"])
    assert listed["signup_provider"] == "email_code" and listed["identities"] == []
    # The administrator in the list was made by hand and never logged in.
    assert next(r for r in rows if r["id"] != marta["id"])["signup_provider"] is None

    # Another municipality's administrator sees none of it.
    r = await client.get(f"{API}/residents/{marta['id']}", headers=baix_admin)
    assert r.status_code == 404


async def test_how_residents_come_in_by_municipality(client, capture_otp, db_session):
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)
    mal_admin = await admin_headers(db_session, mal, "08380")
    baix_admin = await admin_headers(db_session, baix, "17400")

    await _enter(client, capture_otp, "marta@test.cat")
    await _enter(client, capture_otp, "pere@test.cat")
    await _enter(client, capture_otp, "nuria@test.cat", "17404")
    # Born by Google in Malgrat, and later also gets in by email: one account.
    anna = User(
        email="anna@test.cat",
        slug="anna",
        postal_code="08380",
        points=0,
        **flags_from_roles(["resident"]),
    )
    db_session.add(anna)
    await db_session.flush()
    await ensure_identity(db_session, anna, provider=PROVIDER_GOOGLE, subject="g-anna")
    await ensure_identity(db_session, anna, provider=PROVIDER_EMAIL, subject="anna@test.cat")
    await db_session.commit()

    stats = (await client.get(f"{API}/stats/admin", headers=mal_admin)).json()
    assert stats["signups_by_provider"] == {
        "email_code": 2,
        "google": 1,
        "facebook": 0,
        "apple": 0,
    }
    stats = (await client.get(f"{API}/stats/admin", headers=baix_admin)).json()
    assert stats["signups_by_provider"]["email_code"] == 1
    assert stats["signups_by_provider"]["google"] == 0

    # Every municipality together: what the report script prints.
    everyone = await signups_by_provider(db_session, town_id=None, is_fake=False)
    assert (everyone["email_code"], everyone["google"]) == (3, 1)
    assert await signups_by_provider(db_session, town_id=None, is_fake=True) == {
        "email_code": 0,
        "google": 0,
        "facebook": 0,
        "apple": 0,
    }


async def test_a_hidden_apple_email_is_told_apart():
    assert is_hidden_email("abc123@privaterelay.appleid.com")
    assert is_hidden_email(" ABC@PrivateRelay.AppleID.com ")
    assert not is_hidden_email("marta@icloud.com")
    assert not is_hidden_email(None)
