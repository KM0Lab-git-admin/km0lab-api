"""QA territory: erasable test data living inside the shared database.

The pilot runs on UAT with a single database, so automated tests need a
place where they can write without touching real residents or the sales
demo (Demo KM0, CP 00000). That place is the QA territory:

- Postal codes ``99990``–``99999`` (no real Spanish postal code uses them).
- Accounts ``qa+<anything>@km0lab.com`` (fixed OTP, dev/staging only).
- Everything on the ``is_fake`` partition, visible names prefixed ``[QA]``.

``scripts/seed_qa.py`` builds the fixture and ``scripts/purge_qa.py``
removes whatever tests created. Nothing here is reachable in production.
"""

from __future__ import annotations

import re

QA_POSTAL_PREFIX = "9999"
QA_POSTAL_CODE = "99999"
QA_TOWN_NAME = "[QA] QA KM0"
QA_TOWN_SLUG = "qa-km0"
QA_SLUG_PREFIX = "qa-"
QA_NAME_PREFIX = "[QA] "

QA_EMAIL_DOMAIN = "km0lab.com"
QA_EMAIL_LIKE = "qa+%@km0lab.com"
_QA_EMAIL_RE = re.compile(r"^qa\+[a-z0-9][a-z0-9._-]{0,59}@km0lab\.com$")

# Fixture accounts (seeded). Tests only read with them; journeys that write
# create their own ``qa+<run>-…`` accounts so runs never depend on each other.
QA_RESIDENT_EMAIL = "qa+vecino@km0lab.com"
QA_MERCHANT_EMAIL = "qa+comerc@km0lab.com"
QA_ADMIN_EMAIL = "qa+admin@km0lab.com"

QA_FIXTURE_EMAILS: frozenset[str] = frozenset(
    {QA_RESIDENT_EMAIL, QA_MERCHANT_EMAIL, QA_ADMIN_EMAIL}
)


def is_qa_email(email: str | None) -> bool:
    return bool(_QA_EMAIL_RE.match((email or "").lower().strip()))


def is_qa_postal_code(postal_code: str | None) -> bool:
    cp = (postal_code or "").strip()
    return len(cp) == 5 and cp.isdigit() and cp.startswith(QA_POSTAL_PREFIX)
