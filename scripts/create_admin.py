"""Bootstrap CLI: create the first admin user on a fresh deployment.

The two-eyes user-management workflow (POST /api/v1/users) requires an
existing admin to invite new users.  This script fills the cold-start
gap: it talks directly to the database to insert a single admin row
when the system has none.

Usage
-----

    python -m scripts.create_admin \
        --username mavacchi \
        --email mavacchi@gresmalt.it

    # optional overrides:
    #   --tenant-code GRESMALT     (default: auto-detect GRESMALT/CERAMIC_TILE_CO)
    #   --dsn postgresql://...     (default: read from DATABASE_URL / SQLALCHEMY_URL)

Behaviour
---------

1. Prompts for the password twice (no echo); rejects mismatches.
2. Refuses passwords shorter than 12 chars or containing whitespace.
3. Looks up the launch tenant (GRESMALT after M8 rebrand, with a
   CERAMIC_TILE_CO fallback for ambients still pre-M8).
4. Looks up the ``admin`` role (renamed from esg_manager in M24).
5. Refuses to insert if a row with the same (tenant_id, username) or
   (tenant_id, email) already exists.
6. Runs INSERT user + INSERT audit_log row in a single transaction.
   ``audit_log.after_state`` is the PII-free JSONB documented in
   docs/methodology.md §7 (only UUIDs, never the username or email).
7. Prints the new user's UUID on success; exits with non-zero status
   and a clear error message on any failure.

Security
--------

- Password is read via ``getpass.getpass()`` (no echo, never logged).
- The plain password is bcrypt-hashed using the same helper the API
  uses (``infrastructure.security.password.hash_password``), so the
  cost factor matches a normal login flow.
- The script does NOT use the API; it writes directly to PostgreSQL.
  Use it only on first deployment or after a total user wipe.
- Subsequent admins should be created via the Admin page in Streamlit
  or POST /api/v1/users.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import uuid
from typing import Final

try:
    import psycopg
except ImportError:
    print(
        "ERROR: psycopg is not installed in the active Python environment.\n"
        "  Activate the project venv first:\n"
        "    Windows:  .\\.venv\\Scripts\\Activate.ps1\n"
        "    Linux:    source .venv/bin/activate\n"
        "  Then re-run this script.",
        file=sys.stderr,
    )
    sys.exit(2)

# Lazy import — fails loud with a clear message if the venv is wrong.
try:
    from ghg_tool.infrastructure.security.password import hash_password
except ImportError as exc:
    print(
        f"ERROR: cannot import ghg_tool.infrastructure.security.password "
        f"({exc}).\n"
        "  Ensure you have run `pip install -e .[dev]` inside the project "
        "venv before running this script.",
        file=sys.stderr,
    )
    sys.exit(2)


_DEFAULT_TENANT_CANDIDATES: Final[tuple[str, ...]] = ("GRESMALT", "CERAMIC_TILE_CO")
_ADMIN_ROLE_CODE: Final[str] = "admin"
_MIN_PASSWORD_LENGTH: Final[int] = 12


def _resolve_dsn(cli_dsn: str | None) -> str:
    """Pick a PostgreSQL DSN from CLI flag or environment."""
    if cli_dsn:
        return _strip_async_driver(cli_dsn)
    raw = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("SQLALCHEMY_URL")
        or "postgresql://ghg_app:changeme@localhost:5432/ghg_tool"
    )
    return _strip_async_driver(raw)


def _strip_async_driver(dsn: str) -> str:
    """Convert ``postgresql+asyncpg://...`` (and friends) to plain psycopg DSN."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", dsn)


def _parse_args() -> argparse.Namespace:
    """Define and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap the first admin user on a fresh deployment. "
            "Subsequent admins should be created via the Admin page in "
            "Streamlit or POST /api/v1/users."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--username",
        required=True,
        help="Login username (must be unique within the tenant).",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Contact email (must be unique within the tenant).",
    )
    parser.add_argument(
        "--tenant-code",
        default=None,
        help=(
            "Tenant code to attach the user to. "
            f"Default: auto-detect from {_DEFAULT_TENANT_CANDIDATES}."
        ),
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help=(
            "PostgreSQL DSN. "
            "Default: $DATABASE_URL or $SQLALCHEMY_URL, "
            "fallback postgresql://ghg_app:changeme@localhost:5432/ghg_tool."
        ),
    )
    return parser.parse_args()


def _read_password_interactively() -> str:
    """Prompt twice for the password; validate length + whitespace."""
    while True:
        first = getpass.getpass("Password admin (non si vede a schermo): ")
        if len(first) < _MIN_PASSWORD_LENGTH:
            print(
                f"  Password troppo corta: minimo {_MIN_PASSWORD_LENGTH} caratteri."
            )
            continue
        if any(ch.isspace() for ch in first):
            print("  La password non puo contenere spazi.")
            continue
        second = getpass.getpass("Conferma password: ")
        if first != second:
            print("  Le password non coincidono. Riprova.")
            continue
        return first


def _resolve_tenant_id(conn: psycopg.Connection[tuple], explicit: str | None) -> uuid.UUID:
    """Find the tenant UUID by code, with a 2-candidate fallback chain."""
    candidates: tuple[str, ...] = (explicit,) if explicit else _DEFAULT_TENANT_CANDIDATES
    with conn.cursor() as cur:
        for code in candidates:
            cur.execute(
                "SELECT id FROM ref.tenants WHERE code = %s LIMIT 1",
                (code,),
            )
            row = cur.fetchone()
            if row is not None:
                print(f"Tenant trovato: code={code}, id={row[0]}")
                return row[0]
    raise RuntimeError(
        f"Nessun tenant trovato per i codici {list(candidates)}. "
        "Esegui `alembic upgrade head` o passa --tenant-code esplicito."
    )


def _resolve_admin_role_id(conn: psycopg.Connection[tuple]) -> uuid.UUID:
    """Find the admin role UUID; fail with a clear message if M24 not applied."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM ref.roles WHERE role_code = %s LIMIT 1",
            (_ADMIN_ROLE_CODE,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"Ruolo '{_ADMIN_ROLE_CODE}' non trovato in ref.roles. "
                "Esegui `alembic upgrade head` per applicare M24."
            )
        return row[0]


