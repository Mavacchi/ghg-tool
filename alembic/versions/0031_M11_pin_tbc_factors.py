"""M11 — Pin previously-TBC factor values (ISPRA / AIB / DEFRA WTT).

Wave 5 — Cluster METHOD — addresses audit findings F4 (ISPRA grid LB),
F5 (AIB residual mix), F13 (DEFRA 2025 WTT fuels and electricity).

Strategy
--------
The M2 seed (`0003_M2_factor_catalog_seed`) inserts these rows with
``value = NULL`` and ``is_tbc = TRUE`` and ``is_published = FALSE``.  Although
the anti-mutation trigger ``ops.deny_factor_mutation`` blocks UPDATE/DELETE on
published rows, an integration test could publish those rows before this
migration runs; we therefore defensively DISABLE the trigger for the duration
of the UPDATE and ENABLE it again at the end.  This is the canonical pattern
documented in ``docs/methodology.md §5`` for factor revisions.

Factors pinned
--------------
- LB_IT_GRID_ISPRA_2024   = 0.216 kg CO2/kWh
  Source: ISPRA — Rapporto 413/2025 "Le emissioni di CO2 nel settore elettrico",
          production-side factor for 2023 data (publication 2025-05).
  URL: https://emissioni.sina.isprambiente.it/wp-content/uploads/2025/05/
       Le-emissioni-di-CO2-nel-settore-elettrico_r413-2025_def.pdf
  Note: a consumption-side variant (~0.243 kg CO2eq/kWh) exists in Table 3 of
  the PDF; v1 uses the production-side value because it is the figure most
  consistently citable from the publicly available ISPRA web excerpts at the
  time of pinning.  Once the PDF is downloaded and SHA-256 pinned the
  ``parse_ispra_pdf`` loader will extract the consumption-side value and a
  new factor version will be inserted via the standard immutability workflow.

- MB_IT_RESIDUAL_AIB_2024 = 0.441 kg CO2e/kWh (= 441 gCO2/kWh)
  Source: AIB — European Residual Mix 2024 results (published 2025-05-30).
  URL: https://www.aib-net.org/sites/default/files/assets/facts/residual-mix/
       2024/2024_Final%20_Residual%20mix%20calculation%20results_30052025.pdf
  Wave 5 web verification 2026-05-16: Italy 2024 = 441 gCO2/kWh; differs
  from the audit-prompt suggested value of 0.456 — see docs/factor_sources.md
  §"Open issues" O2.

- WTT_GAS_NAT_DEFRA_2025  = 0.46 kg CO2e/Sm3 (DEFRA 2024/2025 WTT fuels)
- WTT_GASOLIO_DEFRA_2025  = 0.60 kg CO2e/litre
- WTT_BENZINA_DEFRA_2025  = 0.59 kg CO2e/litre
- WTT_ELEC_DEFRA_2025     = 0.039 kg CO2e/kWh
  Source: UK Government GHG Conversion Factors 2024 (DESNZ/DEFRA) — WTT fuels
  and electricity WTT tables (publication June 2024).
  URL: https://www.gov.uk/government/collections/
       government-conversion-factors-for-company-reporting
  Note: DEFRA 2025 values are within +/- 5% of 2024; pin uses 2024-published
  values as interim until the DEFRA 2025 spreadsheet hash is set in
  ``seed_loader.py`` (see docs/factor_sources.md §"Open issues" O3).

After UPDATE the rows transition from ``is_tbc=TRUE / is_published=FALSE``
to ``is_tbc=FALSE / is_published=TRUE`` with ``published_at = now()`` and
``published_by = 'system_seed_wave5'``.

Revision: 0031_M11
Revises: 0030_M10
"""

from __future__ import annotations

from alembic import op

revision: str = "0031_M11"
down_revision: str = "0030_M10"
branch_labels: str | None = None
depends_on: str | None = None


# ---------------------------------------------------------------------------
# Pinned values
# Each entry: factor_id -> (value, unit_for_audit_log_note)
# Stored verbatim in DB (no unit conversion — units already correct on the row).
# ---------------------------------------------------------------------------
_PINNED_VALUES: dict[str, float] = {
    "LB_IT_GRID_ISPRA_2024": 0.216,
    "MB_IT_RESIDUAL_AIB_2024": 0.441,
    "WTT_GAS_NAT_DEFRA_2025": 0.46,
    "WTT_GASOLIO_DEFRA_2025": 0.60,
    "WTT_BENZINA_DEFRA_2025": 0.59,
    "WTT_ELEC_DEFRA_2025": 0.039,
}


def upgrade() -> None:
    """Pin TBC factor values and publish the affected rows.

    Disables the ``trg_factor_immutable`` trigger for the duration of the
    UPDATE so that rows which may already be published in integration tests
    can still be transitioned from ``is_tbc=TRUE`` to a pinned value.
    Re-enables the trigger before completion.
    """
    # 1. Defensively disable the immutability trigger for this transaction.
    op.execute(
        "ALTER TABLE ref.factor_catalog DISABLE TRIGGER trg_factor_immutable;"
    )

    try:
        for factor_id, value in _PINNED_VALUES.items():
            op.execute(
                f"""
                UPDATE ref.factor_catalog
                   SET value         = {value},
                       is_tbc        = FALSE,
                       is_published  = TRUE,
                       published_by  = 'system_seed_wave5',
                       published_at  = now()
                 WHERE factor_id = '{factor_id}'
                   AND is_tbc = TRUE;
                """
            )
    finally:
        # 2. Always re-enable the trigger, even if an UPDATE failed.
        op.execute(
            "ALTER TABLE ref.factor_catalog ENABLE TRIGGER trg_factor_immutable;"
        )


def downgrade() -> None:
    """Revert pinned values to the prior TBC state.

    Restores ``value = NULL``, ``is_tbc = TRUE``, ``is_published = FALSE``,
    and clears ``published_at`` / ``published_by``.  The trigger is disabled
    around the UPDATE for symmetry with upgrade().
    """
    op.execute(
        "ALTER TABLE ref.factor_catalog DISABLE TRIGGER trg_factor_immutable;"
    )
    try:
        ids_sql = ", ".join(f"'{fid}'" for fid in _PINNED_VALUES)
        op.execute(
            f"""
            UPDATE ref.factor_catalog
               SET value         = NULL,
                   is_tbc        = TRUE,
                   is_published  = FALSE,
                   published_by  = 'system_seed',
                   published_at  = NULL
             WHERE factor_id IN ({ids_sql});
            """
        )
    finally:
        op.execute(
            "ALTER TABLE ref.factor_catalog ENABLE TRIGGER trg_factor_immutable;"
        )
