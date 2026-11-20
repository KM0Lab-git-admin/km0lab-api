"""The reward catalog is shared; a municipality only switches rewards on/off."""

import pytest
from sqlalchemy import select

from app.catalog.rewards import (
    DEMO_NAME_PREFIX,
    FAKE_DEMO_REWARDS,
    sync_catalog_rewards,
)
from app.models import Redemption, Reward, User
from tests._municipalities import (
    API,
    admin_headers,
    baix_montseny,
    catalog,
    malgrat,
    rewards_of,
)

pytestmark = pytest.mark.asyncio

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
LOCKED = "reward_catalog_locked"
NEW_REWARD = {"name": "Val propi", "type": "discount", "points_required": 10}


async def _public_names(client, postal_code: str) -> list[str]:
    r = await client.get(f"{API}/rewards/public", params={"postal_code": postal_code})
    assert r.status_code == 200, r.text
    return sorted(x["name"] for x in r.json())


async def _demo_reward(db, name: str) -> Reward:
    return (
        await db.execute(
            select(Reward).where(
                Reward.is_fake.is_(True), Reward.name == DEMO_NAME_PREFIX + name
            )
        )
    ).scalars().one()


# ── What the municipality's admin may do ──────────────────────────────


async def test_admin_can_only_switch_a_reward_on_and_off(client, db_session):
    await catalog(db_session)
    town = await malgrat(db_session)
    await sync_catalog_rewards(db_session, town_id=town.id)
    headers = await admin_headers(db_session, town, "08380")
    cap = (await rewards_of(db_session, town))["Gorra KM0 LAB"]
    url = f"{API}/rewards/{cap.id}"

    listed = await client.get(f"{API}/rewards", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == len(FAKE_DEMO_REWARDS)
    assert all(r["content_locked"] for r in listed.json())

    # Nothing but the switch.
    refused = [
        await client.post(f"{API}/rewards", json=NEW_REWARD, headers=headers),
        await client.patch(url, json={"points_required": 1}, headers=headers),
        await client.patch(url, json={"name": "Gorra meva"}, headers=headers),
        await client.patch(url, json={"stock": 999}, headers=headers),
        await client.patch(
            url, json={"status": "inactive", "points_required": 1}, headers=headers
        ),
        await client.patch(url, json={"status": "sold_out"}, headers=headers),
        await client.put(
            f"{url}/media", files={"file": ("x.png", PNG, "image/png")}, headers=headers
        ),
        await client.delete(f"{url}/media", headers=headers),
        await client.delete(url, headers=headers),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)
    assert {r.json()["detail"] for r in refused} == {LOCKED}

    fresh = (await rewards_of(db_session, town))["Gorra KM0 LAB"]
    assert (fresh.points_required, fresh.name, fresh.status) == (
        cap.points_required,
        "Gorra KM0 LAB",
        "active",
    )
    assert len(await rewards_of(db_session, town)) == len(FAKE_DEMO_REWARDS)

    # The switch works, and residents see it.
    off = await client.patch(url, json={"status": "inactive"}, headers=headers)
    assert off.status_code == 200 and off.json()["status"] == "inactive"
    assert "Gorra KM0 LAB" not in await _public_names(client, "08380")

    on = await client.patch(url, json={"status": "active"}, headers=headers)
    assert on.status_code == 200 and on.json()["status"] == "active"
    assert "Gorra KM0 LAB" in await _public_names(client, "08380")


async def test_admin_cannot_touch_another_municipality(client, db_session):
    await catalog(db_session)
    mal = await malgrat(db_session)
    baix = await baix_montseny(db_session)
    await sync_catalog_rewards(db_session, town_id=mal.id)
    await sync_catalog_rewards(db_session, town_id=baix.id)
    mal_admin = await admin_headers(db_session, mal, "08380")
    baix_admin = await admin_headers(db_session, baix, "17400")
    mal_cap = (await rewards_of(db_session, mal))["Gorra KM0 LAB"]
    baix_cap = (await rewards_of(db_session, baix))["Gorra KM0 LAB"]
    assert mal_cap.id != baix_cap.id

    # Each one lists only its own copies.
    mine = await client.get(f"{API}/rewards", headers=baix_admin)
    assert {r["town_id"] for r in mine.json()} == {baix.id}
    theirs = await client.get(f"{API}/rewards", headers=mal_admin)
    assert {r["town_id"] for r in theirs.json()} == {mal.id}

    # Baix Montseny cannot switch Malgrat's rewards, nor the other way round.
    r = await client.patch(
        f"{API}/rewards/{mal_cap.id}", json={"status": "inactive"}, headers=baix_admin
    )
    assert r.status_code == 404
    r = await client.patch(
        f"{API}/rewards/{baix_cap.id}", json={"status": "inactive"}, headers=mal_admin
    )
    assert r.status_code == 404
    rewards = await rewards_of(db_session, mal)
    assert rewards["Gorra KM0 LAB"].status == "active"
    assert (await rewards_of(db_session, baix))["Gorra KM0 LAB"].status == "active"

    # Switching one off in Baix Montseny hides it in its three towns only.
    r = await client.patch(
        f"{API}/rewards/{baix_cap.id}", json={"status": "inactive"}, headers=baix_admin
    )
    assert r.status_code == 200
    for code in ("17400", "17450", "17404"):
        assert "Gorra KM0 LAB" not in await _public_names(client, code)
    assert "Gorra KM0 LAB" in await _public_names(client, "08380")


async def test_catalog_editor_keeps_full_control(client, db_session):
    """Demo KM0 is where the catalog is edited: nothing is locked there."""
    demo = await catalog(db_session)
    headers = await admin_headers(db_session, demo, "00000", is_fake=True)

    created = await client.post(f"{API}/rewards", json=NEW_REWARD, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["content_locked"] is False
    url = f"{API}/rewards/{created.json()['id']}"

    edited = await client.patch(url, json={"points_required": 25}, headers=headers)
    assert edited.status_code == 200 and edited.json()["points_required"] == 25
    assert (await client.delete(url, headers=headers)).status_code == 204


# ── Copying the catalog ───────────────────────────────────────────────


async def test_new_municipality_gets_the_catalog_switched_on(client, db_session):
    await catalog(db_session)
    baix = await baix_montseny(db_session)

    report = await sync_catalog_rewards(db_session, town_id=baix.id)
    await db_session.commit()

    assert len(report.created) == len(FAKE_DEMO_REWARDS)
    assert report.updated == report.deleted == report.untouched == []
    rewards = await rewards_of(db_session, baix)
    assert {r.status for r in rewards.values()} == {"active"}
    assert all(r.catalog_id for r in rewards.values())
    # The three towns of the municipality offer the same catalog.
    for code in ("17400", "17450", "17404"):
        assert len(await _public_names(client, code)) == len(FAKE_DEMO_REWARDS)

    # Running it again changes nothing.
    again = await sync_catalog_rewards(db_session, town_id=baix.id)
    assert again.created == [] and len(again.updated) == len(FAKE_DEMO_REWARDS)


async def test_update_keeps_status_stock_and_what_was_redeemed(client, db_session):
    demo = await catalog(db_session)
    town = await malgrat(db_session)
    await sync_catalog_rewards(db_session, town_id=town.id)
    await db_session.commit()
    before = await rewards_of(db_session, town)

    # The municipality's own decisions and history.
    before["Gorra KM0 LAB"].status = "inactive"  # the admin switched it off
    before["Samarreta KM0 LAB"].stock = 3  # residents redeemed some
    resident = User(email="veina@test.cat", slug="veina", postal_code="08380")
    db_session.add(resident)
    await db_session.flush()
    db_session.add(
        Redemption(
            town_id=town.id,
            user_id=resident.id,
            reward_id=before["Entrada de cinema"].id,
            flow="voucher_qr",
            points_spent=200,
            status="pending",
        )
    )
    ids = {name: r.id for name, r in before.items()}

    # The catalog moves on.
    (await _demo_reward(db_session, "Gorra KM0 LAB")).points_required = 999
    (await _demo_reward(db_session, "Samarreta KM0 LAB")).stock = 500
    renamed = await _demo_reward(db_session, "Bono 10 €")
    renamed.name = DEMO_NAME_PREFIX + "Val de 10 €"
    await db_session.delete(await _demo_reward(db_session, "Entrada de cinema"))
    await db_session.delete(await _demo_reward(db_session, "Bono 20 €"))
    db_session.add(
        Reward(
            town_id=demo.id,
            is_fake=True,
            name=DEMO_NAME_PREFIX + "Ampolla nova",
            type="product",
            points_required=180,
            status="active",
        )
    )
    await db_session.commit()

    report = await sync_catalog_rewards(db_session, town_id=town.id)
    await db_session.commit()
    after = await rewards_of(db_session, town)

    # Content follows the catalog; the switch and the stock do not.
    assert report.changed == ["Gorra KM0 LAB: points 180 -> 999"]
    assert after["Gorra KM0 LAB"].points_required == 999
    assert after["Gorra KM0 LAB"].status == "inactive"
    assert after["Samarreta KM0 LAB"].stock == 3
    assert after["Samarreta KM0 LAB"].status == "active"
    # A renamed catalog reward renames its copy: same row, same status.
    assert report.renamed == [("Bono 10 €", "Val de 10 €")]
    assert after["Val de 10 €"].id == ids["Bono 10 €"]
    assert after["Val de 10 €"].status == "active"
    assert "Bono 10 €" not in after
    # New in the catalog: offered from now on, like everywhere else.
    assert report.created == ["Ampolla nova"]
    assert after["Ampolla nova"].status == "active"
    # Gone from the catalog: kept and off if redeemed, removed otherwise.
    assert report.retired == ["Entrada de cinema"]
    assert after["Entrada de cinema"].status == "inactive"
    assert report.deleted == ["Bono 20 €"]
    assert "Bono 20 €" not in after

    public = await _public_names(client, "08380")
    assert {"Val de 10 €", "Ampolla nova"} <= set(public)
    assert not {"Gorra KM0 LAB", "Entrada de cinema"} & set(public)


async def test_rewards_older_than_the_link_are_adopted_or_left_alone(db_session):
    """Malgrat as it is today: copies matched by name, and three that are not."""
    await catalog(db_session)
    town = await malgrat(db_session)
    cap = Reward(
        town_id=town.id,
        name="Gorra KM0 LAB",
        type="merchandise",
        points_required=1,
        stock=7,
        status="active",
    )
    own = Reward(
        town_id=town.id,
        name="Val per un 5% de descompe",
        type="discount",
        points_required=50,
        status="active",
    )
    db_session.add_all([cap, own])
    await db_session.commit()
    cap_id, own_id = cap.id, own.id

    report = await sync_catalog_rewards(db_session, town_id=town.id)
    await db_session.commit()
    after = await rewards_of(db_session, town)

    # The copy is recognised by name: same row, still on, now linked.
    assert after["Gorra KM0 LAB"].id == cap_id
    assert after["Gorra KM0 LAB"].status == "active"
    assert after["Gorra KM0 LAB"].stock == 7
    assert after["Gorra KM0 LAB"].points_required != 1
    assert after["Gorra KM0 LAB"].catalog_id
    # The one the catalog does not know is not touched, and never deleted.
    assert report.untouched == ["Val per un 5% de descompe"]
    assert after["Val per un 5% de descompe"].id == own_id
    assert after["Val per un 5% de descompe"].status == "active"
    assert after["Val per un 5% de descompe"].catalog_id is None
    assert report.deleted == []
    # The rest of the catalog arrives, on.
    assert len(report.created) == len(FAKE_DEMO_REWARDS) - 1
