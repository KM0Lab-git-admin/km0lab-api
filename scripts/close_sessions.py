"""Close every session of one account (a lost or stolen phone).

Usage (from repo root):

    python -m scripts.close_sessions --email marta@example.com
    python -m scripts.close_sessions --email marta@example.com --apply
    python -m scripts.close_sessions --email marta@example.com --target railway --apply

A person signs in once and stays in (``app/services/sessions.py``). This is
how a session is cut from outside: every device of that account is signed
out at its next request and has to sign in again. The account, its points
and its history are not touched. The person can do the same from the app
("close my session on all my devices").

It is all the devices of the account or none: one device cannot be picked.

Without --apply it only says whose sessions it would close. With --target
railway it writes to UAT, so it only runs when the user asks for it.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts._target import TARGETS, guard_write, point_at


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import User
    from app.services.sessions import close_all_sessions

    email = args.email.strip().lower()
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(func.lower(User.email) == email))
        ).scalars().first()
        if user is None:
            print(f"  REFUSED: no account has the email '{email}'.")
            return 1
        print(f"  Account: {user.email} ({', '.join(user.roles)})")
        if not args.apply:
            await db.rollback()
            print("  Would close its sessions on every device.")
            print("  Nothing written: run again with --apply.")
            return 0
        close_all_sessions(user)
        await db.commit()
    print("  Closed: every device of this account has to sign in again.")
    return 0


async def main(args: argparse.Namespace) -> int:
    from app.db import engine

    try:
        return await _run(args)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--target", choices=TARGETS, default="local")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    parsed = parser.parse_args()
    print(f"Database: {point_at(parsed.target)}")
    guard_write(parsed.target, apply=parsed.apply, confirm=parsed.confirm)
    raise SystemExit(asyncio.run(main(parsed)))
