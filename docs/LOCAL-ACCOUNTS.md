# Cuentas locales (Malgrat vs Demo)

OTP fijo **123456** solo en `ENVIRONMENT=development` o `staging`. En production está desactivado.

## Demo KM0 (pueblo ficticio)

CP `00000`. Catálogo y usuarios `is_fake=true`. **No** ves vecinos reales de Malgrat.

| Email | Rol | OTP |
|-------|-----|-----|
| `resident@km0lab.com` | vecino | `123456` |
| `merchant@km0lab.com` | comercio | `123456` |
| `admin@km0lab.com` | admin Demo | `123456` |

```bash
python -m scripts.seed_demo
```

## Malgrat real (QA local)

CP `08380`. `is_fake=false`. En el backoffice ves **usuarios reales de Malgrat** (Gmail, Jobmail, altas de invitaciones).

| Email | Rol | OTP |
|-------|-----|-----|
| `admin-malgrat@km0lab.com` | admin Malgrat | `123456` |
| `merchant1-malgrat@km0lab.com` | comercio 1 | `123456` |
| `merchant2-malgrat@km0lab.com` | comercio 2 | `123456` |

Vecinos de prueba: tu Gmail y Jobmails. **OTP real** (correo), no 123456.

```bash
python -m scripts.seed              # pueblos + cuentas QA Malgrat
python -m scripts.seed_malgrat_qa   # solo re-asegura admin/merchants Malgrat
```

Docker local:

```bash
docker compose exec api python -m scripts.seed
```

Backoffice local (`http://localhost:8080`): botones **Admin Malgrat** / **Comerç 1–2 Malgrat**. No uses «Admin (demo)» si quieres Malgrat.

App: invita con un vecino (Gmail) → **Copiar enlace** (en local ya sale `http://localhost:5173/i/{código}`) → incógnito abre esa URL → Jobmail + OTP del correo + CP 08380.

## Qué no mezclar

- `admin@km0lab.com` ≠ `admin-malgrat@km0lab.com`
- Un enlace `/i/code` de UAT no convierte en la BD local
