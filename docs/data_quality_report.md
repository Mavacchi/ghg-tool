# Data Quality Report — GHG Accounting Tool

---

## 0. Document Control

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Date | 2026-05-13 |
| Author | data-quality-agent |
| Status | ISSUED — Phase 3 output |
| References | `docs/requirements.md` v1.2.0 (APPROVED); `docs/methodology_validation.md` v1.0.0 |
| Input files | `data/raw/scope1_combustione.csv`, `data/raw/scope2_elettricita.csv`, `data/raw/scope3_categorie.csv` |
| Libraries | Python 3 stdlib `csv`, `io`, `math` (pandas not required; stdlib sufficient for row counts analysed) |
| Next review | Before Phase 5 kick-off |

---

## 1. Executive Summary

### 1.1 Native Row Counts

| CSV | Raw data rows (parsed by DictReader, semicolon-delimited) | Declared in requirements.md |
|---|---|---|
| `scope1_combustione.csv` | **31** | 32 |
| `scope2_elettricita.csv` | **15** | 15 (native) + 1 ETL-synthesised |
| `scope3_categorie.csv` | **100** | 101 |

Row-count discrepancies are a direct DQ finding (see §3 and §6). The `scope1_combustione.csv` is short by exactly 1 row (VIANO_GARGOLA GAS_NAT 2024, absent). The `scope3_categorie.csv` is short by 1 relative to the declared count of 101; the count of 100 is arithmetically confirmed across all categories and years. The requirements.md figure of 101 may be an off-by-one in documentation, or the Cat 1 2024 count of "15 records" is overstated by 1 (actual: 14).

### 1.2 Findings Summary

| Severity | Count |
|---|---|
| DQ-CRIT | **4** |
| DQ-WARN | **8** (1 RESOLVED — DQ-WARN-05) |
| INFO (no block) | **4** |
| **Total** | **16** |

### 1.3 Phase 5 Readiness Verdict

**Phase 5 is BLOCKED.** Four DQ-CRIT findings trigger the block condition per requirements.md §11:

- **DQ-CRIT-01**: VIANO_GARGOLA GAS_NAT 2024 absent — facility coverage < 7/7 for GAS_NAT 2024.
- **DQ-CRIT-02**: 10 Cat 3 rows in `scope3_categorie.csv` have blank mandatory metadata (Fonte_Dato, Qualità_Dato, Stato_Dato empty for all WTT/T&D rows).
- **DQ-CRIT-04**: VIANO_GARGOLA GAS_NAT 2025 = 11 Sm³ (pre-flagged in requirements) confirmed as extreme outlier by ratio test (reference population 2024 absent; the value is also anomalous vs all other sites in 2025).
- **DQ-CRIT-05**: VIANO_GARGOLA GAS_NAT temporal gap — present in 2025 with no corresponding 2024 record and no explicit zero.

Additionally, DQ-WARN-01 (VIANO EE_Acquistata_GO 2025 ratio = 0.499, pre-registered) is confirmed. It does not independently block Phase 5 but reinforces a systemic VIANO 2025 data completeness risk that must be investigated before 2025 consolidated figures are signed off.

---

## 2. Coverage Analysis

### 2.1 Declared Organisational Perimeter

7 sites: IANO, VIANO, VIANO_GARGOLA, CASALGRANDE, FIORANO, SASSUOLO, FRASSINORO. Boundary method: Operational Control.

### 2.2 Scope 1 Site Coverage Matrix — GAS_NAT (Sm³)

| Site | 2024 | 2025 | Status |
|---|---|---|---|
| IANO | 22,916,841 | 23,556,856 | OK |
| VIANO | 4,569,554 | 1,925,606 | WARN (ratio 0.421) |
| VIANO_GARGOLA | **ABSENT** | 11 | **DQ-CRIT-01 + DQ-CRIT-05** |
| CASALGRANDE | 2,738 | 3,901 | OK |
| FIORANO | 15,211 | 18,388 | OK |
| SASSUOLO | 10,632 | 11,464 | OK |
| FRASSINORO | 5,634,446 | 6,336,992 | OK |
| **Coverage** | **6/7 = 85.7%** | 7/7 = 100% | **CRIT 2024** |

VIANO_GARGOLA GAS_NAT 2024 is absent from the CSV. The requirement states 7 records/2024 for GAS_NAT; only 6 are present. This triggers **DQ-CRIT-01** (facility coverage < 7/7) and **DQ-CRIT-05** (temporal gap: site present in 2025 with a value but absent in 2024 without explicit zero record).

### 2.3 Scope 1 Site Coverage Matrix — GASOLIO (litri)

| Site | 2024 | 2025 | Status |
|---|---|---|---|
| IANO | 110,000 | 109,992 | OK |
| VIANO | 44,600 | 22,000 | WARN (ratio 0.493) |
| VIANO_GARGOLA | 2,400 | 2,400 | OK |
| CASALGRANDE | 13,000 | 11,000 | OK |
| FIORANO | 58,000 | 74,400 | OK |
| SASSUOLO | 95,268 | 95,056 | OK |
| FRASSINORO | 18,000 | 20,000 | OK |
| **Coverage** | 7/7 = 100% | 7/7 = 100% | OK |

### 2.4 Scope 1 Site Coverage Matrix — BENZINA (litri, SASSUOLO only)

| Site | 2024 | 2025 | Status |
|---|---|---|---|
| SASSUOLO | 1,349 | 9,151 | WARN (ratio 6.78×) |
| Coverage (structural) | 1/1 = 100% | 1/1 = 100% | OK structural |

BENZINA is structurally SASSUOLO-only per requirements.md §6.1 (confirmed by requirements note). Coverage is 100% of the structural perimeter. The 6.78× YoY increase is a new anomaly not pre-flagged, requiring investigation (see §5).

### 2.5 Scope 1 Site Coverage Matrix — PROCESSO_DECARB (kg CaCO₃, IANO only)

| Site | 2024 | 2025 | Status |
|---|---|---|---|
| IANO | 9,363,616 | 9,061,067 | OK |
| Coverage (structural) | 1/1 = 100% | 1/1 = 100% | OK |

PROCESSO_DECARB is structurally IANO-only. Ratio 2025/2024 = 0.968 (−3.2%). Within normal bounds.

### 2.6 Scope 2 Site Coverage Matrix

| Site | GO 2024 (kWh) | GO 2025 (kWh) | Grid 2024 (kWh) | Grid 2025 (kWh) | Status |
|---|---|---|---|---|---|
| IANO | 3,193,698 | 3,195,741 | — | — | OK |
| VIANO | 6,551,604 | 3,268,364 | — | — | WARN (DQ-WARN-01) |
| VIANO_GARGOLA | 159,518 | 154,856 | — | — | OK |
| CASALGRANDE | 358,307 | 336,654 | — | — | OK |
| FIORANO | 344,808 | 375,142 | — | — | OK |
| SASSUOLO | 377,358 | 421,065 | 46,786 | 0* | OK (SASSUOLO Grid 2025: ETL-synthesised zero per DQ-WARN-05 RESOLVED) |
| FRASSINORO | 8,716,707 | 9,472,090 | — | — | OK |
| **GO Coverage** | 7/7 = 100% | 7/7 = 100% | — | — | OK |

