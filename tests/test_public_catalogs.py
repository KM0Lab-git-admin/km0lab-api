"""Public catalogs by postal code (rewards / shops / promotions)."""

import pytest

from app.models import Promotion, Reward, Shop, Town, TownPostalCode
from app.utils.slug import slugify


async def _seed_town_catalog(db_session, *, postal_code="08400", name="PubTown"):
    town = Town(
        name=name,
        slug=slugify(name),
        entity_name=f"Ajuntament de {name}",
        entity_type="city_council",
        contact_email=f"admin@{slugify(name)}.cat",
        manager_name="Admin",
        default_lang="ca",
    )
    db_session.add(town)
    await db_session.flush()
    db_session.add(
        TownPostalCode(postal_code=postal_code, town_id=town.id, is_primary=True)
    )

    shop_ok = Shop(
        town_id=town.id,
        name="Fleca Activa",
        contact_email="fleca@test.cat",
        status="active",
        description="Descripcio CA",
        description_i18n={
            "ca": "Descripcio CA",
            "es": "Descripcion ES",
            "en": "Description EN",
        },
        is_fake=False,
    )
    shop_pending = Shop(
        town_id=town.id,
        name="Pendent",
        contact_email="p@test.cat",
        status="pending",
        is_fake=False,
    )
    shop_demo = Shop(
        town_id=town.id,
        name="Demo Shop",
        contact_email="d@test.cat",
        status="active",
        is_fake=True,
    )
    db_session.add_all([shop_ok, shop_pending, shop_demo])
    await db_session.flush()

    db_session.add_all(
        [
            Reward(
                town_id=town.id,
                name="Premi CA",
                description="Desc CA",
                name_i18n={"ca": "Premi CA", "es": "Premio ES", "en": "Reward EN"},
                description_i18n={
                    "ca": "Desc CA",
                    "es": "Desc ES",
                    "en": "Desc EN",
                },
                type="product",
                points_required=100,
                status="active",
                is_fake=False,
            ),
            Reward(
                town_id=town.id,
                name="Inactiva",
                description="x",
                type="product",
                points_required=50,
                status="inactive",
                is_fake=False,
            ),
            Reward(
                town_id=town.id,
                name="Demo Reward",
                description="demo",
                type="product",
                points_required=10,
                status="active",
                is_fake=True,
            ),
            Promotion(
                shop_id=shop_ok.id,
                type="discount",
                label="10%",
                title="Descompte CA",
                detail="Detail CA",
                title_i18n={
                    "ca": "Descompte CA",
                    "es": "Descuento ES",
                    "en": "Discount EN",
                },
                detail_i18n={
                    "ca": "Detail CA",
                    "es": "Detalle ES",
                    "en": "Detail EN",
                },
                active=True,
                is_fake=False,
            ),
            Promotion(
                shop_id=shop_ok.id,
                type="gift",
                label="off",
                title="Inactiva",
                detail="x",
                active=False,
                is_fake=False,
            ),
            Promotion(
                shop_id=shop_demo.id,
                type="discount",
                label="demo",
                title="Demo Promo",
                detail="x",
                active=True,
                is_fake=True,
            ),
        ]
    )
    await db_session.commit()
    return town


@pytest.mark.asyncio
async def test_public_rewards_by_postal_and_lang(client, db_session):
    await _seed_town_catalog(db_session, postal_code="08401")

    unknown = await client.get(
        "/api/v1/rewards/public",
        params={"postal_code": "99999"},
    )
    assert unknown.status_code == 404

    ca = await client.get(
        "/api/v1/rewards/public",
        params={"postal_code": "08401", "lang": "ca"},
    )
    assert ca.status_code == 200, ca.text
    names = [r["name"] for r in ca.json()]
    assert names == ["Premi CA"]

    es = await client.get(
        "/api/v1/rewards/public",
        params={"postal_code": "08401", "lang": "es"},
    )
    assert es.json()[0]["name"] == "Premio ES"
    assert es.json()[0]["description"] == "Desc ES"

    demo = await client.get(
        "/api/v1/rewards/public",
        params={"postal_code": "08401", "demo": True},
    )
    assert [r["name"] for r in demo.json()] == ["Demo Reward"]


@pytest.mark.asyncio
async def test_public_rewards_demo_cp_and_malgrat_guard(client, db_session):
    await _seed_town_catalog(db_session, postal_code="00000", name="Demo KM0")
    demo_cp = await client.get(
        "/api/v1/rewards/public",
        params={"postal_code": "00000"},
    )
    assert demo_cp.status_code == 200
    assert [r["name"] for r in demo_cp.json()] == ["Demo Reward"]

    await _seed_town_catalog(db_session, postal_code="08380", name="Malgrat de Mar")
    malgrat = await client.get(
        "/api/v1/rewards/public",
        params={"postal_code": "08380", "demo": True},
    )
    assert [r["name"] for r in malgrat.json()] == ["Premi CA"]


@pytest.mark.asyncio
async def test_public_shops_by_postal_and_lang(client, db_session):
    await _seed_town_catalog(db_session, postal_code="08402", name="ShopTown")

    res = await client.get(
        "/api/v1/shops/public",
        params={"postal_code": "08402", "lang": "es"},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Fleca Activa"
    assert rows[0]["description"] == "Descripcion ES"

    demo = await client.get(
        "/api/v1/shops/public",
        params={"postal_code": "08402", "demo": True},
    )
    assert [s["name"] for s in demo.json()] == ["Demo Shop"]


@pytest.mark.asyncio
async def test_public_promotions_by_postal_and_lang(client, db_session):
    await _seed_town_catalog(db_session, postal_code="08403", name="PromoTown")

    res = await client.get(
        "/api/v1/promotions/public",
        params={"postal_code": "08403", "lang": "en"},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["title"] == "Discount EN"
    assert rows[0]["detail"] == "Detail EN"

    demo = await client.get(
        "/api/v1/promotions/public",
        params={"postal_code": "08403", "demo": True},
    )
    assert [p["title"] for p in demo.json()] == ["Demo Promo"]
