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

## Baix Montseny (municipio real, piloto en modo demostración)

| Email | Rol | OTP |
| ----- | --- | --- |
| `baixmontseny@km0lab.com` | admin Baix Montseny | `123456` |

La cuenta no se crea al entrar: se da de alta con
`python -m scripts.add_admin --town "Baix Montseny" --email baixmontseny@km0lab.com`
(sin `--apply` solo enseña). El código fijo vale únicamente para ese correo
y únicamente fuera de producción.

**Temporal.** El repositorio es público: cualquiera que lea esto puede
entrar en UAT como administrador de Baix Montseny. Mientras no haya vecinos
ni comercios no hay nada que estropear; antes de que los haya, quita el
correo de `PILOT_ADMIN_EMAILS` (`app/demo.py`) y la cuenta pasará a entrar
con el código que le llegue por correo.

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

## Territorio de pruebas (QA)

CP `99999`. `is_fake=true`. Para las pruebas automáticas; se puede borrar
entero. Detalle en [`QA-TERRITORY.md`](QA-TERRITORY.md).

| Email | Rol | OTP |
|-------|-----|-----|
| `qa+vecino@km0lab.com` | vecino (1000 puntos) | `123456` |
| `qa+comerc@km0lab.com` | comercio QA | `123456` |
| `qa+admin@km0lab.com` | admin QA | `123456` |
| `qa+loquesea@km0lab.com` | vecino **nuevo** (se crea al entrar) | `123456` |

```bash
python -m scripts.seed_qa             # crea o repara el territorio
python -m scripts.purge_qa            # enseña lo que borraría
python -m scripts.purge_qa --apply    # borra lo que crearon las pruebas
```

## Qué no mezclar

- `admin@km0lab.com` ≠ `admin-malgrat@km0lab.com`
- Un enlace `/i/code` de UAT no convierte en la BD local