def _ensure_no_collision(
    conn: psycopg.Connection[tuple],
    *,
    tenant_id: uuid.UUID,
    username: str,
    email: str,
) -> None:
    """Refuse to insert if username or email already exists in this tenant."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT username, email FROM ref.users "
            "WHERE tenant_id = %s AND (username = %s OR email = %s) "
            "LIMIT 1",
            (tenant_id, username, email),
        )
        row = cur.fetchone()
        if row is not None:
            existing_username, existing_email = row
            if existing_username == username:
                raise RuntimeError(
                    f"Username '{username}' gia esistente nel tenant. "
                    "Scegli un altro username o usa l'Admin page per gestire "
                    "l'utente esistente."
                )
            raise RuntimeError(
                f"Email '{existing_email}' gia esistente nel tenant. "
                "Usa un'altra email."
            )


def _insert_admin(
    conn: psycopg.Connection[tuple],
    *,
    tenant_id: uuid.UUID,
    username: str,
    email: str,
    password_hash: str,
    role_id: uuid.UUID,
) -> uuid.UUID:
    """Insert the user row + audit_log row inside a single transaction."""
    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    after_state = json.dumps(
        {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "role_id": str(role_id),
        }
    )

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ref.users "
            "  (id, tenant_id, username, email, password_hash, role_id, "
            "   is_active, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, TRUE, now())",
            (user_id, tenant_id, username, email, password_hash, role_id),
        )
        cur.execute(
            "INSERT INTO calc.audit_log "
            "  (id, tenant_id, correlation_id, occurred_at, user_id, "
            "   user_role, action, resource, resource_id, "
            "   request_method, request_path, status_code, after_state) "
            "VALUES (gen_random_uuid(), %s, %s, now(), %s, "
            "        'admin', 'user_created', 'users', %s, "
            "        'CLI', 'scripts.create_admin', 201, %s::jsonb)",
            (tenant_id, correlation_id, user_id, user_id, after_state),
        )
    conn.commit()
    return user_id


def main() -> int:
    """Entry point: parse args, prompt password, insert admin."""
    args = _parse_args()
    dsn = _resolve_dsn(args.dsn)
    print(f"DSN: {_redact(dsn)}")
    password = _read_password_interactively()
    print("Hashing password (bcrypt rounds=12)...")
    password_hash = hash_password(password)

    try:
        with psycopg.connect(dsn) as conn:
            tenant_id = _resolve_tenant_id(conn, args.tenant_code)
            role_id = _resolve_admin_role_id(conn)
            _ensure_no_collision(
                conn,
                tenant_id=tenant_id,
                username=args.username,
                email=args.email,
            )
            user_id = _insert_admin(
                conn,
                tenant_id=tenant_id,
                username=args.username,
                email=args.email,
                password_hash=password_hash,
                role_id=role_id,
            )
    except psycopg.OperationalError as exc:
        print(
            f"\nERRORE: impossibile connettersi al database.\n  {exc}\n\n"
            "  Verifica che PostgreSQL sia in esecuzione e che la DSN sia "
            "corretta (env DATABASE_URL o flag --dsn).",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as exc:
        print(f"\nERRORE: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"\nERRORE database: {exc}", file=sys.stderr)
        return 1

    print()
    print("=" * 64)
    print(f"  OK -- admin '{args.username}' creato.")
    print(f"  user_id   : {user_id}")
    print(f"  tenant_id : {tenant_id}")
    print("  role      : admin")
    print()
    print("  Verifica login:")
    print(
        f"    curl -X POST http://localhost:8000/api/v1/auth/login "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"username\":\"{args.username}\","
        '"password":"<la-password-che-hai-digitato>"}\''
    )
    print("=" * 64)
    return 0


def _redact(dsn: str) -> str:
    """Replace the password in a DSN with '***' for safe logging."""
    return re.sub(r"://([^:]+):[^@]*@", r"://\1:***@", dsn)


if __name__ == "__main__":
    sys.exit(main())
