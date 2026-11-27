"""Generate Postman collection + environments for KM0 LAB API."""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent


def hdr_json() -> list[dict]:
    return [{"key": "Content-Type", "value": "application/json"}]


def hdr_auth() -> list[dict]:
    return [{"key": "Authorization", "value": "Bearer {{access_token}}"}]


def hdr_acting() -> list[dict]:
    return [
        *hdr_auth(),
        {
            "key": "X-Acting-Shop-Id",
            "value": "{{shop_id}}",
            "description": "Admin acting as shop (BO comercio)",
        },
        {
            "key": "X-Active-Role",
            "value": "{{active_role}}",
            "disabled": True,
            "description": "Optional: resident|merchant|admin",
        },
    ]


def q(params: list[tuple[str, str, bool]]) -> list[dict]:
    """(key, value, enabled)"""
    return [
        {"key": k, "value": v, "disabled": not enabled}
        for k, v, enabled in params
    ]


def url(path: str, query: list[dict] | None = None) -> dict:
    raw = f"{{{{baseUrl}}}}/api/v1{path}"
    segments = [s for s in path.strip("/").split("/") if s]
    host = ["{{baseUrl}}"]
    # Postman expects host without protocol in structured form; use raw primarily.
    return {
        "raw": raw if not query else raw
        + ("?" + "&".join(f"{i['key']}={i['value']}" for i in query if not i.get("disabled"))),
        "host": ["{{baseUrl}}"],
        "path": ["api", "v1", *segments],
        **({"query": query} if query else {}),
    }


