"""Diagnose login failures: list users, verify a password against the stored hash.

This bypasses the HTTP endpoint, the rate limiter, JWT issuance and the TOTP
branch — it goes straight to ``ref.users.password_hash`` and runs the exact
``verify_password`` helper the API uses, so the answer it prints is the answer
the API would also produce.

Usage (inside the ghg_app container)
------------------------------------

List users with the state the login flow cares about:

    docker exec ghg_app python -m scripts.debug_login --list

Verify a specific username + password pair:

    docker exec -it ghg_app python -m scripts.debug_login --verify --username mavacchi

The script will prompt for the password (no echo) and print one of:

    OK              — password matches, user is active, role join succeeds
    WRONG_PASSWORD  — user exists but bcrypt.checkpw returned False
    INACTIVE        — user.is_active = false (login would return 401)
    NO_ROLE         — role_id does not join to ref.roles (login lookup returns None)
    HASH_INVALID    — password_hash is not a parseable bcrypt string
    NOT_FOUND       — no user row with that username

The plain password is never logged or written anywhere.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

import psycopg2

from ghg_tool.infrastructure.security.password import verify_password


def _dsn() -> str:
    """Read the sync DSN from env. The async ``+asyncpg`` URL is converted."""
    for key in ("DATABASE_URL", "SQLALCHEMY_URL"):
        v = os.environ.get(key, "").strip()
        if v:
            return v.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")
    return "postgresql://ghg_app:changeme@db:5432/ghg_tool"


def _list_users() -> int:
    """Print one row per user with the fields the login flow checks."""
    with psycopg2.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT u.username, "
            "       LEFT(u.password_hash, 7) AS hash_prefix, "
            "       LENGTH(u.password_hash)  AS hash_len, "
            "       u.is_active, "
            "       COALESCE(r.role_code, '<MISSING>') AS role_code, "
            "       COALESCE(t.code, '<MISSING>')      AS tenant_code "
            "FROM ref.users u "
            "LEFT JOIN ref.roles  r ON r.id = u.role_id "
            "LEFT JOIN ref.tenants t ON t.id = u.tenant_id "
            "ORDER BY u.created_at"
        )
        rows = cur.fetchall()

    if not rows:
        print("(ref.users is empty)")
        return 0
    fmt = "{:<24} {:<10} {:>8} {:<8} {:<14} {:<14}"
    print(fmt.format("username", "hash_pfx", "hash_len", "active", "role", "tenant"))
    print("-" * 80)
    for r in rows:
        print(fmt.format(*[str(c) for c in r]))
    print()
    print("Healthy bcrypt hash:  prefix '$2b$12$', length 60.")
    print("If prefix or length is off, the row was inserted with a non-bcrypt value")
    print("(e.g. plaintext or a hash from a different algorithm).")
    return 0


def _verify(username: str) -> int:
    """Run the exact verify_password the API uses."""
    password = getpass.getpass(f"Password per {username}: ")
    with psycopg2.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT u.password_hash, u.is_active, "
            "       COALESCE(r.role_code, '<MISSING>') AS role_code "
            "FROM ref.users u "
            "LEFT JOIN ref.roles r ON r.id = u.role_id "
            "WHERE u.username = %s",
            (username,),
        )
        row = cur.fetchone()
    if row is None:
        print("NOT_FOUND — nessun utente con questo username in ref.users")
        return 2

    password_hash, is_active, role_code = row
    if not password_hash or not password_hash.startswith("$2"):
        print(f"HASH_INVALID — password_hash inizia con '{password_hash[:7] if password_hash else ''}', non e' un bcrypt")
        return 2
    if role_code == "<MISSING>":
        print("NO_ROLE — role_id non joina ref.roles; il login lookup tornerebbe None")
        return 2
    if not is_active:
        print("INACTIVE — utente disabilitato, il login tornerebbe 401")
        return 2

    if verify_password(password, password_hash):
        print(f"OK — credenziali corrette, role='{role_code}', is_active=True")
        return 0
    print("WRONG_PASSWORD — bcrypt.checkpw ha restituito False: la password inserita")
    print("non corrisponde all'hash salvato. Cause tipiche:")
    print("  * stai digitando una password diversa da quella usata al create_admin")
    print("  * GHG_BOOTSTRAP_ADMIN_PASSWORD_HASH nel .env e' l'hash di una password")
    print("    diversa da quella che stai provando")
    print("  * caps lock / layout di tastiera diverso")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="elenca gli utenti")
    g.add_argument("--verify", action="store_true", help="verifica username+password")
    p.add_argument("--username", help="username da verificare (con --verify)")
    args = p.parse_args()

    if args.list:
        return _list_users()
    if args.verify:
        if not args.username:
            print("--username e' obbligatorio con --verify", file=sys.stderr)
            return 64
        return _verify(args.username)
    return 64


if __name__ == "__main__":
    sys.exit(main())
