"""Pydantic v2 schemas for /go-certificates endpoints (methodology_validation §2.4)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GoCertificateCreate(BaseModel):
    """Payload for ``POST /api/v1/go-certificates``.

    Creates a GO certificate evidence record with all 8 QC booleans required
    by GHG Protocol Scope 2 Quality Criteria (methodology_validation.md §2.4).

    Attributes:
        go_id: GSE unique certificate identifier.
        site_id: UUID FK to ref.sites.
        anno: Reporting year covered.
        volume_mwh: Energy volume in MWh.
        vintage_year: Generation year of the renewable energy.
        cancellation_date: Date of cancellation/redemption.
        beneficiary_legal_entity: Legal entity name on the certificate.
        country_of_issuance: Country code / name of issuing registry.
        technology: Renewable technology type (e.g. 'Solar', 'Wind').
        qc1_conveyed_claim_passed: QC1 — claim conveyed to buyer.
        qc2_unique_passed: QC2 — no double-counting.
        qc3_redeemed_passed: QC3 — certificate is redeemed/cancelled.
        qc4_vintage_passed: QC4 — vintage within acceptable range.
        qc5_geographic_passed: QC5 — geographic market boundary respected.
        qc6_scope_passed: QC6 — Scope 2 attribute coverage confirmed.
        qc7_exclusivity_passed: QC7 — exclusive claim by one entity.
        qc8_residual_mix_disclosed: QC8 — residual mix for non-GO volumes disclosed.
        pdf_evidence_uri: Object-store URI of the GO certificate PDF.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    go_id: str = Field(min_length=1, max_length=80)
    site_id: UUID
    anno: int = Field(ge=2020, le=2099)
    volume_mwh: float = Field(ge=0.0)
    vintage_year: int = Field(ge=2000, le=2100)
    cancellation_date: date
    beneficiary_legal_entity: str = Field(min_length=1, max_length=200)
    country_of_issuance: str = Field(min_length=1, max_length=40)
    technology: str = Field(min_length=1, max_length=40)
    qc1_conveyed_claim_passed: bool
    qc2_unique_passed: bool
    qc3_redeemed_passed: bool
    qc4_vintage_passed: bool
    qc5_geographic_passed: bool
    qc6_scope_passed: bool
    qc7_exclusivity_passed: bool
    qc8_residual_mix_disclosed: bool
    pdf_evidence_uri: str = Field(min_length=1, max_length=512)

    @field_validator("go_id")
    @classmethod
    def validate_go_id_format(cls, v: str) -> str:
        """Ensure go_id is alphanumeric (hyphens and underscores allowed).

        Args:
            v: Raw go_id string.

        Returns:
            Validated go_id string.

        Raises:
            ValueError: If format is invalid.
        """
        clean = v.replace("-", "").replace("_", "")
        if not clean.isalnum():
            raise ValueError("go_id must be alphanumeric (hyphens and underscores allowed)")
        return v

    @model_validator(mode="after")
    def cancellation_after_vintage(self) -> GoCertificateCreate:
        """Cancellation year must be >= vintage year.

        Returns:
            Self if valid.

        Raises:
            ValueError: If cancellation_date.year < vintage_year.
        """
        if self.cancellation_date.year < self.vintage_year:
            raise ValueError("cancellation_date cannot precede vintage_year")
        return self


class GoCertificateResponse(BaseModel):
    """Response schema for a GO certificate evidence record.

    All 8 QC booleans are exposed for auditor inspection (ISAE 3000 evidence).

    Attributes:
        id: Primary key UUID.
        go_id: GSE certificate identifier.
        site_id: Site UUID FK.
        anno: Reporting year.
        volume_mwh: Energy volume in MWh.
        vintage_year: Generation year.
        cancellation_date: Cancellation/redemption date.
        beneficiary_legal_entity: Legal entity on the certificate.
        country_of_issuance: Issuing country.
        technology: Renewable technology type.
        qc1_conveyed_claim_passed through qc8_residual_mix_disclosed: QC results.
        all_qc_passed: Computed — True if all 8 QC booleans are True.
        pdf_evidence_uri: Object-store path.
        validated_by: Username who created/validated this record.
        validated_at: Timestamp of creation/last validation.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    go_id: str
    site_id: UUID
    anno: int
    volume_mwh: float
    vintage_year: int
    cancellation_date: date
    beneficiary_legal_entity: str
    country_of_issuance: str
    technology: str
    qc1_conveyed_claim_passed: bool
    qc2_unique_passed: bool
    qc3_redeemed_passed: bool
    qc4_vintage_passed: bool
    qc5_geographic_passed: bool
    qc6_scope_passed: bool
    qc7_exclusivity_passed: bool
    qc8_residual_mix_disclosed: bool
    pdf_evidence_uri: str
    validated_by: str
    validated_at: datetime

    @property
    def all_qc_passed(self) -> bool:
        """Return True if all 8 QC booleans are True (MG-03 gate).

        Returns:
            Boolean AND of all QC fields.
        """
        return all([
            self.qc1_conveyed_claim_passed,
            self.qc2_unique_passed,
            self.qc3_redeemed_passed,
            self.qc4_vintage_passed,
            self.qc5_geographic_passed,
            self.qc6_scope_passed,
            self.qc7_exclusivity_passed,
            self.qc8_residual_mix_disclosed,
        ])


class GoValidationPatch(BaseModel):
    """Payload for ``PATCH /api/v1/go-certificates/{go_id}/validate``.

    Appends a new validation version row (append-only pattern) with updated
    QC checks and a new ``validated_at`` timestamp.

    Attributes:
        qc1_conveyed_claim_passed through qc8_residual_mix_disclosed: Updated QC checks.
        pdf_evidence_uri: Updated evidence URI if the PDF has been replaced.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    qc1_conveyed_claim_passed: bool | None = None
    qc2_unique_passed: bool | None = None
    qc3_redeemed_passed: bool | None = None
    qc4_vintage_passed: bool | None = None
    qc5_geographic_passed: bool | None = None
    qc6_scope_passed: bool | None = None
    qc7_exclusivity_passed: bool | None = None
    qc8_residual_mix_disclosed: bool | None = None
    pdf_evidence_uri: str | None = Field(default=None, max_length=512)


class GoFilter(BaseModel):
    """Query parameters for ``GET /api/v1/go-certificates``.

    Attributes:
        site_id: Filter by site UUID.
        anno: Filter by reporting year.
        all_qc_passed: Filter to only fully-validated certificates.
        cursor: Pagination cursor.
        limit: Page size (1–200, default 50).
    """

    model_config = ConfigDict(extra="forbid")

    site_id: UUID | None = None
    anno: int | None = Field(default=None, ge=2020, le=2099)
    all_qc_passed: bool | None = None
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
