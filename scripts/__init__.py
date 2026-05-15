"""Operational scripts for the GHG Tool — not shipped in the runtime image.

These are admin-side utilities for bootstrapping a fresh deployment:

  - ``create_admin.py``     — bootstrap the first admin user on a fresh
                              deployment (the two-eyes user-management
                              workflow needs an existing admin to invite
                              new ones; this script fills the cold-start
                              gap).
  - ``create_user.py``      — create a user account in ``ref.users`` with a
                              bcrypt-hashed password (legacy generic helper).
  - ``seed_demo_data.py``   — ingest the Gresmalt CSVs in ``data/raw/`` into
                              the ``raw.scope{1,2,3}_ingestions`` staging
                              tables and persist DQ findings.

All scripts use sync ``psycopg`` (already a project dependency for Alembic).
"""
