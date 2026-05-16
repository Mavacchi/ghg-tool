# Factor Sources — Procurement and Loading Guide

**Version**: 1.0.0
**Date**: 2026-05-15
**Owner**: DataEngineerAgent
**Status**: OPERATIONAL — complements methodology.md §13 (factor catalog lifecycle)

This document describes where to obtain each licensed or externally-hosted factor
source, how to verify its integrity, and how to load it into the factor catalog.

---

## 1. Source Inventory

| Source | Factor IDs | File | License | Status |
|--------|-----------|------|---------|--------|
| DEFRA 2024 v1.0 | `COMB_GAS_NAT_*_DEFRA_2024_*`, `COMB_GASOLIO_AUTO_*`, `COMB_BENZINA_AUTO_*` | `defra_2024_ghg_conversion_v1.xlsx` | Open Government Licence v3 | Fixture in repo |
| ISPRA Rapporto 413/2025 | `LB_IT_GRID_ISPRA_2024` | `ispra_413_2025.pdf` | Public — download required | Placeholder (MG-15) |
| AIB ERM 2024 | `MB_IT_RESIDUAL_AIB_2024` | `aib_residual_mix_2024.pdf` | AIB Member — download required | Placeholder (MG-15) |
| Ecoinvent v3.10 | `ECOINV_*_V3_10` | `ecoinvent_v3.10_sample.csv` | Commercial licence required | Sample CSV in repo |

All files live in `data/raw_factor_sources/`.

---

## 2. DEFRA 2024

### Source
Greenhouse Gas Reporting: Conversion Factors 2024 (DESNZ/DBET, June 2024).
Download: https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting

### File committed
`data/raw_factor_sources/defra_2024_ghg_conversion_v1.xlsx`

This is a **minimal fixture** containing 5 key combustion CO2 factors for
GAS_NAT, GASOLIO_AUTO, and BENZINA_AUTO (base per-Sm3/per-litre + NCV-derived
per-kWh variants). It was created from the public DEFRA 2024 spreadsheet.