*SASSUOLO Grid 2025 = 0 kWh, user-confirmed full-GO contract switch 2026-05-13. ETL inserts explicit zero row with provenance flag `auto_zero_user_confirmed`. No DQ-CRIT-05 fires for this case per DQ-WARN-05 RESOLVED.

SASSUOLO 2024 Grid = 46,786 kWh is **confirmed present** in the native CSV (row 8 of `scope2_elettricita.csv`, Fonte_Dato = Fattura fornitore, Qualità_Dato = P, Stato_Dato = Definitivo).

### 2.7 Scope 3 Category Coverage

| Category | 2024 rows | 2025 rows | Subcategories 2024 | Subcategories 2025 | Status |
|---|---|---|---|---|---|
| Cat 1 — Purchased goods | 14 | 14 | 14 | 14 | OK (req. declares 15/14; actual 14/14 — see INFO-01) |
| Cat 2 — Capital goods | 2 | 2 | 2 | 2 | OK |
| Cat 3 — WTT + T&D | 5 | 5 | 5 | 5 | WARN (metadata blank — see §3) |
| Cat 4 — Upstream transport | 16 | 16 | 16 | 16 | OK (incl. 2 zero-tkm rows per year) |
| Cat 5 — Waste | 4 | 4 | 4 | 4 | OK |
| Cat 6 — Business travel | 3 | 3 | 3 | 3 | OK |
| Cat 7 — Commuting | 1 | 1 | 1 | 1 | OK |
| Cat 9 — Downstream transport | 3 | 3 | 3 | 3 | OK |
| Cat 12 — End-of-life | 2 | 2 | 2 | 2 | OK |
| **Total** | **50** | **50** | — | — | — |

All 9 in-scope categories are present in both years. Subcategories are symmetric 2024/2025 for all categories.

---

## 3. Completeness and Missingness

### 3.1 Mandatory Column NULL Scan

**`scope1_combustione.csv`**: All mandatory columns (Scope, Anno, Codice_Sito, Categoria_S1, Combustibile, Quantità, Unità) are non-null and non-empty across all 31 parsed rows. No DQ-CRIT-02 trigger from null scan alone.

**`scope2_elettricita.csv`**: All mandatory columns (Scope, Anno, Codice_Sito, Voce_S2, Quantità, Unità) are non-null and non-empty across all 15 native rows. No DQ-CRIT-02 trigger.

**`scope3_categorie.csv`**: Mandatory structural columns (Scope, Anno, Categoria_S3, Sottocategoria, Quantità, Unità) are non-null across all 100 parsed rows. **However**, the metadata columns Fonte_Dato, Qualità_Dato, and Stato_Dato are **blank in all 10 Cat 3 rows** (both WTT fuel rows and WTT/T&D electricity rows for both years). These rows end with `;;;;` in the raw file.

### 3.2 Cat 3 Metadata Blank Fields — DQ-CRIT-02

**DQ-CRIT-02 fires** for the 10 Cat 3 rows that are missing Fonte_Dato, Qualità_Dato, and Stato_Dato. These are metadata fields that are mandatory per requirements.md §11 DQ gate definitions (mandatory columns include data-lineage fields needed for FR-22 audit trail). Specific rows affected:

| Row | Anno | Sottocategoria | Combustibile | Missing fields |
|---|---|---|---|---|
| S3/91 | 2024 | WTT Gas Naturale | GAS_NAT | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/92 | 2024 | WTT Gasolio | GASOLIO | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/93 | 2024 | WTT Benzina | BENZINA | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/94 | 2025 | WTT Gas Naturale | GAS_NAT | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/95 | 2025 | WTT Gasolio | GASOLIO | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/96 | 2025 | WTT Benzina | BENZINA | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/97 | 2024 | WTT Elettricità (generazione) | — | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/98 | 2024 | T&D Losses Elettricità | — | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/99 | 2025 | WTT Elettricità (generazione) | — | Fonte_Dato, Qualità_Dato, Stato_Dato |
| S3/100 | 2025 | T&D Losses Elettricità | — | Fonte_Dato, Qualità_Dato, Stato_Dato |

**Remark**: Cat 3 rows are informational inputs; the FR-11 rule states Σ Scope 1 is the source of truth for WTT calculations, not these rows. Nevertheless the blank metadata constitutes a DQ-CRIT-02 under the strict gate definition and must be remediated before Phase 5 ingestion. Recommended fix: populate Fonte_Dato = "Derivato da Scope 1/Scope 2", Qualità_Dato = "D" (Derivato), Stato_Dato = "Definitivo".

### 3.3 Missing % per Column

| File | Column | Blank count | Total rows | % missing |
|---|---|---|---|---|
| scope3_categorie.csv | Fonte_Dato | 10 | 100 | 10.0% |
| scope3_categorie.csv | Qualità_Dato | 10 | 100 | 10.0% |
| scope3_categorie.csv | Stato_Dato | 10 | 100 | 10.0% |
| scope1_combustione.csv | Note | ~27 | 31 | ~87% (optional field, no gate) |
| scope2_elettricita.csv | Note | ~14 | 15 | ~93% (optional field, no gate) |
| scope3_categorie.csv | Note | ~varied | 100 | optional field, no gate |

All other mandatory columns: 0% missing.

---

## 4. Sign Validation

### 4.1 Negative Values

**No negative Quantità values found** across any of the three CSVs. DQ-CRIT-03 does **not** trigger.

### 4.2 Zero-Quantity Rows

Exactly **4 zero-quantity rows** found, all in `scope3_categorie.csv`:

| Row | Anno | Categoria_S3 | Sottocategoria | Quantità | Unità | Source | Note |
|---|---|---|---|---|---|---|---|
| S3/1 | 2024 | 4 | Feldspati_Treno | 0 | tkm | Dichiarazione fornitore | "0 km" |
| S3/2 | 2024 | 4 | Sabbie silicee_Treno | 0 | tkm | Dichiarazione fornitore | "0 km" |
| S3/3 | 2025 | 4 | Feldspati_Treno | 0 | tkm | Dichiarazione fornitore | "0 km" |
| S3/4 | 2025 | 4 | Sabbie silicee_Treno | 0 | tkm | Dichiarazione fornitore | "0 km" |

**Verdict**: These are the exact zero-tkm rows specified in requirements.md §6.3 ("Feldspati_Treno and Sabbie silicee_Treno are present in both years with Quantità = 0 tkm"). They are **legitimate explicit-zero disclosures** per FR-12 and must not be filtered. Fonte_Dato = "Dichiarazione fornitore", Note = "0 km" confirm intentional absence of rail transport. **No other zeros exist** in the dataset. DQ-CRIT-03 sign check passes. Cat 4 zero-tkm validation per §8 is fully satisfied.

---

## 5. Outlier Detection

### 5.1 Methodology

With only 2 years of data per (site × fuel) tuple, the population is 2 points. Z-score of the minority year = ±1.000 by construction (both points are equally far from the 2-point mean), so the z-score gate alone cannot discriminate. Accordingly this assessment applies the **ratio test** as the primary operative heuristic per task specification: ratio_yoy = value_2025 / value_2024. Flag at ratio < 0.6 (−40% or worse) or ratio > 1.67 (+67% or more).

### 5.2 Scope 1 Outliers Detected

**VIANO_GARGOLA GAS_NAT 2025 = 11 Sm³ (pre-flagged, DQ-CRIT-04)**

