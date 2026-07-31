#!/usr/bin/env python
"""Add/update a password (viewer) user in configs/dashboard_users.yaml.

Prompts for username and password, writes a bcrypt hash. Password users
are always role=viewer (enforced server-side regardless of yaml content).
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

import bcrypt
import yaml


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--users-file",
        type=Path,
        default=Path("configs/dashboard_users.yaml"),
    )
    args = ap.parse_args()

    username = input("Username: ").strip()
    if not username:
        raise SystemExit("username required")
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("passwords do not match")
    if not password:
        raise SystemExit("empty password not allowed")

    path: Path = args.users_file
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
    data.setdefault("google", {})
    data.setdefault("password_users", {})

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    action = "updated" if username in data["password_users"] else "added"
    data["password_users"][username] = {"hash": hashed, "role": "viewer"}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True))
    print(f"{action} viewer user {username!r} in {path}")


if __name__ == "__main__":
    main()
