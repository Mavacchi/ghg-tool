"""Staging writer — inserts validated rows into raw.scope{1,2,3}_ingestions.

Implements idempotency: a row is only inserted if its ``idempotency_key``
does not already exist for the current batch.  Returns UUIDs for downstream
Cat 3 reconciliation.

Plumbing for calc modules (wave 2):
  Each raw row inserted carries ``ingestion_batch_id``, enabling the
  data-analyst calc modules to join raw → emission via raw_row_id FK.
  ``correlation_id``, ``factor_source/version/gwp_set/methodology``
  columns on emissions_consolidated are populated by the calc modules,
  not here.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from typing import Any

import pandas as pd


def _to_decimal(value: Any) -> Decimal:
    """Coerce a CSV-derived numeric value to ``Decimal`` without float artefacts.

    The pandera schemas coerce ``Quantità`` to ``float`` for validation, but
    the destination columns ``raw.scope{1,2,3}_ingestions.quantita`` are
    ``Numeric(20, 6)``.  Routing through ``Decimal(str(...))`` preserves the
    exact decimal representation and avoids IEEE-754 binary-fraction noise
    such as ``Decimal(0.1) == 0.1000000000000000055511151231257827021181583404541015625``.

    Args:
        value: Numeric value from a pandera-validated DataFrame.

    Returns:
        Equivalent ``Decimal`` value.
    """
    return Decimal(str(value))


def _build_idempotency_key(parts: list[str]) -> str:
    """Derive a deterministic idempotency key from row-identifying parts.

    Args:
        parts: List of string values that uniquely identify the row
               (e.g. [codice_sito, anno, combustibile, provenance]).

    Returns:
        SHA-256 hex digest of the concatenated parts (truncated to 120 chars).
    """
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:120]


def build_scope1_rows(
    df: pd.DataFrame,
    *,
    batch_id: uuid.UUID,
    tenant_id: uuid.UUID,
    ingested_by: str,
) -> list[dict[str, Any]]:
    """Translate a validated Scope 1 DataFrame into raw insert dicts.

    Args:
        df: Validated Scope 1 DataFrame (post pandera + transforms).
        batch_id: UUID of the parent ingestion batch.
        tenant_id: Tenant UUID.
        ingested_by: Username or service account string.

    Returns:
        List of dicts ready for ``raw.scope1_ingestions`` INSERT.
    """
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        provenance = str(row.get("_provenance", "native"))
        idem_key = _build_idempotency_key(
            [str(row["Codice_Sito"]), str(row["Anno"]),
             str(row["Combustibile"]), provenance]
        )
        rows.append(
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "batch_id": batch_id,
                "scope": 1,
                "anno": int(row["Anno"]),
                "codice_sito": str(row["Codice_Sito"]),
                "categoria_s1": str(row["Categoria_S1"]),
                "combustibile": str(row["Combustibile"]),
                "quantita": _to_decimal(row["Quantità"]),
                "unita": str(row["Unità"]),
                "fonte_dato": str(row.get("Fonte_Dato", "")),
                "qualita_dato": str(row.get("Qualità_Dato", "")),
                "stato_dato": str(row.get("Stato_Dato", "")),
                "note": str(row["Note"]) if pd.notna(row.get("Note")) else None,
                "provenance": provenance,
                "provenance_rationale": str(row.get("_provenance_rationale", ""))
                    if pd.notna(row.get("_provenance_rationale")) else None,
                "idempotency_key": idem_key,
                "ingested_by": ingested_by,
            }
        )
    return rows


def build_scope2_rows(
    df: pd.DataFrame,
    *,
    batch_id: uuid.UUID,
    tenant_id: uuid.UUID,
    ingested_by: str,
) -> list[dict[str, Any]]:
    """Translate a validated Scope 2 DataFrame into raw insert dicts.

    Args:
        df: Validated Scope 2 DataFrame (post pandera + transforms).
        batch_id: UUID of the parent ingestion batch.
        tenant_id: Tenant UUID.
        ingested_by: Username or service account string.

    Returns:
        List of dicts ready for ``raw.scope2_ingestions`` INSERT.
    """
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        provenance = str(row.get("_provenance", "native"))
        idem_key = _build_idempotency_key(
            [str(row["Codice_Sito"]), str(row["Anno"]),
             str(row["Voce_S2"]), provenance]
        )
        rows.append(
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "batch_id": batch_id,
                "scope": 2,
                "anno": int(row["Anno"]),
                "codice_sito": str(row["Codice_Sito"]),
                "voce_s2": str(row["Voce_S2"]),
                "quantita": _to_decimal(row["Quantità"]),
                "unita": str(row["Unità"]),
                "strumento_mb": str(row["Strumento_MB"])
                    if pd.notna(row.get("Strumento_MB")) else None,
                "fonte_dato": str(row.get("Fonte_Dato", "")),
                "qualita_dato": str(row.get("Qualità_Dato", "")),
                "stato_dato": str(row.get("Stato_Dato", "")),
                "note": str(row["Note"]) if pd.notna(row.get("Note")) else None,
                "provenance": provenance,
                "provenance_rationale": str(row.get("_provenance_rationale", ""))
                    if pd.notna(row.get("_provenance_rationale")) else None,
                "idempotency_key": idem_key,
                "ingested_by": ingested_by,
            }
        )
    return rows


def build_scope3_rows(
    df: pd.DataFrame,
    *,
    batch_id: uuid.UUID,
    tenant_id: uuid.UUID,
    ingested_by: str,
) -> list[dict[str, Any]]:
    """Translate a validated Scope 3 DataFrame into raw insert dicts.

    Args:
        df: Validated Scope 3 DataFrame (post pandera + FR-37 transforms).
        batch_id: UUID of the parent ingestion batch.
        tenant_id: Tenant UUID.
        ingested_by: Username or service account string.

    Returns:
        List of dicts ready for ``raw.scope3_ingestions`` INSERT.
    """
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        combustibile = str(row["Combustibile"]) if pd.notna(row.get("Combustibile")) else ""
        idem_key = _build_idempotency_key(
            [str(row["Anno"]), str(row["Categoria_S3"]),
             str(row["Sottocategoria"]), combustibile]
        )
        rows.append(
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "batch_id": batch_id,
                "scope": 3,
                "anno": int(row["Anno"]),
                "categoria_s3": int(row["Categoria_S3"]),
                "sottocategoria": str(row["Sottocategoria"]),
                "metodo": str(row["Metodo"]),
                "combustibile": combustibile or None,
                "quantita": _to_decimal(row["Quantità"]),
                "unita": str(row["Unità"]),
                "fonte_dato": str(row.get("Fonte_Dato", "")),
                "qualita_dato": str(row.get("Qualità_Dato", "")),
                "stato_dato": str(row.get("Stato_Dato", "")),
                "note": str(row["Note"]) if pd.notna(row.get("Note")) else None,
                "metadata_defaulted": bool(row.get("_metadata_defaulted", False)),
                "defaulting_rule_id": str(row.get("_defaulting_rule_id", ""))
                    if pd.notna(row.get("_defaulting_rule_id")) else None,
                "idempotency_key": idem_key,
                "ingested_by": ingested_by,
            }
        )
    return rows