This is the pre-identified anomaly from requirements.md §6.1 and OI-2. The 2024 value is absent (DQ-CRIT-05), making a ratio test impossible. The 11 Sm³ value is contextually extreme: all other sites consuming GAS_NAT in 2025 range from 3,901 Sm³ (CASALGRANDE) to 23,556,856 Sm³ (IANO). VIANO_GARGOLA's 2025 GAS_NAT is 355 times lower than the next smallest non-VIANO_GARGOLA consumer (CASALGRANDE 3,901 Sm³). Cross-site z-score (VIANO_GARGOLA vs 6-site 2025 GAS_NAT population): mean ≈ 5,407,601 Sm³, std ≈ 8,590,540 Sm³, z ≈ −0.629 — not triggering numerically, but the absolute value of 11 Sm³ for an industrial kiln site is physically implausible. DQ-CRIT-04 fires on the contextual heuristic ground. Investigation required: possible meter reset, partial month reading, or data entry error.

**VIANO GAS_NAT 2025 / 2024 ratio = 0.421 (−57.9%)**

| Site | 2024 (Sm³) | 2025 (Sm³) | Ratio | Flag |
|---|---|---|---|---|
| VIANO | 4,569,554 | 1,925,606 | 0.421 | DQ-WARN (ratio < 0.6) |

This is a new finding beyond the pre-flagged anomalies. A 57.9% decline in natural gas consumption at VIANO is consistent with the concurrent electricity and diesel reductions at the same site (see pattern analysis below). Investigated jointly under VIANO site pattern — see §5.4.

**SASSUOLO BENZINA 2025 / 2024 ratio = 6.784 (+578%)**

| Site | 2024 (litri) | 2025 (litri) | Ratio | Flag |
|---|---|---|---|---|
| SASSUOLO | 1,349 | 9,151 | 6.784 | DQ-WARN (ratio > 1.67) |

New finding not pre-flagged. A 6.78× increase in petrol consumption at SASSUOLO is significant in percentage terms but modest in absolute terms (7,802 extra litres). Possible explanations: fleet composition change, acquisition of petrol vehicle, reclassification of previously unrecorded fuel, or data error. Requires data-steward investigation.

**VIANO GASOLIO 2025 / 2024 ratio = 0.493 (−50.7%)**

| Site | 2024 (litri) | 2025 (litri) | Ratio | Flag |
|---|---|---|---|---|
| VIANO | 44,600 | 22,000 | 0.493 | DQ-WARN (ratio < 0.6) |

Consistent with the VIANO site-wide energy reduction pattern.

### 5.3 Scope 2 Outliers Detected

**VIANO EE_Acquistata_GO 2025 / 2024 ratio = 0.499 (−50.1%) — DQ-WARN-01**

Pre-registered finding, confirmed exactly. Value 2024 = 6,551,604 kWh; value 2025 = 3,268,364 kWh. Ratio = 0.499. Trigger threshold ratio < 0.6 met. This is DQ-WARN-01 per requirements.md §11.

All other sites show normal variations (ratios 0.940–1.116) with no ratio flag.

### 5.4 VIANO Site Pattern — Cross-Energy Analysis

The three independent energy streams at VIANO all show comparable reductions in 2025:

| Energy type | 2024 | 2025 | Ratio |
|---|---|---|---|
| GAS_NAT (Sm³) | 4,569,554 | 1,925,606 | 0.421 |
| GASOLIO (litri) | 44,600 | 22,000 | 0.493 |
| EE_Acquistata_GO (kWh) | 6,551,604 | 3,268,364 | 0.499 |

All three show approximately 50–58% reductions. The correlated nature of these drops across all energy carriers at VIANO strongly suggests either: (a) a major production reduction or site shutdown during part of 2025, or (b) incomplete 2025 data ingestion (OI-2 open issue). This pattern reinforces the OI-2 concern: if VIANO operated for only approximately half of 2025, the 2025 corporate total across all scopes will be materially understated. The data-quality-agent escalates this as a systemic risk to ComplianceAgent and OrchestratorAgent: the 2025 VIANO data should not be used in any consolidated 2025 total until the data steward has confirmed completeness.

---

## 6. Temporal Gap Analysis

### 6.1 Scope 1 — Temporal Gaps

| Fuel | Sites in 2024 only | Sites in 2025 only | Verdict |
|---|---|---|---|
| GAS_NAT | — | VIANO_GARGOLA | **DQ-CRIT-05** — VIANO_GARGOLA present in 2025 (11 Sm³) but absent in 2024 with no explicit zero record |
| GASOLIO | — | — | OK — symmetric 7/7 both years |
| BENZINA | — | — | OK — SASSUOLO only, both years |
| PROCESSO_DECARB | — | — | OK — IANO only, both years |

**DQ-CRIT-05 fires** for VIANO_GARGOLA GAS_NAT 2024 absent. No explicit zero record exists for 2024. Requirements.md §11 DQ-CRIT-05 definition: "site present in 2024 but absent in 2025 (or vice versa) without explicit zero-quantity record". The converse direction (absent 2024, present 2025) applies equally. The data steward must either supply the 2024 VIANO_GARGOLA GAS_NAT value or insert an explicit zero row with rationale (e.g. "site commenced GAS_NAT consumption in 2025; 2024 = 0 Sm³") before Phase 5 can proceed.

This gap also causes the **Scope 1 GAS_NAT 2024 site coverage = 6/7 = 85.7%**, triggering **DQ-CRIT-01**.

### 6.2 Scope 2 — Temporal Gaps

| Voce_S2 | Sites in 2024 only | Sites in 2025 only | Verdict |
|---|---|---|---|
| EE_Acquistata_GO | — | — | OK — 7/7 both years |
| EE_Acquistata_Grid | SASSUOLO | — | DOCUMENTED EXCEPTION — DQ-WARN-05 RESOLVED. ETL synthesises explicit zero row for SASSUOLO 2025 with provenance flag `auto_zero_user_confirmed`. No DQ-CRIT-05 fires. |

**EE_Acquistata_Grid gap for SASSUOLO 2025 is the documented exception**. All other Scope 2 combinations are symmetric.

### 6.3 Scope 3 — Temporal Gaps

All 9 categories present in both years with identical subcategory sets. No temporal gaps in Scope 3.

---

## 7. Cat 3 vs Scope 1 Reconciliation (FR-11 / OI-2 / MG-05)

### 7.1 Reconciliation Results — All Fuels

| Fuel / Energy | Year | Σ Scope 1 (source of truth) | Cat 3 CSV Quantità | Delta | Delta % | Verdict |
|---|---|---|---|---|---|---|
| GAS_NAT | 2024 | 33,149,422 Sm³ | 33,149,422 Sm³ | 0 | 0.0% | **PERFECT MATCH** |
| GAS_NAT | 2025 | 31,853,218 Sm³ | 31,853,218 Sm³ | 0 | 0.0% | **PERFECT MATCH** |
| GASOLIO | 2024 | 341,268 litri | 341,268 litri | 0 | 0.0% | **PERFECT MATCH** |
| GASOLIO | 2025 | 334,848 litri | 334,848 litri | 0 | 0.0% | **PERFECT MATCH** |
| BENZINA | 2024 | 1,349 litri | 1,349 litri | 0 | 0.0% | **PERFECT MATCH** |
| BENZINA | 2025 | 9,151 litri | 9,151 litri | 0 | 0.0% | **PERFECT MATCH** |
| Elettricità (WTT) | 2024 | 19,748,786 kWh (Σ Scope 2) | 19,748,786 kWh | 0 | 0.0% | **PERFECT MATCH** |
| Elettricità (WTT) | 2025 | 17,223,912 kWh (Σ Scope 2) | 17,223,912 kWh | 0 | 0.0% | **PERFECT MATCH** |
| Elettricità (T&D) | 2024 | 19,748,786 kWh | 19,748,786 kWh | 0 | 0.0% | **PERFECT MATCH** |
| Elettricità (T&D) | 2025 | 17,223,912 kWh | 17,223,912 kWh | 0 | 0.0% | **PERFECT MATCH** |

