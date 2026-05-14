"""CLI to create a user account in ``ref.users`` with a bcrypt password.

Designed to be run inside the ``app`` container (which already has the
project + ``psycopg`` + ``bcrypt`` installed):

    docker compose --profile app exec app \\
        python -m scripts.create_user --username marco \\
                                      --email marco@example.com \\
                                      --role esg_manager

The password is read from stdin (or the ``GHG_NEW_USER_PASSWORD`` env var)
so it never appears in shell history or process listings.

Exit codes:
  0  — user created successfully
  1  — generic error (DB unreachable, invalid args, etc.)
  2  — user with that (tenant, username) already exists
  3  — role or tenant not found
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from getpass import getpass

import psycopg

from ghg_tool.infrastructure.security.password import hash_password

_DEFAULT_DSN = "postgresql://ghg_app:changeme@localhost:5432/ghg_tool"
_DEFAULT_TENANT_CODE = "CERAMIC_TILE_CO"
_VALID_ROLES = ("data_steward", "esg_manager", "auditor")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,120}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LEN = 8


def _dsn() -> str:
    """Return the synchronous psycopg DSN.

    Honours ``DATABASE_URL`` / ``SQLALCHEMY_URL`` if present so the script
    follows the same connection settings as Alembic. Strips the SQLAlchemy
    driver prefix (``postgresql+asyncpg://`` / ``postgresql+psycopg://``)
    so psycopg can parse the URL.
    """
    raw = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_URL") or _DEFAULT_DSN
    return re.sub(r"^postgresql\+\w+://", "postgresql://", raw)


def _read_password(prompt_label: str) -> str:
    """Read the password from the env var or interactively from stdin."""
    env_pw = os.getenv("GHG_NEW_USER_PASSWORD")
    if env_pw:
        return env_pw
    pw1 = getpass(f"{prompt_label}: ")
    pw2 = getpass(f"{prompt_label} (again): ")
    if pw1 != pw2:
        raise SystemExit("Passwords do not match.")
    return pw1


def _validate(args: argparse.Namespace, password: str) -> None:
    if not _USERNAME_RE.match(args.username):
        raise SystemExit(
            f"Invalid username '{args.username}': must match {_USERNAME_RE.pattern}"
        )
    if not _EMAIL_RE.match(args.email):
        raise SystemExit(f"Invalid email '{args.email}'.")
    if args.role not in _VALID_ROLES:
        raise SystemExit(
            f"Invalid role '{args.role}': must be one of {', '.join(_VALID_ROLES)}"
        )
    if len(password) < _MIN_PASSWORD_LEN:
        raise SystemExit(
            f"Password must be at least {_MIN_PASSWORD_LEN} characters long."
        )


def _lookup_ids(
    cur: psycopg.Cursor[tuple[uuid.UUID, ...]], *, tenant_code: str, role_code: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """Resolve tenant_id and role_id by their natural keys.

    Raises SystemExit(3) if either is missing — typically means migrations
    haven't been applied yet.
    """
    cur.execute("SELECT id FROM ref.tenants WHERE code = %s", (tenant_code,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(
            f"Tenant '{tenant_code}' not found. Did you run `alembic upgrade head`?"
        )
    tenant_id: uuid.UUID = row[0]

    cur.execute("SELECT id FROM ref.roles WHERE role_code = %s", (role_code,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"Role '{role_code}' not found in ref.roles.")
    role_id: uuid.UUID = row[0]

    return tenant_id, role_id


def _insert_user(
    cur: psycopg.Cursor[tuple[uuid.UUID, ...]],
    *,
    tenant_id: uuid.UUID,
    username: str,
    email: str,
    password_hash_value: str,
    role_id: uuid.UUID,
) -> uuid.UUID:
    """Insert one user; raise SystemExit(2) on UNIQUE collision."""
    try:
        cur.execute(
            """
            INSERT INTO ref.users
                (tenant_id, username, email, password_hash, role_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (tenant_id, username, email, password_hash_value, role_id),
        )
    except psycopg.errors.UniqueViolation as exc:
        raise SystemExit(
            f"User '{username}' already exists for tenant '{tenant_id}'."
        ) from exc
    row = cur.fetchone()
    assert row is not None  # noqa: S101 — RETURNING guarantees one row
    return row[0]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a user account in ref.users with a bcrypt password.",
    )
    parser.add_argument("--username", required=True, help="Unique username within the tenant.")
    parser.add_argument("--email", required=True, help="User email (unique within tenant).")
    parser.add_argument(
        "--role",
        required=True,
        choices=_VALID_ROLES,
        help="Role to assign — one of: " + ", ".join(_VALID_ROLES),
    )
    parser.add_argument(
        "--tenant-code",
        default=_DEFAULT_TENANT_CODE,
        help=f"ref.tenants.code (default: {_DEFAULT_TENANT_CODE}).",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help=(
            "PostgreSQL DSN. Defaults to DATABASE_URL / SQLALCHEMY_URL env "
            f"vars, else {_DEFAULT_DSN}."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    password = _read_password(f"Password for {args.username}")
    _validate(args, password)

    password_hash_value = hash_password(password)
    dsn = args.dsn or _dsn()

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        tenant_id, role_id = _lookup_ids(
            cur, tenant_code=args.tenant_code, role_code=args.role
        )
        user_id = _insert_user(
            cur,
            tenant_id=tenant_id,
            username=args.username,
            email=args.email,
            password_hash_value=password_hash_value,
            role_id=role_id,
        )
        conn.commit()

    print(
        f"OK — created user '{args.username}' "
        f"(id={user_id}, role={args.role}, tenant={args.tenant_code})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
