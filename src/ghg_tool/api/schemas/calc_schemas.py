"""Pydantic v2 schemas for the auto-calc preview/insert API.

Implements the API contract from auto_calc_design.md §10 with validators
for every conditional field (§2.1, §2.2, §2.7 customer-feedback updates).

Schema hierarchy:
    CalcInputRequest    — universal input for any scope/sub-scope
    CalcPreviewResponse — read-only calc trace (no DB write)
    CalcInsertResponse  — extends preview with emission_id + audit fields

Validators enforce:
    - S1 combustion: combustibile + codice_sito required
    - S1 process:    codice_sito required, process_mode default 'direct_tco2',
                     if mode='direct_tco2' then unita must be 'tCO2'
    - S2 MB/LB:      codice_sito required
    - S2 MB:         strumento_mb required
    - S3:            sottocategoria + metodo required; codice_sito MUST be None
                     (Scope 3 is corporate-level, not per-site)
                     Decision 2026-05-15: "S3 è corporate, di tutto il gruppo,
                     non per una specifica sede".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class CalcInputRequest(BaseModel):
    """Universal auto-calc input — valid for any scope / sub-scope combination.

    All conditional fields are typed as ``X | None`` and enforced by the
    ``_validate_conditional_fields`` model-level validator so that upstream
    pydantic validation reports all missing fields at once rather than the
    first one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Literal[1, 2, 3] = Field(description="GHG Protocol scope (1, 2, or 3)")
    sub_scope: Literal[
        "combustion",
        "process",
        "lb",
        "mb",
        "cat1_purchased_goods",
        "cat3_fuel_energy",
        "cat4_upstream_transport",
        "cat5_waste",
        "cat6_business_travel",
        "cat7_commuting",
        "cat9_downstream_transport",
        "cat12_eol",
    ] = Field(description="Sub-scope key (must match scope)")

    anno: int = Field(ge=2000, le=2100, description="Reporting year")
    codice_sito: str | None = Field(
        default=None,
        description=(
            "Site code. Required for Scope 1 and Scope 2. "
            "MUST be null/omitted for Scope 3 (corporate-level, not per-site). "
            "Decision 2026-05-15: Scope 3 is corporate-level across the whole group."
        ),
    )
    quantita: Decimal = Field(gt=0, description="Activity quantity (must be > 0)")
    unita: str = Field(
        min_length=1,
        description=(
            "Unit of quantita "
            "(e.g. 'kWh', 'litri', 'Sm3', 'kg', 't', 'EUR', 'km', 'tCO2')"
        ),
    )
    gwp_set: Literal["AR6", "AR5"] = Field(
        default="AR6",
        description="GWP assessment report to use (AR6 = CSRD default, AR5 = EU ETS)",
    )

    # --- Conditional fields (scope/sub_scope dependent) ---

    combustibile: Literal["GAS_NAT", "GASOLIO", "BENZINA"] | None = Field(
        default=None,
        description="Fuel code — required for S1 combustion",
    )
    process_mode: Literal["direct_tco2", "caco3_mass"] | None = Field(
        default=None,
        description=(
            "S1 process mode: "
            "'direct_tco2' (Mode A — quantita is already tCO2, default) or "
            "'caco3_mass' (Mode B — CaCO3 stoichiometric 0.4397 tCO2/t)"
        ),
    )
    strumento_mb: Literal["GO", "PPA", "RESIDUAL"] | None = Field(
        default=None,
        description="Market-based instrument — required for S2 MB",
    )
    sottocategoria: str | None = Field(
        default=None,
        description="Sub-category — required for S3 (e.g. 'Cement', 'imballaggi cartone')",
    )
    metodo: Literal[
        "mass-based",
        "spend-based",
        "distance-based",
        "fuel-based",
    ] | None = Field(
        default=None,
        description="Calculation methodology — required for S3",
    )

    # --- Optional metadata ---
    fonte_dato: str | None = Field(default=None, description="Data source description")
    qualita_dato: str | None = Field(
        default=None,
        description="Data quality tag: 'P' = primary, 'S' = secondary, …",
    )
    note: str | None = Field(default=None, description="Free-text note")

    @model_validator(mode="after")
    def _validate_scope_sub_scope_compatibility(self) -> CalcInputRequest:
        """Validate scope/sub_scope pairing.

        Raises:
            ValueError: When sub_scope does not match scope.
        """
        s1_sub = {"combustion", "process"}
        s2_sub = {"lb", "mb"}
        s3_sub = {
            "cat1_purchased_goods",
            "cat3_fuel_energy",
            "cat4_upstream_transport",
            "cat5_waste",
            "cat6_business_travel",
            "cat7_commuting",
            "cat9_downstream_transport",
            "cat12_eol",
        }
        allowed: dict[int, set[str]] = {1: s1_sub, 2: s2_sub, 3: s3_sub}
        if self.sub_scope not in allowed.get(self.scope, set()):
            raise ValueError(
                f"sub_scope={self.sub_scope!r} is not valid for scope={self.scope}. "
                f"Allowed: {sorted(allowed[self.scope])}"
            )
        return self

    @model_validator(mode="after")
    def _validate_conditional_fields(self) -> "CalcInputRequest":  # noqa: C901 — fan-out validator
        """Enforce scope/sub_scope conditional requirements.

        Raises:
            ValueError: When a required conditional field is absent or
                an implicit constraint (e.g. unita='tCO2' for Mode A) is violated.

        Scope 3 codice_sito rule (decision 2026-05-15):
            "S1 e S2 riusciamo a dettagliarli per ogni sito, S3 è corporate, di
            tutto il gruppo, non per una specifica sede."
            - Scope 3: codice_sito MUST be None → 422 if present.
            - Scope 1/2: codice_sito is REQUIRED → 422 if absent.
        """
        errors: list[str] = []

        if self.scope == 1 and self.sub_scope == "combustion":
            if self.combustibile is None:
                errors.append("combustibile is required for scope=1 sub_scope='combustion'")
            if self.codice_sito is None:
                errors.append(
                    "codice_sito required for Scope 1 sub_scope='combustion'"
                )

        if self.scope == 1 and self.sub_scope == "process":
            if self.codice_sito is None:
                errors.append(
                    "codice_sito required for Scope 1 sub_scope='process' (must be 'IANO')"
                )
            # Validate unit constraint for Mode A (default when process_mode is None)
            effective_mode = self.process_mode or "direct_tco2"
            if effective_mode == "direct_tco2" and self.unita != "tCO2":
                errors.append(
                    "For process_mode='direct_tco2' (Mode A), unita must be 'tCO2'; "
                    f"got unita={self.unita!r}"
                )

        if self.scope == 2 and self.sub_scope == "mb":
            if self.strumento_mb is None:
                errors.append("strumento_mb is required for scope=2 sub_scope='mb'")
            if self.codice_sito is None:
                errors.append("codice_sito is required for scope=2 sub_scope='mb'")

        if self.scope == 2 and self.sub_scope == "lb" and self.codice_sito is None:
            errors.append("codice_sito is required for scope=2 sub_scope='lb'")

        if self.scope == 3:
            if self.sottocategoria is None:
                errors.append("sottocategoria is required for scope=3")
            if self.metodo is None:
                errors.append("metodo is required for scope=3")
            # Decision 2026-05-15: Scope 3 is corporate-level; codice_sito must be null.
            if self.codice_sito is not None:
                errors.append(
                    "Scope 3 is corporate-level, codice_sito must be null"
                )

        if errors:
            raise ValueError("; ".join(errors))

        return self


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class CalcPreviewResponse(BaseModel):
    """Read-only calc trace for a single auto-calc request.

    Returned by POST /api/v1/calc/preview (no DB write) and embedded in
    CalcInsertResponse after a successful POST /api/v1/calc/insert.

    Decimal precision: tco2e and biogenic/fossil columns are Decimal 15,6
    per auto_calc_design.md §9.
    """

    model_config = ConfigDict(frozen=True)

    # Headline result
    tco2e: Decimal = Field(description="Total tCO2e (Decimal 15,6 precision)")
    co2_biogenic_tonne: Decimal | None = Field(
        default=None,
        description=(
            "ADR-007 biogenic CO2 memo (Cat 1 cardboard/pallet); "
            "never netted into tco2e"
        ),
    )
    co2_fossil_tonne: Decimal | None = Field(
        default=None,
        description="ADR-007 fossil CO2 split companion",
    )

    # Factor provenance
    factor_id: str = Field(
        description="Catalog factor ID used (e.g. 'COMB_GAS_NAT_CO2_DEFRA_2025')"
    )
    factor_value: Decimal = Field(description="Numeric factor value applied")
    factor_unit: str = Field(description="Unit of the factor (e.g. 'kg CO2 / kWh')")
    factor_source: str = Field(
        description="Factor provider (e.g. 'DEFRA 2025', 'IPCC', 'ISPRA')"
    )
    factor_version: str = Field(description="Factor version tag")
    factor_vintage: str = Field(
        description="Actual vintage resolved after closest-prior lookup (e.g. '2024')"
    )
    gwp_set: str = Field(description="GWP assessment report used ('AR6' or 'AR5')")
    gwp_value: Decimal | None = Field(
        default=None,
        description="GWP multiplier applied (1.0 for CO2-only factors)",
    )
    methodology: str = Field(
        description=(
            "Methodology tag "
            "(e.g. 'activity-based', 'mass-based', 'stoichiometric')"
        )
    )

    # Calculation trace
    formula_human: str = Field(
        description=(
            "Human-readable formula trace "
            "(e.g. '1000 kWh × 0.18 kgCO2/kWh × 1e-3 = 0.18 tCO2e')"
        )
    )
    unit_conversion_applied: str | None = Field(
        default=None,
        description="Unit conversion description or None if no conversion needed",
    )

    # Non-blocking warnings
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking warnings (e.g. vintage fallback notice)",
    )


class CalcInsertResponse(CalcPreviewResponse):
    """Preview + insert result: extends CalcPreviewResponse with DB identifiers.

    Returned by POST /api/v1/calc/insert (status 201) after the emission row
    has been appended to calc.emissions_consolidated and the audit_log row
    has been written.
    """

    model_config = ConfigDict(frozen=True)

    emission_id: uuid.UUID = Field(
        description="UUID of the newly inserted calc.emissions_consolidated row"
    )
    correlation_id: uuid.UUID = Field(
        description="Request correlation UUID (links to audit_log row)"
    )
    created_at: datetime = Field(
        description="UTC timestamp when the emission row was persisted"
    )