### 7.2 Reconciliation vs Requirements.md §FR-11 Cited Figures

Requirements.md §FR-11 cites: "GAS_NAT 2024: CSV Cat 3 = 33,149,422 Sm³ vs Σ Scope 1 = 28,149,392 Sm³, delta +18%". This referenced a **prior version of the Scope 1 data**. In the current CSV files, Σ Scope 1 GAS_NAT 2024 = 33,149,422 Sm³ — identical to Cat 3 CSV. The 18% delta no longer exists in the current dataset. This is logged here as **INFO-02** for audit trail completeness. The reconciliation "delta logging" requirement (FR-11) is satisfied: the delta is 0 for all fuels and years.

**Important caveat**: the VIANO_GARGOLA 2024 GAS_NAT row is missing. If it eventually turns out VIANO_GARGOLA consumed material GAS_NAT in 2024, then Σ Scope 1 GAS_NAT 2024 would increase and Cat 3 WTT GAS_NAT 2024 would need to be recalculated. The Cat 3 CSV value of 33,149,422 may itself be incomplete for 2024.

### 7.3 Scope 2 LB Basis Reconciliation

Σ Scope 2 kWh 2024 = 19,748,786 kWh (19,702,000 GO + 46,786 Grid). Cat 3 WTT Elettricità and T&D rows both record 19,748,786 kWh. Perfect match.

Σ Scope 2 kWh 2025 = 17,223,912 kWh (all GO; SASSUOLO Grid = 0 per user confirmation). Cat 3 WTT and T&D 2025 both record 17,223,912 kWh. Perfect match, and the ETL zero-synthesis for SASSUOLO Grid 2025 is correctly reflected in the Cat 3 totals.

---

## 8. Cat 4 Zero-Tkm Validation

### 8.1 Confirmation

The zero-quantity rows in Cat 4 are exclusively:

- `Feldspati_Treno` — 2024: 0 tkm; 2025: 0 tkm
- `Sabbie silicee_Treno` — 2024: 0 tkm; 2025: 0 tkm

These 4 rows (2 subcategories × 2 years) are the only zeros in Cat 4, and they match precisely the expected entries per requirements.md §6.3 and FR-12. All other 28 Cat 4 rows have non-zero quantities.

### 8.2 Explicit-Zero Evidence

Both zero rows carry:
- `Fonte_Dato = "Dichiarazione fornitore"` (supplier declaration)
- `Qualità_Dato = "S"` (Supplier-declared)
- `Stato_Dato = "Definitivo"`
- `Note = "0 km"`

This is compliant with FR-12 ("zero-tkm rows produce explicit 0.0 tCO2e; not NULL"). No suspicious zeros detected in Cat 4.

### 8.3 Cat 4 Non-Zero Distribution

For the 28 non-zero Cat 4 rows (combined 2024 and 2025):

| Metric | Value |
|---|---|
| Minimum | 19,676 tkm (Reggette PP_Strada 2024) |
| Median | 9,243,551 tkm |
| Maximum | 76,115,538 tkm (Argille_Nave 2024) |

No Cat 4 non-zero value appears implausible given the bulk-mineral transport context of a ceramic manufacturer.

---

## 9. Cross-CSV Consistency

### 9.1 Codice_Sito Values

All `Codice_Sito` values in `scope1_combustione.csv` and `scope2_elettricita.csv` are members of the declared 7-site perimeter. No unknown sites detected.

### 9.2 Anno Values

All `Anno` values in all three CSVs are either "2024" or "2025". No outlier years.

### 9.3 Scope Field Values

All rows in `scope1_combustione.csv` have Scope = "1". All rows in `scope2_elettricita.csv` have Scope = "2". All rows in `scope3_categorie.csv` have Scope = "3". No cross-contamination.

### 9.4 Voce_S2 Taxonomy

All `Voce_S2` values in `scope2_elettricita.csv` are members of {EE_Acquistata_GO, EE_Acquistata_Grid}. No unknown values.

### 9.5 Categoria_S3 Values

Categories present in `scope3_categorie.csv`: {1, 2, 3, 4, 5, 6, 7, 9, 12}. All are members of the allowed range 1–15. Expected in-scope categories per requirements.md §6.3 (1, 2, 3, 4, 5, 6, 7, 9, 12): all 9 confirmed present in both years. No unexpected categories.

### 9.6 Combustibile Taxonomy

Values present in `scope1_combustione.csv`: {GAS_NAT, GASOLIO, BENZINA, PROCESSO_DECARB}. All consistent with the documented categorical taxonomy per §6.1.

Values in `scope3_categorie.csv` Cat 3 fuel column: {GAS_NAT, GASOLIO, BENZINA, ""} — the empty string applies to electricity rows where Combustibile is not applicable. Consistent.

### 9.7 Units Consistency

| File | Units observed | Assessment |
|---|---|---|
| scope1_combustione.csv | Sm³, litri, kg CaCO₃ | Correct — Sm³ for gas, litri for liquid fuels, kg CaCO₃ for decarbonation |
| scope2_elettricita.csv | kWh | Correct — single unit for electricity, no MWh/GJ ambiguity |
| scope3_categorie.csv | tkm, km, EUR, t, litri, kWh, Sm³ | All appropriate per category and method type |

No ambiguous or mixed unit-of-measure anomalies detected. No MWh/kWh confusion in Scope 2. No kg/t confusion in Scope 3 Cat 1 (mass-based) or Cat 5 (waste). Units are unambiguous per category.

---

## 10. Numeric Summaries

### 10.1 Scope 1 — Totals by Fuel and Year

| Fuel | Unit | 2024 total | 2025 total | YoY change | N sites 2024 | N sites 2025 |
|---|---|---|---|---|---|---|
| GAS_NAT | Sm³ | 33,149,422 | 31,853,218 | −3.9% | 6 | 7 |
| GASOLIO | litri | 341,268 | 334,848 | −1.9% | 7 | 7 |
| BENZINA | litri | 1,349 | 9,151 | +578% | 1 | 1 |
| PROCESSO_DECARB | kg CaCO₃ | 9,363,616 | 9,061,067 | −3.2% | 1 | 1 |

Distribution highlights (GAS_NAT 2024, 6 sites): min = 2,738 Sm³ (CASALGRANDE), median = 12,921 Sm³ (avg SASSUOLO+FIORANO), max = 22,916,841 Sm³ (IANO). IANO is dominant (69.1% of 2024 GAS_NAT total).

Distribution highlights (GASOLIO 2024, 7 sites): min = 2,400 L (VIANO_GARGOLA), median = 44,600 L (VIANO), max = 110,000 L (IANO).