def req(
    name: str,
    method: str,
    path: str,
    *,
    auth: bool = False,
    acting: bool = False,
    query: list[tuple[str, str, bool]] | None = None,
    body: dict | list | None = None,
    body_raw: str | None = None,
    multipart: bool = False,
    description: str = "",
    event: list | None = None,
) -> dict:
    headers: list[dict] = []
    if acting:
        headers.extend(hdr_acting())
    elif auth:
        headers.extend(hdr_auth())
    query_list = q(query) if query else None
    item: dict = {
        "name": name,
        "request": {
            "method": method,
            "header": headers,
            "url": url(path, query_list),
            "description": description,
        },
    }
    # Avoid inheriting collection Bearer on public / OTP endpoints.
    if not auth and not acting:
        item["request"]["auth"] = {"type": "noauth"}
    if event:
        item["event"] = event
    if multipart:
        item["request"]["body"] = {
            "mode": "formdata",
            "formdata": [
                {
                    "key": "file",
                    "type": "file",
                    "src": "",
                    "description": "Image file (png/jpg/webp)",
                }
            ],
        }
    elif body is not None or body_raw is not None:
        item["request"]["header"] = [*headers, *hdr_json()]
        item["request"]["body"] = {
            "mode": "raw",
            "raw": body_raw
            if body_raw is not None
            else json.dumps(body, ensure_ascii=False, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    return item


def folder(name: str, items: list[dict], description: str = "") -> dict:
    return {"name": name, "description": description, "item": items}


VERIFY_OTP_TESTS = [
    {
        "listen": "test",
        "script": {
            "type": "text/javascript",
            "exec": [
                "if (pm.response.code === 200) {",
                "  const j = pm.response.json();",
                "  if (j.access_token) pm.environment.set('access_token', j.access_token);",
                "  if (j.user) {",
                "    if (j.user.id) pm.environment.set('user_id', j.user.id);",
                "    if (j.user.town_id) pm.environment.set('town_id', j.user.town_id);",
                "    if (j.user.shop_id) pm.environment.set('shop_id', j.user.shop_id);",
                "    if (j.user.email) pm.environment.set('email', j.user.email);",
                "  }",
                "}",
            ],
        },
    }
]

collection = {
    "info": {
        "name": "KM0 LAB API",
        "description": (
            "API KM0 LAB (`/api/v1`).\n\n"
            "**Auth:** `POST /auth/request-otp` → `POST /auth/verify-otp` "
            "(guarda `access_token` en el entorno).\n\n"
            "**Demo UAT:** `resident@` / `merchant@` / `admin@km0lab.com` "
            "con código `123456`.\n\n"
            "**Admin en panel comercio:** header `X-Acting-Shop-Id` = `{{shop_id}}`."
        ),
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "auth": {
        "type": "bearer",
        "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}],
    },
    "variable": [
        {"key": "baseUrl", "value": "https://api.uat.km0lab.com"},
    ],
    "item": [
        folder(
            "00 · Health",
            [
                req("Health", "GET", "/health", description="Liveness check"),
            ],
        ),
        folder(
            "01 · Auth",
            [
                req(
                    "Request OTP",
                    "POST",
                    "/auth/request-otp",
                    body={"email": "{{email}}", "lang": "{{lang}}"},
                    description="Envía OTP. Demo emails no envían correo.",
                ),
                req(
                    "Verify OTP",
                    "POST",
                    "/auth/verify-otp",
                    body={"email": "{{email}}", "code": "{{otp_code}}"},
                    description="Devuelve JWT. Test script guarda token e IDs.",
                    event=VERIFY_OTP_TESTS,
                ),
            ],
            "Login OTP. Demo: code 123456.",
        ),
        folder(
            "02 · Users",
            [
                req("Get me", "GET", "/users/me", auth=True),
                req(
                    "Patch me",
                    "PATCH",
                    "/users/me",
                    auth=True,
                    body={
                        "first_name": "Anna",
                        "last_name": "García",
                        "lang": "ca",
                        "postal_code": "{{postal_code}}",
                        "phone": "+34600111222",
                        "birth_date": "1990-05-15",
                        "contact_shared": True,
                    },
                ),
            ],
        ),
        folder(
            "03 · Towns",
            [
                req(
                    "Public by postal code",
                    "GET",
                    "/towns/public",
                    query=[("postal_code", "{{postal_code}}", True)],
                ),
                req("My town (admin)", "GET", "/towns/me", auth=True),
                req("Get town", "GET", "/towns/{{town_id}}", auth=True),
                req(
                    "Patch town",
                    "PATCH",
                    "/towns/{{town_id}}",
                    auth=True,
                    body={
                        "entity_name": "Ajuntament Demo",
                        "points_per_euro": 200,
                        "default_visit_points": 10,
                        "default_lang": "ca",
                        "expiry_months": 12,
                    },
                ),
                req(
                    "Upload town media",
                    "PUT",
                    "/towns/{{town_id}}/media/{{media_kind}}",
                    auth=True,
                    multipart=True,
                    description="kind: logo (etc.)",
                ),
                req(
                    "Delete town media",
                    "DELETE",
                    "/towns/{{town_id}}/media/{{media_kind}}",
                    auth=True,
                ),
                req(
                    "Get town media (public)",
                    "GET",
                    "/towns/{{town_id}}/media/{{media_kind}}",
                ),
            ],
        ),
        folder(
            "04 · Shops",
            [
                req(
                    "Public list",
                    "GET",
                    "/shops/public",
                    query=[
                        ("postal_code", "{{postal_code}}", True),
                        ("lang", "{{lang}}", True),
                        ("demo", "true", False),
                    ],
                ),
                req(
                    "For me (resident)",
                    "GET",
                    "/shops/for-me",
                    auth=True,
                    query=[
                        ("postal_code", "{{postal_code}}", False),
                        ("lang", "{{lang}}", True),
                    ],
                ),
                req(
                    "List (admin)",
                    "GET",
                    "/shops",
                    auth=True,
                    query=[
                        ("status", "active", False),
                        ("q", "", False),
                        ("lang", "{{lang}}", True),
                    ],
                ),
                req(
                    "Create shop (admin)",
                    "POST",
                    "/shops",
                    auth=True,
                    body={
                        "name": "Fleca Demo",
                        "emoji": "🥖",
                        "categories": ["bakery"],
                        "contact_email": "merchant@km0lab.com",
                        "visit_points": 10,
                        "address": "Carrer Major 1",
                        "postal_code": "{{postal_code}}",
                        "phone": "+34930111222",
                        "description": "Pa del dia",
                        "i18n_source_lang": "ca",
                    },
                ),
                req(
                    "Get me (merchant/admin)",
                    "GET",
                    "/shops/me",
                    acting=True,
                    query=[("lang", "{{lang}}", True)],
                ),
                req(
                    "Patch me",
                    "PATCH",
                    "/shops/me",
                    acting=True,
                    body={
                        "name": "Fleca Demo",
                        "description": "Pa artesà",
                        "phone": "+34930111222",
                        "i18n_source_lang": "ca",
                    },
                ),
                req(
                    "Upload my media",
                    "PUT",
                    "/shops/me/media/{{media_kind}}",
                    acting=True,
                    multipart=True,
                    description="kind: logo|hero|qr",
                ),
                req(
                    "Delete my media",
                    "DELETE",
                    "/shops/me/media/{{media_kind}}",
                    acting=True,
                ),
                req("Get my QR", "GET", "/shops/me/qr", acting=True),
                req("Ensure my QR", "POST", "/shops/me/qr", acting=True),
                req(
                    "Upload shop media (admin)",
                    "PUT",
                    "/shops/{{shop_id}}/media/{{media_kind}}",
                    auth=True,
                    multipart=True,
                ),
                req(
                    "Get shop media (public)",
                    "GET",
                    "/shops/{{shop_id}}/media/{{media_kind}}",
                ),
                req(
                    "Get shop",
                    "GET",
                    "/shops/{{shop_id}}",
                    auth=True,
                    query=[("lang", "{{lang}}", True)],
                ),
                req(
                    "Patch shop (admin)",
                    "PATCH",
                    "/shops/{{shop_id}}",
                    auth=True,
                    body={"status": "active", "visit_points": 15},
                ),
            ],
        ),
        folder(
            "05 · Shop categories",
            [
                req(
                    "List",
                    "GET",
                    "/shop-categories",
                    query=[
                        ("include_inactive", "false", False),
                        ("lang", "{{lang}}", True),
                    ],
                ),
                req(
                    "Patch category (admin)",
                    "PATCH",
                    "/shop-categories/{{category_slug}}",
                    auth=True,
                    body={
                        "label_i18n": {
                            "ca": "Fleca",
                            "es": "Panadería",
                            "en": "Bakery",
                        },
                        "i18n_source_lang": "ca",
                        "sort_order": 10,
                        "active": True,
                        "emoji": "🥖",
                    },
                ),
            ],
        ),
        folder(
            "06 · Promotions",
            [
                req(
                    "Public list",
                    "GET",
                    "/promotions/public",
                    query=[
                        ("postal_code", "{{postal_code}}", True),
                        ("lang", "{{lang}}", True),
                        ("demo", "true", False),
                    ],
                ),
                req(
                    "List (merchant)",
                    "GET",
                    "/promotions",
                    acting=True,
                    query=[("lang", "{{lang}}", True)],
                ),
                req(
                    "Create",
                    "POST",
                    "/promotions",
                    acting=True,
                    body={
                        "type": "discount",
                        "title": "10% en pastes",
                        "label": "10% pastes",
                        "detail": "Vàlid de dilluns a divendres",
                        "value": "10%",
                        "min_purchase": "5",
                        "active": True,
                        "i18n_source_lang": "ca",
                    },
                ),
                req(
                    "Patch",
                    "PATCH",
                    "/promotions/{{promo_id}}",
                    acting=True,
                    body={"active": False, "value": "15%"},
                ),
                req(
                    "Delete",
                    "DELETE",
                    "/promotions/{{promo_id}}",
                    acting=True,
                ),
            ],
        ),
        folder(
            "07 · Actions",
            [
                req(
                    "Public list",
                    "GET",
                    "/actions/public",
                    query=[
                        ("postal_code", "{{postal_code}}", True),
                        ("visible_home", "true", False),
                        ("lang", "{{lang}}", True),
                        ("demo", "true", False),
                    ],
                ),
                req("List (admin)", "GET", "/actions", auth=True),
                req(
                    "Create (admin)",
                    "POST",
                    "/actions",
                    auth=True,
                    body={
                        "type": "custom",
                        "name": "Visita web",
                        "description": "Entra a la web municipal",
                        "points": 50,
                        "per_user_limit": 1,
                        "visible_home": True,
                        "active": True,
                        "url": "https://example.com",
                        "i18n_source_lang": "ca",
                    },
                ),
                req(
                    "Patch (admin)",
                    "PATCH",
                    "/actions/{{action_id}}",
                    auth=True,
                    body={"points": 75, "visible_home": False},
                ),
                req(
                    "Activate",
                    "POST",
                    "/actions/{{action_id}}/activate",
                    auth=True,
                ),
                req(
                    "Deactivate",
                    "POST",
                    "/actions/{{action_id}}/deactivate",
                    auth=True,
                ),
                req(
                    "Delete",
                    "DELETE",
                    "/actions/{{action_id}}",
                    auth=True,
                ),
            ],
        ),
        folder(
            "08 · Points",
            [
                req(
                    "My history",
                    "GET",
                    "/points/me/history",
                    auth=True,
                    query=[
                        ("filter", "all", True),
                        ("limit", "100", True),
                    ],
                    description="filter: all|earned|spent",
                ),
                req("Claim birthday", "POST", "/points/claim-birthday", auth=True),
            ],
        ),
        folder(
            "09 · Rewards",
            [
                req(
                    "Public list",
                    "GET",
                    "/rewards/public",
                    query=[
                        ("postal_code", "{{postal_code}}", True),
                        ("lang", "{{lang}}", True),
                        ("demo", "true", False),
                    ],
                ),
                req(
                    "List",
                    "GET",
                    "/rewards",
                    auth=True,
                    query=[("lang", "{{lang}}", True)],
                ),
                req(
                    "Create (admin)",
                    "POST",
                    "/rewards",
                    auth=True,
                    body={
                        "name": "Val 5€",
                        "description": "Saldo comerç local",
                        "type": "balance",
                        "points_required": 1000,
                        "value": "5",
                        "stock": 50,
                        "status": "active",
                        "shop_ids": [],
                        "i18n_source_lang": "ca",
                    },
                ),
                req(
                    "Get one",
                    "GET",
                    "/rewards/{{reward_id}}",
                    auth=True,
                    query=[("lang", "{{lang}}", True)],
                ),
                req(
                    "Patch (admin)",
                    "PATCH",
                    "/rewards/{{reward_id}}",
                    auth=True,
                    body={"points_required": 900, "stock": 40},
                ),
                req(
                    "Upload media",
                    "PUT",
                    "/rewards/{{reward_id}}/media",
                    auth=True,
                    multipart=True,
                ),
                req(
                    "Delete media",
                    "DELETE",
                    "/rewards/{{reward_id}}/media",
                    auth=True,
                ),
                req(
                    "Get media (public)",
                    "GET",
                    "/rewards/{{reward_id}}/media",
                ),
                req(
                    "Delete reward",
                    "DELETE",
                    "/rewards/{{reward_id}}",
                    auth=True,
                ),
            ],
        ),
        folder(
            "10 · Redemptions",
            [
                req(
                    "Redeem (resident)",
                    "POST",
                    "/redemptions",
                    auth=True,
                    body={
                        "reward_id": "{{reward_id}}",
                        "shop_id": "{{shop_id}}",
                        "amount": "5.00",
                    },
                ),
                req(
                    "List",
                    "GET",
                    "/redemptions",
                    auth=True,
                    query=[
                        ("status", "pending_use", False),
                        ("reward_type", "balance", False),
                        ("shop_id", "{{shop_id}}", False),
                    ],
                ),
                req(
                    "Validate voucher",
                    "POST",
                    "/redemptions/validate",
                    acting=True,
                    body={"code": "{{voucher_code}}", "amount_applied": "5.00"},
                ),
                req(
                    "Patch status (admin)",
                    "PATCH",
                    "/redemptions/{{redemption_id}}/status",
                    auth=True,
                    body={"status": "delivered", "note": "Entregat"},
                ),
                req(
                    "Use by id",
                    "POST",
                    "/redemptions/{{redemption_id}}/use",
                    acting=True,
                    body={"amount_applied": "5.00"},
                ),
            ],
        ),
        folder(
            "11 · Payments",
            [
                req("Debts (admin)", "GET", "/payments/debts", auth=True),
                req(
                    "List (admin)",
                    "GET",
                    "/payments",
                    auth=True,
                    query=[("shop_id", "{{shop_id}}", False)],
                ),
                req(
                    "Create settlement (admin)",
                    "POST",
                    "/payments",
                    auth=True,
                    body={
                        "shop_id": "{{shop_id}}",
                        "redemption_ids": ["{{redemption_id}}"],
                        "note": "Liquidació",
                    },
                ),
            ],
        ),
        folder(
            "12 · Scans",
            [
                req(
                    "Scan QR (resident)",
                    "POST",
                    "/scans",
                    auth=True,
                    body={"qr_code": "{{qr_code}}"},
                ),
            ],
        ),
        folder(
            "13 · Residents",
            [
                req(
                    "List (admin)",
                    "GET",
                    "/residents",
                    auth=True,
                    query=[("q", "", False)],
                ),
                req(
                    "Get one (admin)",
                    "GET",
                    "/residents/{{resident_id}}",
                    auth=True,
                    query=[("include_activity", "true", True)],
                ),
            ],
        ),
        folder(
            "14 · Stats",
            [
                req("Admin stats", "GET", "/stats/admin", auth=True),
                req("Merchant stats", "GET", "/stats/merchant", acting=True),
            ],
        ),
    ],
}


def env(name: str, values: dict[str, str], *, active: set[str] | None = None) -> dict:
    active = active or set(values)
    return {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "values": [
            {
                "key": k,
                "value": v,
                "type": "default",
                "enabled": k in active or True,
            }
            for k, v in values.items()
        ],
        "_postman_variable_scope": "environment",
    }


UAT = {
    "baseUrl": "https://api.uat.km0lab.com",
    "access_token": "",
    "email": "resident@km0lab.com",
    "otp_code": "123456",
    "lang": "es",
    "postal_code": "00000",
    "user_id": "",
    "town_id": "",
    "shop_id": "",
    "reward_id": "",
    "action_id": "",
    "promo_id": "",
    "redemption_id": "",
    "resident_id": "",
    "qr_code": "",
    "voucher_code": "12345",
    "category_slug": "bakery",
    "media_kind": "logo",
    "active_role": "resident",
}

LOCAL = {
    **UAT,
    "baseUrl": "http://localhost:8000",
    "email": "resident@km0lab.com",
}

PROD_LIKE = {
    **UAT,
    "baseUrl": "https://api.uat.km0lab.com",
    "email": "tu@email.com",
    "otp_code": "",
    "postal_code": "08380",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "KM0Lab-API.postman_collection.json").write_text(
        json.dumps(collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "KM0Lab-UAT.postman_environment.json").write_text(
        json.dumps(env("KM0Lab UAT", UAT), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "KM0Lab-Local.postman_environment.json").write_text(
        json.dumps(env("KM0Lab Local", LOCAL), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("Wrote:", OUT / "KM0Lab-API.postman_collection.json")
    print("Wrote:", OUT / "KM0Lab-UAT.postman_environment.json")
    print("Wrote:", OUT / "KM0Lab-Local.postman_environment.json")


if __name__ == "__main__":
    main()