The full DEFRA 2024 workbook (all categories) is not committed because it is
larger than needed; the fixture covers v1 scope (Scope 1 combustion + NCV
dual-unit decision #3).

### SHA-256 pin
`f2fbf9b592e71dae6b73a0217b7811969e015172fe1b2bba91a31e0f69b81803`
Set in `seed_loader.py::DEFRA_EXCEL_SHA256`.

### NCV references (dual-unit derivation)
Per `auto_calc_design.md §12 #3` and DEFRA 2024 NCV table + IPCC 2006 Vol.2 Ch.1:

| Fuel | NCV | Basis |
|------|-----|-------|
| Gas naturale | 9.59 kWh/Sm³ | @ 15°C, 1 atm, dry basis (DEFRA 2024 NCV table) |
| Gasolio auto | 9.97 kWh/L | density 0.832 kg/L × 42.7 MJ/kg NCV (GHG Protocol EF guide) |
| Benzina auto | 9.20 kWh/L | density 0.741 kg/L × 44.7 MJ/kg NCV (GHG Protocol EF guide) |

Formula: `factor_per_kwh = factor_per_native_unit / NCV_kwh_per_native_unit`

The per-kWh variants are stored as separate factor_ids with the `_PER_KWH`
suffix and `applicability_note` encoding the derivation chain for audit trail.

---

## 3. ISPRA Rapporto 413/2025

### Source
ISPRA — "Le emissioni di CO2 nel settore elettrico", Rapporto 413/2025.
URL: https://emissioni.sina.isprambiente.it/wp-content/uploads/2025/05/Le-emissioni-di-CO2-nel-settore-elettrico_r413-2025_def.pdf

### Why not committed
The PDF is publicly accessible but is not a small fixture file. It is also subject
to ISPRA's website terms. The hash is pinned in code once manually retrieved.

### Steps to load ISPRA
1. Download the PDF from the URL above.
2. Save as `data/raw_factor_sources/ispra_413_2025.pdf`.
3. Run:
   ```bash
   python -m ghg_tool.infrastructure.factors.seed_loader --check-hash ispra
   ```
   This prints the SHA-256 of the file.
4. Set `ISPRA_PDF_SHA256` in `src/ghg_tool/infrastructure/factors/seed_loader.py`
   to the printed hash.
5. Run:
   ```bash
   python -m ghg_tool.infrastructure.factors.seed_loader --apply --skip-pdf
   # Then without --skip-pdf once the hash is set:
   python -m ghg_tool.infrastructure.factors.seed_loader --apply
   ```

### Value extraction
The loader (`parse_ispra_pdf`) reads Table 3 of the PDF and extracts
"Fattore medio di emissione (consumo)" in gCO2eq/kWh, converting to kgCO2eq/kWh.
If the PDF layout changes in a future edition, adjust the regex in `parse_ispra_pdf`.

### Vintage note
ISPRA 413/2025 contains 2023 data. The `vintage = '2024'` row is loaded with
`applicability_note` documenting the offset per `methodology.md §2` and
`auto_calc_design.md §3` (closest-prior rule). `disclosure_notes` on each
emission row will carry the offset statement.

---

## 4. AIB European Residual Mix 2024

### Source
Association of Issuing Bodies (AIB) European Residual Mix 2024.
URL: https://www.aib-net.org/facts/european-residual-mix/2024

### Gate status
MG-15: The AIB PDF returned HTTP 403 during Phase 2 validation (May 2025).
The PDF is expected to be published at the URL above after 2025-05-30.
Until it is available, `MB_IT_RESIDUAL_AIB_2024` remains `is_tbc=TRUE` in
the DB (seeded by migration M2).

### Steps to load AIB
1. Download the PDF from the URL above once available.
2. Save as `data/raw_factor_sources/aib_residual_mix_2024.pdf`.
3. Run:
   ```bash
   python -m ghg_tool.infrastructure.factors.seed_loader --check-hash aib
   ```
4. Set `AIB_PDF_SHA256` in `seed_loader.py`.
5. Run:
   ```bash
   python -m ghg_tool.infrastructure.factors.seed_loader --apply
   ```

### Value extraction
The loader (`parse_aib_pdf`) scans each page for an "Italy" row followed by a
numeric value in kgCO2e/kWh. If the PDF layout differs from the expected pattern,
adjust the regex in `parse_aib_pdf` and document the change in a methodology note.

---

## 5. Ecoinvent v3.10

### License requirement
Ecoinvent is proprietary. A commercial licence is required.
Information: https://ecoinvent.org/licensing/

The factor values `ECOINV_*_V3_10` are seeded in migration M2 as
`is_licence_only = TRUE` with `value = NULL`. The production values must be
loaded from a licensed ecoinvent export.

### Sample CSV (anonymised)
`data/raw_factor_sources/ecoinvent_v3.10_sample.csv` contains 5 rows with
**anonymised / order-of-magnitude values** for testing. These are NOT the
licensed values and MUST NOT be used for any emissions calculation.

SHA-256 pin: `bc48339dafa7d0716b3696d8f09b712a5bbaf98093d5d3847a58e9e6fc8a0039`

### Steps to load licensed Ecoinvent data
1. Obtain an ecoinvent v3.10 licence via https://ecoinvent.org/licensing/.
2. Export the relevant datasets (Clay, Feldspar, Silica sand, Frit, Pigment,
   Additives, Cardboard, Pallets, LDPE film, PP strap, Inert landfill,
   CDW recycling) in CSV format.
3. Format the CSV with the columns expected by `parse_ecoinvent_csv`:
   `material_id, source, value_kgCO2e_per_kg, gwp_set, vintage, methodology, applicability_note`
4. Replace `data/raw_factor_sources/ecoinvent_v3.10_sample.csv` with the
   licensed export.
5. Update `ECOINVENT_CSV_SHA256` in `seed_loader.py`.
6. Run:
   ```bash
   python -m ghg_tool.infrastructure.factors.seed_loader --apply
   ```

### Biogenic split (ADR-007)
`ECOINV_CARDBOARD_V3_10` and `ECOINV_PALLET_V3_10` require the
`biogenic_co2_kg_per_unit` companion field. Add a `biogenic_co2_kg_per_unit`
column to the CSV export and extend `parse_ecoinvent_csv` to map it.
See `methodology.md §12` (ADR-007) and OI-9.

---

## 6. Loading All Seeds

```bash
# Check hashes only (does not touch DB)
python -m ghg_tool.infrastructure.factors.seed_loader --check-hash defra
python -m ghg_tool.infrastructure.factors.seed_loader --check-hash ecoinvent

# List TBC factors still pending pinning
python -m ghg_tool.infrastructure.factors.seed_loader --list-tbc

# Apply all available sources (skip PDF if not yet downloaded)
python -m ghg_tool.infrastructure.factors.seed_loader --apply --skip-pdf

# Apply all sources including PDFs (requires ISPRA + AIB PDFs in raw_factor_sources/)
python -m ghg_tool.infrastructure.factors.seed_loader --apply
```

The loader is idempotent: re-running with the same files produces
`ON CONFLICT DO NOTHING` — no duplicates, no errors.

---

## 7. MinIO Evidence Storage

When `MINIO_ENDPOINT` is set, the loader uploads each source file to MinIO
and stores the URI as `pdf_source_uri` on the factor row for auditor access.

```bash
export MINIO_ENDPOINT=http://localhost:9000
export MINIO_BUCKET=gh-tool-evidence
export MINIO_ACCESS_KEY=minioadmin
export MINIO_SECRET_KEY=minioadmin

python -m ghg_tool.infrastructure.factors.seed_loader --apply --skip-pdf
```

Without `MINIO_ENDPOINT`, `pdf_source_uri` stores the local `file://` path.
This is acceptable for development but not for production (auditors need
the MinIO URI for evidence retrieval).

---

## 8. Security Notes

- Hash pins are committed to the repository. A changed hash is a CI signal
  that a source file has been modified — investigate before proceeding.
- Never commit the real ISPRA or AIB PDFs — they are large and subject to
  third-party terms. Only commit the SHA-256 pins.
- The ecoinvent licensed CSV must NOT be committed to the repository.
  Use MinIO (or another secrets-store-backed object store) for licensed data.
- `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` must be injected via env vars
  (never hardcoded); see `docs/architecture.md` ADR-008.