### 10.2 Scope 2 — Totals by Voce and Year

| Voce | Unit | 2024 total | 2025 total (native) | 2025 total (incl ETL zero) | YoY (incl ETL) |
|---|---|---|---|---|---|
| EE_Acquistata_GO | kWh | 19,702,000 | 17,223,912 | 17,223,912 | −12.6% |
| EE_Acquistata_Grid | kWh | 46,786 | 0 (native absent) | 0 (ETL zero) | −100% (confirmed) |
| **Total LB** | **kWh** | **19,748,786** | — | **17,223,912** | **−12.8%** |

FRASSINORO is the largest electricity consumer: 8,716,707 kWh (2024) and 9,472,090 kWh (2025), representing 44.2% and 55.0% of total GO consumption in respective years.

Distribution highlights (EE_GO 2024, 7 sites): min = 159,518 kWh (VIANO_GARGOLA), median = 377,358 kWh (SASSUOLO), max = 8,716,707 kWh (FRASSINORO).

### 10.3 Scope 3 — Totals by Category and Year (selected)

| Category | Subcategory / type | 2024 | 2025 | Unit | YoY |
|---|---|---|---|---|---|
| Cat 1 mass-based | Total mass raw materials | 283,171 | 276,617 | t | −2.3% |
| Cat 1 spend-based | Total services spend | 53,607,851 | 49,145,227 | EUR | −8.3% |
| Cat 2 spend-based | Capital goods + consumables | 15,166,188 | 5,955,165 | EUR | −60.7% |
| Cat 3 | WTT GAS_NAT | 33,149,422 | 31,853,218 | Sm³ | −3.9% |
| Cat 3 | Electricity (WTT + T&D) | 19,748,786 | 17,223,912 | kWh | −12.8% |
| Cat 4 | Total non-zero tkm | 216,066,180 | 224,093,443 | tkm | +3.7% |
| Cat 5 | Total waste | 6,373 | 4,779 | t | −25.0% |
| Cat 6 | Total business travel | 356,488 | 382,776 | EUR | +7.4% |
| Cat 7 | Commuting distance | 4,452,800 | 4,259,200 | km | −4.3% |
| Cat 9 | Total downstream tkm | 340,816,616 | 353,143,516 | tkm | +3.6% |
| Cat 12 | Total EoL tiles | 263,376 | 249,240 | t | −5.4% |

Cat 2 capital goods spend drops 60.7% YoY (2024: 13,103,478 EUR Impiantistica; 2025: 3,903,979 EUR). This is a notable year-over-year change in spend-based categories. It is flagged as **INFO-03** (informational; spend-based categories inherently volatile; no Cat 2 gate rule). Data steward should confirm this reflects actual capex reduction, not incomplete data.

Cat 5 non-pericolosi da riciclo drops from 5,990 t (2024) to 4,313 t (2025), a 28.0% decline. Consistent with the VIANO production reduction hypothesis. Flagged as **INFO-04**.

---

## 11. Findings Catalogue

