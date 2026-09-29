"""Provision the first administrator or recover an account locally."""

import argparse
from getpass import getpass

from backend.app.auth.security import hash_password
from backend.app.core.config import get_settings
from backend.app.storage.accounts import AccountStore
from backend.app.storage.database import initialize_db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["bootstrap-admin", "reset-password"])
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    path = get_settings().APP_DATABASE_PATH
    initialize_db(path)
    store = AccountStore(path)
    if args.command == "bootstrap-admin" and store.list_accounts(limit=1)["total"]:
        raise SystemExit("Bootstrap is available only for an empty account database.")
    target = store.by_username(args.username) if args.command == "reset-password" else None
    if args.command == "reset-password" and target is None:
        raise SystemExit("Account not found.")
    password = getpass("New password (12+ characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords did not match")
    try:
        encoded = hash_password(password)
        if args.command == "bootstrap-admin":
            store.create(args.username, args.username, "admin", encoded, None, False)
            print("Administrator account created. The password was not printed.")
        else:
            store.update(target["id"], None, password_hash=encoded, must_change_password=True)
            print("Password reset. Existing sessions were revoked; a change is required at next sign-in.")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
