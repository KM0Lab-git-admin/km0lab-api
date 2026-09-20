# Invitaciones KM0 LAB (API)

Circuito last-click. Un código reutilizable por prescriptor y tipo (`person` | `business`).

## Tablas

- `invitation_links` — `public_code` único, unique `(inviter_user_id, kind)`
- `invitation_events` — hitos (`share_initiated`, `link_resolved`, `registration_started`, `install_referrer_recovered`). No son entrega.
- `invitation_conversions` — alta atribuida; unique `(kind, invitee_user_id)` y `shop_id`
- `otp_codes.invite_code` — last-click en el OTP
- `shops.tax_id` — persistido, no se usa como duplicado de establecimiento

## Endpoints

| Método | Ruta | Auth |
|--------|------|------|
| GET | `/api/v1/invites/me/link?kind=` | JWT |
| GET | `/api/v1/invites/me/summary` | JWT |
| GET | `/api/v1/invites/me/conversions` | JWT |
| POST | `/api/v1/invites/resolve` | público |
| POST | `/api/v1/invites/events` | opcional |
| POST | `/api/v1/auth/request-otp` | `invite_code`, `postal_code` opcionales |
| POST | `/api/v1/auth/verify-otp` | `invite_code`, `postal_code` opcionales |
| POST | `/api/v1/shops/public-signup` | JWT opcional |
| GET | `/api/v1/admin/invites` | admin pueblo |
| POST | `/api/v1/admin/invites/conversions/{id}/retry-reward` | admin pueblo |

## Reglas

- Conversión solo si el alta es **en el mismo pueblo** que el enlace.
- Cuenta existente: login OK, **sin** conversión.
- Auto-referido: ignorado.
- 1 usuario = 1 comercio: un merchant no puede usar otra invitación de negocio.
- Preview bots (WhatsApp/Facebook) no registran evento de conversión (no hay conversión en resolve).
- Importes: acciones `invite_person` / `invite_business` (100/500) o env `INVITE_PERSON_POINTS` / `INVITE_BUSINESS_POINTS`. Snapshot en la conversión.

Cuentas para probar el circuito en local: [`LOCAL-ACCOUNTS.md`](LOCAL-ACCOUNTS.md).

## Migración

```bash
alembic upgrade head
```

Revisión `0025_invitations`.