```json
[
  {
    "rule_id": "DQ-CRIT-01",
    "severity": "CRIT",
    "scope": "Scope 1",
    "site": "VIANO_GARGOLA",
    "year": 2024,
    "metric": "GAS_NAT coverage",
    "detail": "VIANO_GARGOLA GAS_NAT 2024 record absent. Scope 1 GAS_NAT 2024 site coverage = 6/7 = 85.7%, below the 7/7 (100%) threshold required by DQ-CRIT-01. Total rows in scope1_combustione.csv = 31, not 32 as declared in requirements.md.",
    "value_2024": null,
    "value_2025": 11,
    "ratio_yoy": null,
    "trigger": "coverage < 7/7 (100%) for GAS_NAT 2024",
    "recommended_action": "Data steward to supply VIANO_GARGOLA GAS_NAT 2024 actual value from billing records, or insert explicit zero row with rationale if consumption was genuinely zero in 2024. ETL must not proceed with incomplete 2024 GAS_NAT data.",
    "blocks_phase_5": true
  },
  {
    "rule_id": "DQ-CRIT-02",
    "severity": "CRIT",
    "scope": "Scope 3",
    "site": null,
    "year_pair": [2024, 2025],
    "metric": "Cat 3 metadata fields",
    "detail": "All 10 Cat 3 rows (WTT Gas Naturale, WTT Gasolio, WTT Benzina, WTT Elettricita, T&D Losses for both years) have blank Fonte_Dato, Qualita_Dato, and Stato_Dato. These are mandatory audit-trail metadata fields per FR-22 / CG-04. Blank metadata breaks the row-to-source traceability chain required for ISAE 3000 Limited assurance.",
    "affected_rows": 10,
    "missing_fields": ["Fonte_Dato", "Qualita_Dato", "Stato_Dato"],
    "trigger": "mandatory column empty for 10 rows",
    "recommended_action": "Data steward to populate: Fonte_Dato='Derivato da Scope 1/Scope 2', Qualita_Dato='D', Stato_Dato='Definitivo' for all 10 Cat 3 rows. These are derived reference quantities, not primary activity data, so the source is the Scope 1 and Scope 2 CSVs.",
    "blocks_phase_5": true
  },
  {
    "rule_id": "DQ-CRIT-04",
    "severity": "CRIT",
    "scope": "Scope 1",
    "site": "VIANO_GARGOLA",
    "year": 2025,
    "metric": "GAS_NAT Sm3",
    "value_2024": null,
    "value_2025": 11,
    "ratio_yoy": null,
    "cross_site_context_min_2025": 3901,
    "cross_site_context_site": "CASALGRANDE",
    "trigger": "value 355x below next-smallest non-trivial GAS_NAT consumer in same year; physically implausible for an industrial kiln site. Pre-flagged in requirements.md §6.1 and DQ-CRIT-04 definition.",
    "recommended_action": "Data steward to investigate source billing record for VIANO_GARGOLA GAS_NAT 2025. Check whether (a) the meter read is in MWh or GJ and was not converted, (b) the site was offline, (c) the read covers only a partial period, (d) there is a data-entry transcription error. Do not use 11 Sm3 in 2025 calculations until confirmed.",
    "blocks_phase_5": true
  },
  {
    "rule_id": "DQ-CRIT-05",
    "severity": "CRIT",
    "scope": "Scope 1",
    "site": "VIANO_GARGOLA",
    "metric": "GAS_NAT temporal gap",
    "detail": "VIANO_GARGOLA present in 2025 GAS_NAT (11 Sm3) but absent in 2024 GAS_NAT with no explicit zero row. This is a temporal gap per DQ-CRIT-05 definition. The gap is in the opposite direction to SASSUOLO Grid (present 2024, absent 2025), which had a user-confirmed explicit zero. For VIANO_GARGOLA 2024 GAS_NAT no such confirmation exists.",
    "year_absent": 2024,
    "year_present": 2025,
    "trigger": "site present in year T+1 (2025) but absent in year T (2024) without explicit zero",
    "recommended_action": "Same as DQ-CRIT-01: data steward to supply 2024 value or insert explicit zero with rationale. Note DQ-CRIT-01, DQ-CRIT-04, and DQ-CRIT-05 for VIANO_GARGOLA GAS_NAT are co-dependent findings; a single data remediation may resolve all three.",
    "blocks_phase_5": true
  },
  {
    "rule_id": "DQ-WARN-01",
    "severity": "WARN",
    "scope": "Scope 2",
    "site": "VIANO",
    "year_pair": [2024, 2025],
    "metric": "EE_Acquistata_GO kWh",
    "value_2024": 6551604,
    "value_2025": 3268364,
    "ratio_yoy": 0.499,
    "trigger": "ratio < 0.6",
    "recommended_action": "Data steward confirms whether VIANO operated at reduced capacity in 2025 (partial production halt, seasonal shutdown) or whether 2025 electricity data is incomplete. If missing data, replay ETL with corrected source. Cross-reference against VIANO GAS_NAT and GASOLIO reductions in 2025 (same pattern across all three energy carriers confirms a site-level issue).",
    "blocks_phase_5": false,
    "note": "Pre-registered finding. OI-2 open. The correlated drop across GAS_NAT (0.421x), GASOLIO (0.493x), and EE_GO (0.499x) at VIANO strongly suggests either genuine operational reduction (shutdown, maintenance period) or systematic 2025 data undercount."
  },
  {
    "rule_id": "DQ-WARN-02",
    "severity": "WARN",
    "scope": "Scope 1",
    "site": "IANO",
    "year_pair": [2024, 2025],
    "metric": "PROCESSO_DECARB data quality",
    "value_2024": 9363616,
    "value_2025": 9061067,
    "unit": "kg CaCO3",
    "qualita_dato": "E (Estimated)",
    "fonte_dato": "Stima interna",
    "trigger": "Qualita_Dato = E for process emission estimation",
    "recommended_action": "Disclose LOI 3.5% estimation uncertainty (+/-10-20%) in ESRS E1-6 PDF per methodology_validation.md §6.4. Flag for Tier-2 upgrade (XRF measurement). No data change needed; annotation is sufficient.",
    "blocks_phase_5": false,
    "note": "Pre-registered finding. Confirmed: Stato_Dato = Stimato in both years. Note field = 'LOI 3,5%' in both years."
  },
  {
    "rule_id": "DQ-WARN-03",
    "severity": "WARN",
    "scope": "Scope 3",
    "site": null,
    "year_pair": [2024, 2025],
    "metric": "Spend-based Cat 1/2/6 rows",
    "affected_subcategories": ["Servizi vari (Agenti)", "Servizi vari (Lav.est./Acq.prd.fin)", "Servizi vari (Servizi)", "Servizi vari (Altro)", "Impiantistica", "Materiali di consumo", "Voli", "Auto noleggio", "Hotel"],
    "trigger": "Metodo = Spend-based",
    "recommended_action": "Annotate all spend-based rows with uncertainty disclosure in ESRS E1-6. EXIOBASE/CDP sector ratios have inherent uncertainty of +/-30-50% vs primary activity data. Specific note for Cat 6 (business travel): DEFRA spend-based factors are GBP-denominated; EUR/GBP conversion methodology must be documented by data-engineer at Phase 5.",
    "blocks_phase_5": false,
    "note": "Pre-registered finding."
  },
  {
    "rule_id": "DQ-WARN-04",
    "severity": "WARN",
    "scope": "Scope 3",
    "site": null,
    "year_pair": [2024, 2025],
    "metric": "Proxy-based Cat 7/9/12 rows",
    "affected_subcategories": ["Commuting_Auto", "Italia_Strada", "Europa_Strada", "Export_Nave", "Piastrelle_Discarica", "Piastrelle_Riciclo"],
    "trigger": "Qualita_Dato = E or Fonte_Dato in {Proxy settoriale, Stima interna}",
    "recommended_action": "Disclose proxy assumptions in ESRS E1-6. Cat 7: 8,800 km/FTE/year is an internal estimate; FTE count confirmed by HR (506/484). Cat 9: load factor 27t per truck is a sector proxy. Cat 12: 30%/70% landfill/recycle split is sector proxy.",
    "blocks_phase_5": false,
    "note": "Pre-registered finding."
  },
  {
    "rule_id": "DQ-WARN-05",
    "severity": "WARN",
    "scope": "Scope 2",
    "site": "SASSUOLO",
    "year": 2025,
    "metric": "EE_Acquistata_Grid 2025",
    "status": "RESOLVED",
    "detail": "SASSUOLO EE_Acquistata_Grid 2025 confirmed zero by user 2026-05-13. ETL synthesises explicit zero row with provenance flag auto_zero_user_confirmed. DQ-CRIT-05 temporal gap suppressed for this case.",
    "blocks_phase_5": false,
    "note": "Pre-registered RESOLVED finding. Confirmed: SASSUOLO 2024 Grid = 46,786 kWh present in native CSV (Fattura fornitore, Qualita_Dato=P, Stato_Dato=Definitivo)."
  },
  {
    "rule_id": "DQ-WARN-06",
    "severity": "WARN",
    "scope": "Scope 1",
    "site": "VIANO",
    "year_pair": [2024, 2025],
    "metric": "GAS_NAT Sm3",
    "value_2024": 4569554,
    "value_2025": 1925606,
    "ratio_yoy": 0.421,
    "trigger": "ratio < 0.6 (NEW — not pre-flagged)",
    "recommended_action": "Investigate jointly with DQ-WARN-01 (VIANO EE_GO) and DQ-WARN-07 (VIANO GASOLIO). If VIANO experienced a partial shutdown in 2025, document the production days and confirm data covers the full calendar year. If data is incomplete, re-ingest from billing records.",
    "blocks_phase_5": false,
    "note": "NEW finding. Combined with DQ-WARN-01 and DQ-WARN-07 this represents a VIANO site-wide energy pattern that is internally consistent and strongly suggestive of a genuine operational event or systematic data gap at VIANO in 2025."
  },
  {
    "rule_id": "DQ-WARN-07",
    "severity": "WARN",
    "scope": "Scope 1",
    "site": "VIANO",
    "year_pair": [2024, 2025],
    "metric": "GASOLIO litri",
    "value_2024": 44600,
    "value_2025": 22000,
    "ratio_yoy": 0.493,
    "trigger": "ratio < 0.6 (NEW — not pre-flagged)",
    "recommended_action": "Same root cause investigation as DQ-WARN-06 / DQ-WARN-01.",
    "blocks_phase_5": false,
    "note": "NEW finding."
  },
  {
    "rule_id": "DQ-WARN-08",
    "severity": "WARN",
    "scope": "Scope 1",
    "site": "SASSUOLO",
    "year_pair": [2024, 2025],
    "metric": "BENZINA litri",
    "value_2024": 1349,
    "value_2025": 9151,
    "ratio_yoy": 6.784,
    "trigger": "ratio > 1.67 — 578% increase (NEW — not pre-flagged)",
    "recommended_action": "Data steward to confirm: (a) whether SASSUOLO acquired additional petrol-fuelled vehicles in 2025, (b) whether 2024 data is complete (1,349 L is plausible for one vehicle if partially recorded), (c) whether there has been any reclassification from GASOLIO to BENZINA. Absolute impact is small (7,802 extra litres) but the percentage change is extreme and may indicate a data entry issue in the 2024 figure.",
    "blocks_phase_5": false,
    "note": "NEW finding. Absolute delta is modest (7,802 litres) but YoY ratio is 6.78x. Phase 5 data-analyst should apply BENZINA WTT calculation to the higher 2025 figure if confirmed."
  },
  {
    "rule_id": "INFO-01",
    "severity": "INFO",
    "scope": "Scope 3 — Cat 1",
    "detail": "requirements.md §6.3 declares Cat 1 2024 = 15 records. Actual parsed count = 14 records (consistent with enumerated subcategories: 10 mass-based + 4 spend-based). The '15' figure in requirements.md appears to be an over-count by 1 in documentation. The CSV is arithmetically correct and internally consistent. No missing subcategory identified.",
    "blocks_phase_5": false
  },
  {
    "rule_id": "INFO-02",
    "severity": "INFO",
    "scope": "Scope 3 — Cat 3 / FR-11",
    "detail": "requirements.md §FR-11 cited GAS_NAT 2024 delta: Sigma_S1 = 28,149,392 Sm3 vs Cat3_CSV = 33,149,422 Sm3 (+18%). In the current CSV files, Sigma_S1 GAS_NAT 2024 = 33,149,422 Sm3 = Cat3_CSV, delta = 0. The prior version's Sigma_S1 figure (28,149,392) was based on an earlier dataset version. Requirement §FR-11 delta is now resolved. Logged here for audit trail.",
    "blocks_phase_5": false
  },
  {
    "rule_id": "INFO-03",
    "severity": "INFO",
    "scope": "Scope 3 — Cat 2",
    "detail": "Cat 2 spend drops 60.7% YoY: 2024 Impiantistica = 13,103,478 EUR; 2025 Impiantistica = 3,903,979 EUR. Spend-based categories are inherently volatile. No gate rule applies. Data steward should confirm this reflects actual capex reduction not incomplete ingestion.",
    "blocks_phase_5": false
  },
  {
    "rule_id": "INFO-04",
    "severity": "INFO",
    "scope": "Scope 3 — Cat 5",
    "detail": "Cat 5 non-pericolosi da riciclo drops 28.0% YoY (2024: 5,990 t; 2025: 4,313 t). Consistent directionally with VIANO production reduction hypothesis. No gate rule for Cat 5 YoY. Informational cross-check.",
    "blocks_phase_5": false
  }
]
```

