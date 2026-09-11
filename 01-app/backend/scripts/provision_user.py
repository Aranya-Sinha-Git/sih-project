"""Provision or promote a Supabase Auth user with explicit administrator input.

This command intentionally has no credential defaults. It uses the server-only
Supabase key and is the administrative path for reviewer/admin promotion.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import create_auth_user, username_to_internal_email  # noqa: E402
from app.services.database import SupabaseDatabase  # noqa: E402


def load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() and name.strip() not in os.environ:
            os.environ[name.strip()] = value.strip().strip('"')


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser(description="Provision a SIF Sentinel user with an explicit role.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", required=True, choices=("member", "reviewer", "admin"))
    args = parser.parse_args()
    username = username_to_internal_email(args.user_id).split("@", 1)[0]
    email = username_to_internal_email(username)
    database = SupabaseDatabase()
    existing_profile = database.get_profile_by_username(username)
    if existing_profile:
        user_id = str(existing_profile["id"])
        print("Auth user already exists; password was not changed.")
    else:
        user = create_auth_user(email=email, password=args.password, username=username, display_name=args.display_name)
        user_id = user["id"]
        print("Created Auth user.")
    profile = {"id": user_id, "username": username, "display_name": args.display_name, "role": args.role}
    if existing_profile:
        database.update_profile(user_id, {key: value for key, value in profile.items() if key != "id"})
    else:
        database.create_profile(profile)
    print(f"Profile ready for User ID: {username} ({args.role})")


if __name__ == "__main__":
    main()
