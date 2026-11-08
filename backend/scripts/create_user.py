"""Invite a user (accounts are invite-only; there is no sign-up route). L13.

    python -m scripts.create_user --demo                 # the demo customer (owns the demo inbox)
    python -m scripts.create_user --username admin --role admin

Asks for the password twice (at least 12 characters), or reads it from
`SENTINEL_NEW_PASSWORD` for scripted setup. Then prints a one-time TOTP setup
link and secret: add them to an authenticator app now, they are not shown again
(the stored copy is encrypted with AES-256-GCM). After the first sign-in, add a
passkey from the privacy panel and use that instead.

Run from `backend/` with `AUTH_ENABLED=true` and the keys from `scripts.auth_keys` in `.env`.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys

from app.auth import mfa
from app.auth.deps import DEMO_CUSTOMER_ID
from app.auth.passwords import WeakPasswordError, hash_password
from app.auth.store import AuthStore
from app.config import get_settings
from app.crypto import KeyRing


def _password() -> str:
    from_env = os.environ.get("SENTINEL_NEW_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass("Password (12+ characters): ")
    if first != getpass.getpass("Again: "):
        sys.exit("Passwords didn't match.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username")
    parser.add_argument("--display-name")
    parser.add_argument("--role", choices=["customer", "admin"], default="customer")
    parser.add_argument("--demo", action="store_true", help="create the demo customer that owns the demo inbox")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.DATA_ENCRYPTION_KEYS is None:
        sys.exit("DATA_ENCRYPTION_KEYS is not set. Run `python -m scripts.auth_keys` first.")
    username = args.username or ("demo" if args.demo else None)
    if not username:
        sys.exit("Give --username, or --demo for the demo customer.")

    try:
        password_hash = hash_password(_password())
    except WeakPasswordError as exc:
        sys.exit(f"Password not accepted: {exc}.")

    keyring = KeyRing.parse(settings.DATA_ENCRYPTION_KEYS.get_secret_value())
    store = AuthStore(settings.auth_db_path)
    try:
        user = store.create_user(
            username,
            args.display_name or username.title(),
            "customer" if args.demo else args.role,
            password_hash,
            user_id=DEMO_CUSTOMER_ID if args.demo else None,
        )
    except sqlite3.IntegrityError:
        sys.exit(f"A user named {username!r} (or the demo customer) already exists.")
    secret = mfa.new_secret()
    store.set_totp_secret(user.id, keyring.encrypt(secret, mfa.aad(user.id)))
    store.audit.record("user.created", actor="cli", target=user.id, details={"role": user.role})
    store.close()

    print(f"Created {user.role} {username!r} in {settings.auth_db_path}.")
    print("Add this to an authenticator app now. It is shown only once:")
    print(f"  {mfa.provisioning_uri(secret, username)}")
    print(f"  (or type the secret: {secret})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