---

## 12. Verdict for Phase 5

### PHASE 5 IS BLOCKED

The following critical findings must be remediated before Phase 5 (emission calculations) may proceed:

| Finding ID | Rule triggered | Remediation required |
|---|---|---|
| **DQ-CRIT-01** | DQ-CRIT-01 — facility coverage < 7/7 | Supply VIANO_GARGOLA GAS_NAT 2024 value or explicit zero |
| **DQ-CRIT-02** | DQ-CRIT-02 — mandatory metadata blank | Populate Fonte_Dato / Qualita_Dato / Stato_Dato for all 10 Cat 3 rows |
| **DQ-CRIT-04** | DQ-CRIT-04 — outlier z > threshold | Investigate and confirm/correct VIANO_GARGOLA GAS_NAT 2025 = 11 Sm³ |
| **DQ-CRIT-05** | DQ-CRIT-05 — temporal gap | Insert explicit zero or supply 2024 value for VIANO_GARGOLA GAS_NAT |

Note: DQ-CRIT-01, DQ-CRIT-04, and DQ-CRIT-05 for VIANO_GARGOLA GAS_NAT are co-dependent. A single data-steward action (supplying or confirming the 2024 value, and clarifying the 2025 value of 11 Sm³) may resolve all three simultaneously.

DQ-CRIT-02 for Cat 3 metadata is independent and requires a separate but simple fix (populating three metadata fields across 10 rows).

### Conditions for Unblocking Phase 5

1. Data steward submits a corrected `scope1_combustione.csv` containing VIANO_GARGOLA GAS_NAT 2024 (actual value or documented explicit zero).
2. Data steward submits a corrected `scope3_categorie.csv` with Fonte_Dato, Qualita_Dato, Stato_Dato populated for all 10 Cat 3 rows.
3. Data steward provides written confirmation on VIANO_GARGOLA GAS_NAT 2025 = 11 Sm³ (confirmation of correctness or correction of value).
4. Data steward provides written explanation of the VIANO 2025 energy pattern (all three carriers ~50% decline) to confirm whether it reflects genuine operations or data incompleteness. If data incompleteness: 2025 VIANO data must be reingested before Phase 5 2025 calculations can be signed off.
5. OrchestratorAgent to record DQ-CRIT-01/04/05 block release in the pipeline audit log once conditions 1–3 are met.

### DQ-WARN Status for Phase 5

DQ-WARN findings (DQ-WARN-01 through DQ-WARN-08) do not block Phase 5 individually. They require:
- Dashboard warning banner for VIANO 2025 data (FR-24 / DQ-WARN-01).
- Annotation on IANO Processo_Decarb rows (DQ-WARN-02).
- Uncertainty disclosures in ESRS E1-6 PDF for spend-based and proxy-based rows (DQ-WARN-03, DQ-WARN-04).
- Resolution of SASSUOLO BENZINA 2025 before the 2025 Cat 3 WTT BENZINA calculation is finalized (DQ-WARN-08).

---

## 13. Operational Recommendations for Phase 4 (architect-agent)

### 13.1 DLQ Structure (FR-32, NFR-13)

The Dead-Letter Queue (DLQ) must capture at minimum the following fields for each rejected row, derived from this report's findings:

| Column | Type | Purpose |
|---|---|---|
| `dq_finding_id` | UUID | Links DLQ entry to `dq_findings` table |
| `rule_id` | VARCHAR(20) | e.g. DQ-CRIT-01, DQ-WARN-06 |
| `severity` | VARCHAR(10) | CRIT or WARN |
| `scope` | INT | 1, 2, or 3 |
| `codice_sito` | VARCHAR(30) | Nullable (corporate-level findings) |
| `anno` | INT | Reporting year of the affected row |
| `combustibile_or_voce` | VARCHAR(50) | Fuel / voce_S2 / categoria_S3 key |
| `value_observed` | NUMERIC | The value that triggered the gate |
| `threshold` | VARCHAR(100) | Human-readable threshold (e.g. "< 0.6 ratio") |
| `z_score` | NUMERIC | Z-score if outlier check; NULL otherwise |
| `ratio_yoy` | NUMERIC | Year-over-year ratio if ratio check; NULL otherwise |
| `raw_row_id` | UUID FK | FK to ingestion staging table |
| `ingestion_batch_id` | UUID | Correlation ID of the batch run |
| `fired_at` | TIMESTAMPTZ | UTC timestamp |
| `message` | TEXT | Human-readable description |
| `resolution_status` | VARCHAR(20) | OPEN, WAIVED, REMEDIATED |
| `resolved_by` | VARCHAR(100) | Username who resolved |
| `resolved_at` | TIMESTAMPTZ | NULL until resolved |

### 13.2 Recommended `dq_findings` Table Schema

The `dq_findings` table stores the runtime artefacts produced by data-quality-agent (i.e. the findings in §11 above), persisted for audit trail:

