"""Operator CLI: `python -m app.cli <command>`.

- `create-user` — seeds/updates the single-user account (no open
  registration anywhere in the app).
- `wipe-data` — the complete-wipe scope, run synchronously against the DB
  directly (no worker/Redis required) for ops use on a stuck deployment.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from sqlalchemy import select

from app.config import get_config
from app.db import get_sessionmaker
from app.models.user import User
from app.services.auth.passwords import hash_password
from app.services.privacy.deletion import wipe_everything
from app.services.storage.local import LocalStorage


def create_user(email: str, password: str | None) -> None:
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("passwords do not match", file=sys.stderr)
            raise SystemExit(1)
    password_hash = hash_password(password)
    with get_sessionmaker()() as session:
        existing = session.scalar(select(User).where(User.email == email))
        if existing is not None:
            existing.password_hash = password_hash
            action = "updated"
        else:
            session.add(User(email=email, password_hash=password_hash))
            action = "created"
        session.commit()
    print(f"user {action}: {email}")


def wipe_data(*, confirm: bool) -> None:
    if not confirm:
        typed = input(
            "This permanently deletes ALL application data except the user account. "
            "Type WIPE to continue: "
        )
        if typed != "WIPE":
            print("aborted")
            raise SystemExit(1)
    with get_sessionmaker()() as session:
        storage = LocalStorage(get_config().data_dir)
        report = wipe_everything(session, storage)
    print(json.dumps(report, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_user_parser = subparsers.add_parser("create-user", help="seed or update the account")
    create_user_parser.add_argument("--email", required=True)
    create_user_parser.add_argument(
        "--password", default=None, help="omit to be prompted (recommended)"
    )

    wipe_parser = subparsers.add_parser("wipe-data", help="delete all application data")
    wipe_parser.add_argument(
        "--yes", action="store_true", help="skip the interactive confirmation prompt"
    )

    args = parser.parse_args(argv)
    if args.command == "create-user":
        create_user(args.email, args.password)
    elif args.command == "wipe-data":
        wipe_data(confirm=args.yes)


if __name__ == "__main__":
    main()