```sql
CREATE TABLE dq_findings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id          VARCHAR(20)  NOT NULL,
    severity         VARCHAR(10)  NOT NULL CHECK (severity IN ('CRIT','WARN','INFO')),
    scope            INT,
    codice_sito      VARCHAR(30),
    anno             INT,
    metric           VARCHAR(100),
    value_observed   NUMERIC,
    value_reference  NUMERIC,
    ratio_yoy        NUMERIC,
    z_score          NUMERIC,
    trigger_desc     TEXT,
    recommended_action TEXT,
    blocks_pipeline  BOOLEAN      NOT NULL DEFAULT FALSE,
    dq_report_version VARCHAR(20) NOT NULL,
    assessed_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolution_status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                      CHECK (resolution_status IN ('OPEN','WAIVED','REMEDIATED')),
    resolved_by      VARCHAR(100),
    resolved_at      TIMESTAMPTZ,
    waiver_justification TEXT,
    waiver_approved_by   VARCHAR(100)
);
```

This table is append-only consistent with the immutability design (FR-20). Resolution updates are implemented as new rows with `resolution_status = REMEDIATED` and reference to the original finding_id (via a `parent_finding_id` FK), not as UPDATEs.

### 13.3 Idempotency-Key Strategy

This assessment found no duplicate rows across any CSV. However, the idempotency key for the ingestion pipeline must be designed to detect re-runs. Recommended composite idempotency key per FR scope:

- **Scope 1**: `(Codice_Sito, Anno, Combustibile)` — unique per site/year/fuel. The Note field is excluded from the key to tolerate minor annotation changes.
- **Scope 2**: `(Codice_Sito, Anno, Voce_S2)` — unique per site/year/voce. The ETL-synthesised SASSUOLO Grid 2025 row needs a synthetic `codice_sito || year || voce_s2` key plus `provenance = auto_zero_user_confirmed` to distinguish it from a native zero that might later be ingested.
- **Scope 3**: `(Anno, Categoria_S3, Sottocategoria)` — unique per year/category/subcategory. Combustibile is a secondary key for Cat 3 rows.

Idempotency enforcement recommendation: pre-insert hash check against a `raw_ingestion_staging` table keyed by `(idempotency_key_hash, batch_id)`. On hash collision, skip insert and log as DUPLICATE in DLQ.

### 13.4 Provenance Flag `auto_zero_user_confirmed`

The ETL-synthesised SASSUOLO EE_Acquistata_Grid 2025 = 0 kWh row requires:

```python
{
    "codice_sito": "SASSUOLO",
    "anno": 2025,
    "voce_s2": "EE_Acquistata_Grid",
    "quantita": 0.0,
    "unita": "kWh",
    "strumento_mb": "Grid_Residual",
    "fonte_dato": "ETL_synthesis",
    "qualita_dato": "U",          # User-confirmed
    "stato_dato": "Definitivo",
    "provenance": "auto_zero_user_confirmed",
    "confirmation_source": "user_2026-05-13",
    "confirmation_rationale": "Full GO contract switch; 100% EE_Acquistata_GO in 2025"
}
```

The `provenance` field must be a first-class column in the `raw_ingestion_staging` table, not a free-text note, so that DQ gate DQ-CRIT-05 can be programmatically suppressed for rows where `provenance = auto_zero_user_confirmed` and `blocks_dq_crit_05_waived = TRUE`. This separation prevents accidental suppression of genuine temporal gaps.

### 13.5 Schema Note — `scope3_categorie.csv` Cat 3 Blank Metadata

The blank Fonte_Dato / Qualita_Dato / Stato_Dato fields across all 10 Cat 3 rows are a structural CSV deficiency. The ETL pipeline should enforce non-null on these columns for all ingested rows and reject Cat 3 rows with blank metadata to DLQ with rule_id = DQ-CRIT-02. After data-steward remediation, the corrected values should flow through the same ingestion path with a new batch_id.

---

## 14. Resolution Addendum (2026-05-13)

User responses 2026-05-13 closed all 4 DQ-CRIT triggers without modifying the native CSVs. Remediation is implemented as deterministic ETL transforms (FR-01 / FR-02 / FR-37) consistent with the append-only / source-immutability principle (FR-20, NFR-21).

### 14.1 DQ-CRIT closure log

| Finding | User decision | ETL remediation | Status |
|---|---|---|---|
| **DQ-CRIT-01** (VIANO_GARGOLA GAS_NAT 2024 absent) | "2024 = 0 reale (no gas connection)" | FR-01 ETL synthesises explicit `VIANO_GARGOLA GAS_NAT 2024 = 0 Sm³` row with provenance `auto_zero_user_confirmed`. Native CSV unchanged. | **CLOSED** |
| **DQ-CRIT-02** (10 Cat 3 rows blank Fonte_Dato/Qualità_Dato/Stato_Dato) | "Accetta fix DQ agent" | FR-37 ETL defaulting: `Fonte_Dato = "Derivato da Scope 1/2 per FR-11"`, `Qualità_Dato = "D"`, `Stato_Dato = "Definitivo"`. INFO-level entry in `dq_findings` per defaulted row. Native CSV unchanged. | **CLOSED** |
| **DQ-CRIT-04** (VIANO_GARGOLA GAS_NAT 2025 = 11 Sm³ outlier) | "11 Sm³ reale (commissioning value)" | Annotation only — ETL keeps the value, dashboard/PDF display "VIANO_GARGOLA — gas commissioned 2025" tooltip. No ETL transform required. | **CLOSED** |
| **DQ-CRIT-05** (VIANO_GARGOLA GAS_NAT temporal gap) | (co-dependent with CRIT-01) | Resolved by the FR-01 synthesised 2024 zero row. | **CLOSED** |

### 14.2 DQ-WARN reclassifications

| Finding | User decision | Reclassification |
|---|---|---|
| **DQ-WARN-01** (VIANO EE_GO 2025 −50.1%) | "Fermo parziale reale" | Reclassified from anomaly to **operational annotation**. Dashboard banner: "VIANO — reduced operation 2025". |
| **DQ-WARN-06** (VIANO GAS_NAT 2025 −57.9%) | "Fermo parziale reale" | Same as WARN-01. |
| **DQ-WARN-07** (VIANO GASOLIO 2025 −50.7%) | "Fermo parziale reale" | Same as WARN-01. |
| **DQ-WARN-08** (SASSUOLO BENZINA 2025 +578%) | "Aumento reale flotta benzina" | Confirmed real. WTT Cat 3 BENZINA 2025 calculation includes annotation "Fleet expansion 2025" in disclosure_notes. |

### 14.3 OI-2 closure

OI-2 (suspected VIANO 2025 data incompleteness) is now **CLOSED** in `requirements.md` v1.2.1. The −50% pattern is real partial production halt; 2025 YoY can be consolidated and published without reimport.

### 14.4 Phase 5 unblock status

**Phase 5 is UNBLOCKED.** All 4 DQ-CRIT remediations are implemented as ETL transforms specified in FR-01 / FR-02 / FR-37. Native CSV files in `/data/raw/` remain untouched. Architect-agent (Phase 4) and data-engineer-agent (Phase 5) can proceed.

### 14.5 Outstanding DQ-WARN for Phase 5 display

These do not block Phase 5 but must be exposed to dashboard / PDF users:

- WARN-02 (Processo_Decarb LOI-3.5% method) — annotate IANO rows
- WARN-03 (spend-based Cat 1 services, Cat 2, Cat 6) — uncertainty disclosure in ESRS E1-6
- WARN-04 (proxy-based Cat 7, Cat 9, Cat 12) — proxy methodology disclosure

---

*Addendum end — 2026-05-13 — closes all DQ-CRIT triggers raised in §11.*

