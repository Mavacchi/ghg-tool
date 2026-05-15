# Auto-Calc Design — consumption -> tCO2e

**Version**: 1.0.0 (Wave: feature-template-and-autocalc)
**Date**: 2026-05-15
**Owner**: SustainabilityExpertAgent
**Status**: DESIGN — to be consumed by backend + UI for implementation
**Scope**: Methodology specification only. No code. Complements `docs/methodology.md` (which is the canonical reference and is NOT modified by this document).

References:
- GHG Protocol Corporate Standard (2004), Scope 2 Guidance (2015), Scope 3 Standard (2011).
- IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (GWP100 source classes).
- IPCC 2006 Guidelines V3 §2.5.1.3 (process emissions).
- CSRD Directive 2022/2464/EU; ESRS E1 (Delegated Regulation, 2023) — §44 (gas-by-gas), §50–§55 (dual-track reconciliation), §49 (biogenic flows).
- ISAE 3000 (Revised) §A99 (sufficient appropriate evidence; separation of duties); §A50–§A56 (precision and aggregation).
- IAASB ISA 320 §A3–§A14 (materiality).
- EU MRR Reg. UE 2018/2066 (AR5 GWPs for EU ETS Phase IV).

---

## §1 Goal and Scope

### In scope

- User submits a single consumption row through the UI (or API) describing **what was consumed, where, when, in which unit**.
- The system AUTOMATICALLY resolves the appropriate emission factor from `ref.factor_catalog`, applies the correct formula, returns the `tCO2e` together with the full audit trail (factor_id, version, source, gwp_set, methodology).
- Two operations are exposed: `preview` (read-only, no DB write) and `insert` (writes one immutable row in `calc.emissions_consolidated`).
- Coverage in v1 (post customer feedback 2026-05-15): Scope 1 combustion (GAS_NAT, GASOLIO, BENZINA — solo queste 3 categorie), Scope 1 process (CaCO3 decarbonation with **direct-tCO2 input mode** as default), Scope 2 LB, Scope 2 MB (GO + residual), Scope 3 Cat 1 (purchased goods + services), Scope 3 Cat 3 WTT/T&D, **plus Cat 4 / 5 / 6 / 7 / 9 / 12** (customer-confirmed: all Scope 3 categories must accept quantity × factor input in v1, not just Cat 1/3).

### Out of scope

- Bulk ingestion (`raw.scope*_ingestions` ETL path is unchanged; this design adds a complementary single-row path).
- New factor authoring (factor catalog lifecycle is governed by `methodology.md §13`).
- Recalculation / correction workflow (FR-21, FR-26 unchanged).
- EU Taxonomy KPI computation (deferred to v2 — `methodology.md §12`).
- Schema design (delegated to ArchitectAgent / DataEngineerAgent).
- Python / SQL / FastAPI code (delegated to backend dev agents).

---

## §2 Per-Scope Lookup Matrix

The lookup contract is: given the user input fields, the resolver MUST produce **exactly one** `factor_id` (per gas component when applicable) at the resolution moment. If zero or more-than-one factor would match, the resolver raises `AmbiguousFactorError` (see §6).

### 2.1 Scope 1 — Combustion

Lookup key (multi-component): `(scope=1, sub_scope='combustion', combustibile, component in {CO2, CH4, N2O}, gwp_set, vintage)`.

| User input field | Required | Drives |
|---|---|---|
| `scope = 1` | yes | filter |
| `categoria_s1` in **`{Gas_Naturale, Gasolio_Auto, Benzina_Auto}`** | yes | sub_scope dispatch + fuel identity. **CUSTOMER FEEDBACK 2026-05-15: queste sono le SOLE 3 categorie di Scope 1 Combustion. La 4ª categoria del CSV (`Processo_Decarb`) appartiene a Scope 1 Process e ha il suo sub-scope dedicato (§2.2).** |
| `combustibile` in {GAS_NAT, GASOLIO, BENZINA} | yes (derivato da `categoria_s1`) | factor family selection (DEFRA fuel ID) |
| `codice_sito` | yes | per-site attribution (not lookup) |
| `anno` | yes | vintage selection (§3) |
| `quantita`, `unita` | yes | activity data + unit-match (§4) |
| `gwp_set` | default AR6 | factor variant + GWP application (§5) |

Three factors resolved per row (`COMB_<fuel>_<gas>_DEFRA_<vintage>`). Formula identical to current `scope1_combustion.py`: `tco2e = sum_gas (factor_gas * quantita * KG_TO_TONNE * gwp_gas)`.

### 2.2 Scope 1 — Process (CaCO3 decarbonation)

**CUSTOMER FEEDBACK 2026-05-15: l'utente ha il dato in tCO2 già calcolato/stimato e vuole inserirlo direttamente. Supportiamo DUE modalità nello stesso form (toggle "input mode"):**

**Mode A (default, customer-preferred): direct CO2**
- Input: `quantita` in `tCO2`
- No factor lookup. `tco2e = quantita * 1.0` (factor virtuale = 1, source = `DIRECT_INPUT`, methodology = `direct_measurement`)
- Audit trail: `factor_source = 'direct_input'`, `disclosure_notes` registra "Emissioni di processo inserite direttamente dall'utente"
- Pre-insert DQ: `quantita >= 0` and `unita == 'tCO2'`

**Mode B (alternativa, stoichiometric): mass of raw material**
- Input: `quantita` in `t CaCO3` (o kg con conversione esatta §4)
- Lookup key: `(scope=1, sub_scope='process', categoria_s1='Processo_Decarb', gwp_set, vintage)` → `STOICH_CACO3_IPCC_2006` (0.4397 tCO2 / t CaCO3). GWP=1 (CO2 only).
- Formula: `tco2e = quantita * 0.4397 * KG_TO_TONNE` (se quantita in kg)

Constraint: applicable only to `codice_sito = IANO` per `methodology.md §2`.

### 2.3 Scope 2 — Location-Based

Lookup key: `(scope=2, sub_scope='LB', country='IT', gwp_set, vintage)` -> `LB_IT_GRID_ISPRA_<vintage>`.

| User input field | Required | Drives |
|---|---|---|
| `scope = 2` | yes | filter |
| `voce_s2` | yes | any of `EE_Acquistata_GO` / `EE_Acquistata_Grid` — both contribute to LB |
| `codice_sito` -> country mapping | yes | LB factor selection. V1 hard-mapping: all 7 sites -> `IT` |
| `anno` | yes | vintage (§3) |
| `quantita`, `unita = kWh` | yes | activity |
| `gwp_set` | default AR6 | composite factor variant |

Formula unchanged: `tco2e = factor.value * quantita * KG_TO_TONNE`. Component-split columns left NULL per `scope2_lb.py` M-07.

### 2.4 Scope 2 — Market-Based

Lookup key: `(scope=2, sub_scope='MB', strumento_mb, country='IT', gwp_set, vintage)`.

Instrument hierarchy (GHG Protocol Scope 2 Guidance 2015 Ch.6, Quality Criteria Ch.7):
1. `strumento_mb = 'GO_GSE'` AND QC1..QC8 evidence PASSED -> `MB_GO_ZERO` (0 tCO2e/MWh).
2. `strumento_mb = 'GO_GSE'` AND QC1..QC8 FAILED -> **REJECT** with `GOValidationError` (MG-14). Never silently fall back to residual.
3. `strumento_mb in {'Grid_Residual', None, ...}` -> `MB_IT_RESIDUAL_AIB_<vintage>`.

The QC1..QC8 check is delegated to `GOEvidenceCheck` port (already defined in `scope2_mb.py`). For UI single-entry: if a user enters a `GO_GSE` row, the QC evidence must already exist in `ref.go_certificate_qc_*` for the same `(codice_sito, anno)`. If not, return a 422 with explicit reason — no zero MB without evidence.

### 2.5 Scope 3 — Cat 1 (Purchased goods & services)

Lookup key (mass-based): `(scope=3, sub_scope='Cat1', methodology='mass-based', sottocategoria, gwp_set, vintage)` -> `ECOINV_<material>_V3_10`.
Lookup key (spend-based): `(scope=3, sub_scope='Cat1', methodology='spend-based', sottocategoria, gwp_set, vintage)` -> `EXIO_<NACE>` (e.g. `EXIO_SERVICES_NACE_M`).

| User input field | Required | Drives |
|---|---|---|
| `scope = 3` | yes | filter |
| `categoria_s3 = 1` | yes | Cat 1 dispatch |
| `sottocategoria` (free-text, normalized lowercase) | yes | maps to ecoinvent / EXIOBASE code via `_MATERIAL_FACTOR_MAP` / `_SPEND_FACTOR_MAP` |
| `metodo` in {Mass-based, Spend-based} | yes | dispatch + unit semantics (t vs EUR) |
| `quantita`, `unita` (t for mass, EUR for spend) | yes | activity |
| `gwp_set` | default AR6 | factor variant |
| `anno` | yes | vintage |

Biogenic split (ADR-007) applied automatically for `ECOINV_CARDBOARD_V3_10` and `ECOINV_PALLET_V3_10`. `tco2e` excludes biogenic; `co2_biogenic_tonne` populated as memo.

### 2.6 Scope 3 — Cat 3 (WTT + T&D)

Lookup key (WTT fuels): `(scope=3, sub_scope='Cat3', sub_kind='WTT', combustibile, gwp_set, vintage)` -> `WTT_<fuel>_DEFRA_<vintage>`.
Lookup key (WTT electricity): `(scope=3, sub_scope='Cat3', sub_kind='WTT_ELECTRICITY', country='IT', gwp_set, vintage)`.
Lookup key (T&D losses): `(scope=3, sub_scope='Cat3', sub_kind='TD_LOSSES', country='IT', gwp_set, vintage)`.

Note: per `methodology.md §2` and FR-11, the **fuel quantity for Cat 3 WTT must equal Sigma Scope 1 quantita** per `(combustibile, anno)`. The auto-calc UI MUST validate this on insert: when entering a Cat 3 WTT row, the system pre-computes the expected quantity from Scope 1 totals and either auto-fills or refuses divergence (see §8).

### 2.7 Scope 3 — other categories (Cat 4, 5, 6, 7, 9, 12)

**CUSTOMER FEEDBACK 2026-05-15: anche queste categorie devono accettare input quantità + fattore moltiplicativo nella v1. Il principio generale che l'utente ha richiesto è: "voglio sempre poter inserire una quantità e moltiplicarla per un fattore di conversione".**

Same contract: lookup key = `(scope=3, sub_scope, methodology, sottocategoria_or_route, gwp_set, vintage)`. The lookup function is generic; only the map `(sottocategoria -> factor_id)` is per-category. **V1 SCOPE EXPANDED: tutte le categorie (Cat 4, 5, 6, 7, 9, 12) devono essere supportate dalla UI con il pattern quantita × factor.**

Forward-compat: nuove sottocategorie aggiungibili al catalog senza modifiche al code.

---

## §3 Vintage Selection Rule

**Decision: Option B (closest-prior vintage) with explicit ceiling.**

When the user submits `anno = N`, the resolver:

1. Filters `ref.factor_catalog` rows where `is_published = true` AND `gwp_set = <requested>` AND `factor_family matches lookup key`.
2. From that set, selects the row with `vintage <= N` and the highest `vintage` (closest-prior).
3. If no `vintage <= N` row exists -> `MissingFactorError` (do NOT use a future factor).

### Normative justification

- **GHG Protocol Corporate Standard Ch.7** ("Accounting for GHG reductions") and **Scope 2 Guidance Ch.6** require factors to be **representative of the reporting period**. A factor published in year M for vintage M is the canonical "vintage-stretto" match; but real-world publication cycles (ISPRA, AIB, DEFRA) routinely lag by 12-18 months — strict equality (Option A) would systematically halt audits.
- **GHG Protocol Scope 2 Guidance §6.3** explicitly allows "the most recent factor available at the time of reporting" provided it is documented. The closest-prior rule operationalises this: never use a factor whose vintage post-dates the activity (which would imply prescience), always document the offset.
- **ISAE 3000 §A50** requires the auditor to verify that the factor applied is "the most appropriate available evidence at the date of measurement". Closest-prior with a documented offset satisfies this; closest-future does not.
- **CSRD ESRS E1 BP-2** requires disclosure of "significant judgements" — vintage offset is disclosed in `disclosure_notes` on each emission row.
- Option C (latest published regardless of vintage) is REJECTED: it can apply a 2026 factor to 2023 activity, distorting time-series and breaking FR-26 base-year integrity.

### Vintage offset disclosure

When `selected_factor.vintage < anno`, the emission row's `disclosure_notes` MUST include: `"Vintage offset: factor vintage=<X>, activity year=<N>; closest-prior rule applied per GHG Protocol Scope 2 Guidance §6.3."`

### Pinned exception: ISPRA 2024 vintage

`methodology.md §2` already documents the ISPRA 413/2025 (2023 data) usage for 2024 activity until 2024 vintage is published. The closest-prior rule produces the same outcome automatically — no special case required.

---

## §4 Unit Conversion Strategy

**Decision: Option C (factor catalog carries multi-unit variants) + restricted Option B (a small, normatively safe built-in conversion table).**

### Why not pure A

Option A (refuse any mismatch) blocks legitimate cases (`m3` vs `kWh` for gas where DEFRA publishes both forms) and is hostile to users entering invoice data.

### Why not pure B

Option B (free-form built-in conversions) requires per-fuel NCV (Net Calorific Value), which varies by gas composition (typical Italian natural gas: 10.55–10.83 kWh/Sm3 per ISPRA "Fattori di emissione" Tabelle). NCV is itself a methodological choice — embedding a single global NCV would hide a CSRD-grade decision from the audit trail.

### Decision detail

1. **Primary**: factor catalog stores factors in the unit the source publishes them (DEFRA gas: kg CO2/Sm3 and kg CO2/kWh — both are catalog rows with distinct `factor_id` suffixes). User selects the unit at input; resolver matches directly. **No conversion at runtime.**
2. **Built-in safe conversions** (no NCV, no assumption): only dimension-preserving conversions across the same physical quantity (mass, energy, volume).

### Accepted built-in conversion table (no NCV)

| From | To | Factor | Type | Notes |
|---|---|---|---|---|
| t | kg | 1000 | mass | exact |
| kg | t | 0.001 | mass | exact |
| MWh | kWh | 1000 | energy | exact |
| kWh | MWh | 0.001 | energy | exact |
| GJ | MJ | 1000 | energy | exact |
| MJ | kWh | 0.277777... | energy | exact (1 kWh = 3.6 MJ) |
| kWh | MJ | 3.6 | energy | exact |
| GJ | kWh | 277.777... | energy | exact |
| dm3 / l | m3 | 0.001 | volume (liquids) | exact |
| m3 | l | 1000 | volume (liquids) | exact |
| Sm3 | Nm3 | NOT supported | gas volume | normalization differs by standard (15 C vs 0 C) — REJECT |

### REJECTED conversions (require methodology choice)

- `Sm3 gas` <-> `kWh` (requires NCV — must be a catalog factor variant, not runtime).
- `litri gasolio` <-> `kWh` or `kg` (requires NCV and density).
- `EUR` <-> `USD` or any FX (requires PPP / period-specific conversion — out of scope).

If the user input unit and the resolved factor unit are not directly convertible via the built-in table, return `UnitMismatchError` with explicit hint: "Use factor variant `<factor_id_kWh>` or convert upstream."

### Normative justification

- **GHG Protocol Corporate Standard Ch.6** ("Calculating GHG emissions") requires that "the unit of activity data must match the unit basis of the emission factor". The closest match is achieved by carrying the factor in the source unit, not by silent runtime conversion.
- **ISO 14064-1 §6.2.2** requires uncertainty quantification for every methodological assumption; NCV variability is a quantifiable uncertainty that belongs in factor metadata, not in a global constant.
- **ISAE 3000 §A99** — silent unit conversions are not "sufficient appropriate evidence". Multi-variant catalog rows are.

---

## §5 GWP Set Handling

- **Default**: `gwp_set = 'AR6'` per CSRD ESRS E1-6 §44.
- **User override**: dropdown in UI with `AR6 (CSRD default)` and `AR5 (EU ETS Phase IV)`. Backend accepts `gwp_set` field; if absent -> AR6.
- **Dual-track**: not in scope for single-row preview/insert UI in this wave. The `POST /api/v1/calc/run-dual` endpoint (`methodology.md §11.1`) remains the dual-track entry point. Single-row insert in AR5 is permitted with `regulatory_stream = 'EU_ETS_PHASE_IV'` set by the caller (admin only).
- **Never mixed**: a single emission row carries exactly one `gwp_set`. The UI never aggregates AR5 and AR6 totals in the same widget.
- **AR4 prohibited**: the input contract rejects `gwp_set = 'AR4'` at validation time with 422.

Normative anchors: `methodology.md §3`; IPCC AR6 WG1 Ch.7 SM Table 7.SM.7; MRR Reg. UE 2018/2066 Annex VI §3 (AR5).

---

## §6 Error Handling

| Error class | HTTP code | When | Caller action |
|---|---|---|---|
| `MissingFactorError` | 422 | No factor matches lookup key (scope, sub_scope, key fields, gwp_set, vintage<=anno) | Show: "Nessun fattore trovato per (scope=X, ..., anno=Y). Verifica il catalogo o richiedi un nuovo fattore al data steward." |
| `AmbiguousFactorError` | 500 | More than one active factor matches | Internal alert — catalog integrity bug; block insert |
| `UnitMismatchError` | 422 | User unit not directly convertible to factor unit | Suggest factor variant or upstream conversion |
| `GOValidationError` | 422 | `strumento_mb = GO_GSE` but QC1..QC8 not all PASS | Block insert; instruct user to complete GO evidence checklist |
| `InvalidScopeMappingError` | 422 | Scope on input does not match scope of resolved factor | Block; defensive integrity check |
| `UnpublishedFactorError` | 422 | Resolver hits a draft (is_published=false) — defensive | Block; should never happen given §2 filters |
| `GWPSetNotAllowedError` | 422 | Caller sent `gwp_set='AR4'` or unrecognised tag | Block |

**Hard rule: NO category-fallback.** The system never silently substitutes a generic factor for a missing specific one. The audit trail must trace user input -> exact factor; partial substitution is a CSRD/ISAE non-conformance.

---

## §7 Audit Trail — Preview vs Insert

### Preview (`POST /api/v1/calc/preview`)

- **NO writes** to `calc.emissions_consolidated`, `calc.audit_log`, `calc.dq_findings`.
- Returns the computed `tco2e` + breakdown + resolved factor metadata + DQ checks that would apply on insert.
- May emit a lightweight structured log line `calc.preview` for SIEM (no PII; payload-hashed). This is optional.
- Idempotent and safe to call repeatedly from the UI as the user edits the form.

### Insert (`POST /api/v1/calc/insert`)

Writes EXACTLY ONE row in `calc.emissions_consolidated` per call. Required fields on the row (already enforced by FR-22 / `methodology.md §7`):

| Column | Source |
|---|---|
| `id` | UUID v4 generated server-side |
| `tenant_id` | from session GUC |
| `correlation_id` | new UUID v4 per insert (single-row run; no dual unless API caller pre-sets) |
| `raw_row_id` | NULL (no staging row for direct-entry path) OR FK to a `raw.direct_entry` row if v1.1 introduces it |
| `scope`, `sub_scope`, `codice_sito`, `anno` | from input |
| `tco2e`, `co2_tonne`, `co2_fossil_tonne`, `co2_biogenic_tonne`, `ch4_tco2e`, `n2o_tco2e` | from computation |
| `factor_id` (UUID FK to `ref.factor_catalog.id`) | from resolver |
| `factor_business_key` (e.g. `COMB_GAS_NAT_CO2_DEFRA_2025`) | denormalised for audit |
| `factor_version`, `factor_source` | from resolver |
| `gwp_set`, `methodology`, `regulatory_stream` | from input |
| `calc_timestamp` | now() UTC |
| `created_by` | session `sub` UUID |
| `valid_from = now()`, `valid_to = NULL`, `superseded_by = NULL`, `reason_code = NULL` | append-only defaults |
| `disclosure_notes` | resolver-generated, includes vintage offset note if applicable |

Plus one row in `calc.audit_log` with `action='emission_inserted_direct'`, `before_state = NULL`, `after_state = <row JSONB>`.

Insert is rejected if it would violate the partial unique index `ux_emissions_active_natural_key` (`tenant_id, scope, sub_scope, codice_sito, anno, regulatory_stream, gwp_set`); duplicates require the FR-21 correction workflow, never a second active row.

---

## §8 Pre-Insert DQ Validation

Applied BEFORE the row is written. Failure returns 422 with the failing rule.

| Rule | Severity | Detail |
|---|---|---|
| `tco2e >= 0` | CRIT | Negative emissions impossible outside CCS path (out of v1 scope) |
| `quantita > 0` | CRIT | Zero quantity rows ARE allowed (FR-04, NFR-18 traceability) but must be explicitly flagged `is_zero_row=true` by the UI; negative input is always rejected |
| `factor.is_published = true` | CRIT | Draft factors never usable |
| `factor.is_tbc = false` OR explicit override flag | CRIT | TBC factors block insert |
| `factor scope == input scope` | CRIT | Defensive integrity (e.g. catch a scope-1 factor mis-attached to a scope-2 lookup) |
| `gwp_set in {AR6, AR5}` | CRIT | AR4 rejected |
| `combustibile` matches factor family | CRIT | E.g. GAS_NAT user input must not resolve to GASOLIO factor |
| `vintage_factor <= anno` | CRIT | Vintage rule (§3) |
| `codice_sito` in current operational boundary | CRIT | Per `methodology.md §1.1` table of 7 sites |
| `anno` within reporting window | WARN | Block if `anno < 2024` (no historical baseline) or `anno > current_year + 1`; WARN if data submitted after FR-21 lock date |
| Cat 3 WTT: `quantita == Sigma scope 1 quantita per (combustibile, anno)` | CRIT | FR-11 conservation |
| GO row: QC1..QC8 all PASS | CRIT | `methodology.md §2 (Scope 2 MB)`, MG-14 |
| Process row: `codice_sito = IANO` | CRIT | `methodology.md §2 (Scope 1 process)` |
| Unit consistent with factor (§4) | CRIT | Either exact match or in built-in table |
| Idempotency / dedup | CRIT | `ux_emissions_active_natural_key` partial unique |

The DQ findings, when not blocking, are persisted in `calc.dq_findings` linked by `correlation_id`.

---

## §9 Decimal Precision Policy

Aligned with `methodology.md §11` (Bitemporal) and ISAE 3000 §A50 (precision proportional to materiality).

| Field | Type | Precision | Rationale |
|---|---|---|---|
| User input `quantita` | `Decimal` | 20 significant digits, scale up to 6 (e.g. `Decimal('1234567890.123456')`) | Covers invoice precision (Sm3, kWh) without binary float drift |
| Factor `value` | `Decimal(20, 10)` | as stored in `ref.factor_catalog` | unchanged from current schema |
| GWP multipliers | `Decimal` exact (27.9, 273, 28, 265) | 3 significant digits | as published by IPCC |
| Intermediate `kg` (factor x quantita) | `Decimal`, full precision (no rounding) | propagated | preserves auditability |
| Intermediate `kg -> tonne` (`* Decimal('0.001')`) | exact | no loss | |
| Output `tco2e` (stored) | `Decimal(15, 6)` | 6 fractional digits = milligram-equivalent at tonne scale | matches `methodology.md §11` and ESRS E1 disclosure rounding to 1 tCO2e in published outputs (more digits retained internally for restatement math) |
| Output `co2_tonne`, `co2_fossil_tonne`, `co2_biogenic_tonne`, `ch4_tco2e`, `n2o_tco2e` | `Decimal(15, 6)` | same | |
| Rounding mode | `ROUND_HALF_EVEN` (banker's) | ISO 31-0 / IEEE 754 default; ISAE 3000 §A50 prefers unbiased rounding | applied ONLY at the final persistence step |

Float arithmetic is FORBIDDEN at every layer (input parsing, factor multiplication, GWP weighting, sum). The UI MUST send `quantita` as a JSON string to avoid IEEE-754 corruption (e.g. `"1234567.89"` not `1234567.89`).

---

## §10 API Contract Proposal

### `POST /api/v1/calc/preview`

Request (JSON):

```
{
  "scope": 1,
  "sub_scope": "combustion",             // "combustion" | "process" | "LB" | "MB" | "Cat1" | "Cat3" | ...
  "codice_sito": "IANO",                  // nullable for corporate Cat 1
  "anno": 2024,
  "combustibile": "GAS_NAT",              // required for scope 1 combustion / scope 3 WTT
  "categoria_s1": "Gas_Naturale",         // optional, drives sub_scope dispatch
  "categoria_s3": null,                   // 1..15 for scope 3
  "sottocategoria": null,                 // e.g. "Argille" for Cat 1
  "metodo": null,                         // "mass-based" | "spend-based" | "distance-based" | "activity-based"
  "strumento_mb": null,                   // "GO_GSE" | "Grid_Residual" for scope 2 MB
  "voce_s2": null,                        // "EE_Acquistata_GO" | "EE_Acquistata_Grid" for scope 2
  "quantita": "22916841",                 // STRING to preserve Decimal precision
  "unita": "Sm3",
  "gwp_set": "AR6",                       // optional, default AR6
  "regulatory_stream": "CSRD_ESRS_E1"     // optional, default CSRD_ESRS_E1
}
```

Response (200):

```
{
  "preview_id": "uuid",                   // ephemeral, for client correlation only
  "tco2e": "44530.123456",                // STRING Decimal
  "breakdown": {
    "co2_tonne": "44321.0",
    "co2_fossil_tonne": "44321.0",
    "co2_biogenic_tonne": null,
    "ch4_tco2e": "5.123",
    "n2o_tco2e": "204.0",
    "gas_components": [
      {"gas": "CO2", "factor_id": "...", "factor_value": "...", "contribution_tco2e": "..."},
      {"gas": "CH4", "factor_id": "...", "factor_value": "...", "gwp": "27.9", "contribution_tco2e": "..."},
      {"gas": "N2O", "factor_id": "...", "factor_value": "...", "gwp": "273", "contribution_tco2e": "..."}
    ]
  },
  "factor_metadata": {
    "primary_factor_id": "COMB_GAS_NAT_CO2_DEFRA_2025",
    "factor_db_id": "uuid",
    "factor_version": "2025",
    "factor_source": "DEFRA",
    "vintage": "2025",
    "vintage_offset_applied": false,
    "unit": "kg CO2 / Sm3"
  },
  "gwp_set": "AR6",
  "methodology": "activity-based",
  "regulatory_stream": "CSRD_ESRS_E1",
  "disclosure_notes": "Combustion GAS_NAT: CO2 factor=COMB_GAS_NAT_CO2_DEFRA_2025 ...",
  "dq_findings": [
    {"rule": "anno_within_window", "severity": "PASS"},
    ...
  ]
}
```

Errors: see §6.

### `POST /api/v1/calc/insert`

Request: identical body to `/preview` PLUS optional `idempotency_key` (UUID, recommended for retry safety).

Response (201): identical to preview body PLUS `emission_id` (UUID of the persisted row) and `audit_log_id`.

Errors: same set as preview, plus 409 Conflict if `ux_emissions_active_natural_key` would be violated; the response body MUST then carry the conflicting row id and instruct the caller to use the FR-21 correction endpoint.

---

## §11 UI Flow Proposal

### Form fields (single panel)

1. **Scope** dropdown: `1` / `2` / `3`.
2. **Sub-scope** dropdown — populated dynamically based on Scope (e.g. Scope 1 -> `Combustione` / `Processo`).
3. **Codice sito** dropdown — populated from `ref.sites` filtered by operational boundary (`methodology.md §1.1`).
4. **Anno** numeric picker — bounded 2024..currentYear+1.
5. **Combustibile** / **Voce S2** / **Categoria + Sottocategoria** — appears conditional on Sub-scope.
6. **Strumento MB** (Scope 2 only).
7. **Quantita** input + **Unita** dropdown (units restricted to factor-supported set for the chosen sub-scope; greyed-out when impossible).
8. **GWP set** dropdown — default `AR6 (CSRD)`, alternative `AR5 (EU ETS)`. Hidden behind "Advanced" toggle to reduce error.
9. **Note** free text (-> `disclosure_notes` suffix).

### Preview area (live, debounced 400ms after edit)

- Calls `/preview` whenever form passes client-side schema validation.
- Renders:
  - Large `tco2e` total with unit and GWP set chip.
  - Expandable gas component table (CO2 / CH4 / N2O contributions).
  - Resolved factor card: `factor_id`, `version`, `source`, `vintage` (with vintage offset warning badge when applicable).
  - DQ panel: list of rules with PASS / WARN / FAIL pills.
  - Methodology statement preview (the `disclosure_notes` that will be persisted).
- Any error response renders the actionable error message + a "go to factor catalog" deep link when relevant.

### Conferma button

- Disabled while any CRIT DQ rule fails.
- On click: calls `/insert` with the same payload + an `idempotency_key` (UUID generated on form open).
- On success: toast with `emission_id` + link to the consolidated row view.
- On 409: dialog explaining duplicate active row + button to launch the FR-21 correction workflow.

---

## §12 Open Questions for the Customer

### Risolte (2026-05-15, first round)

- **Scope 1 Combustion categories**: ridotte alle 3 reali (`Gas_Naturale`, `Gasolio_Auto`, `Benzina_Auto`). La 4ª del CSV (`Processo_Decarb`) è Scope 1 Process, separato.
- **Scope 1 Process input mode**: default è **direct tCO2** (l'utente ha il dato già calcolato). Mode B (massa CaCO3 con stoichiometric factor 0.4397) resta disponibile come toggle.
- **Scope 3 v1 coverage**: tutte le categorie (Cat 1, 3, 4, 5, 6, 7, 9, 12) devono accettare quantità × fattore nella v1. Principio generale dell'utente: «voglio sempre poter inserire una quantità e moltiplicarla per un fattore di conversione».

### Risolte (2026-05-15, second round)

1. **Direct-entry raw row** → **DECISIONE: SÌ, in wave successiva**. Introdurre tabella `raw.direct_entry` (stesso pattern di `raw.bulk_load`) per preservare FR-22 universal traceability: ogni riga in `emissions_consolidated` deve avere `raw_row_id` non-NULL. Migration Alembic prevista; backfill delle righe inserite con auto-calc tra deploy e cutover ammesso con UUID sentinel + nota in audit log.
2. **Multi-country sites** → **DECISIONE: SÌ**. Aggiungere colonna `country` (CHAR(2) ISO 3166-1 alpha-2) su `ref.sites`. Lookup Scope 2 LB risolve `site.country → LB factor` al posto del hardcode IT. Default `IT` per i 7 siti attuali. Owner della mappa = data steward.
3. **NCV catalog dual-unit** → **DECISIONE: SÌ**. Per ogni fuel pubblicare entrambe le varianti factor dove la fonte autorevole le pubblica (DEFRA pubblica per kWh, ISPRA per Sm³; per gasolio/benzina entrambe sono in litri come unità autorevole). Selezione runtime sull'`unita` user-provided.
4. **AR4 historical baselines** → **DECISIONE: NO**. Nessuna baseline pre-2024 richiede GWP AR4. Policy `methodology.md §3` (AR6 di default, AR5 per EU ETS Phase IV) confermata.
5. **Cat 3 WTT auto-cascade da Scope 1** → **DECISIONE: NO auto**. L'utente inserisce manualmente la riga Cat 3 WTT quando vuole. Eventuale "Replica come WTT" come bottone esplicito secondario in wave successiva.
6. **Idempotency key TTL** → **DECISIONE: 24h**. Header `Idempotency-Key` accettato su `/calc/insert`; chiavi tenute 24h per dedup retry rete.
7. **Site type discrimination** → **NUOVA DECISIONE (più strutturata della raccomandazione)**: aggiungere enum `site_type` su `ref.sites` con valori `STABILIMENTO_PRODUTTIVO`, `UFFICIO`, `MAGAZZINO`. La categoria `Processo_Decarb` (Scope 1 Process) è ammessa **solo per `STABILIMENTO_PRODUTTIVO`**. UI nasconde la voce per uffici/magazzini; backend rifiuta 422 con messaggio "Process emissions allowed only for STABILIMENTO_PRODUTTIVO sites". Migration Alembic + popolamento iniziale dei 7 siti (IANO = STABILIMENTO_PRODUTTIVO; gli altri da classificare con il customer). Use case ESG: gli uffici non hanno cottura/decarbonatazione, eventuali emissioni di processo lì sarebbero un data quality error.
8. **Bulk-from-UI paste** → **DECISIONE: fuori v1**. Endpoint `/calc/preview` resta singola riga in v1.
9. **Versioning del design doc** → **DECISIONE: confermata**. Owner = SustainabilityExpertAgent. Quando arrivano emendamenti ESRS E1 / aggiornamenti GHG Protocol questo doc si aggiorna PRIMA dell'implementazione, con changelog in fondo + bump versione.

### Implementazione delle decisioni risolte

Le decisioni #1, #2, #6, #7 hanno impatto su schema DB e richiedono migration Alembic + backend work. Le decisioni #3, #4, #5, #8, #9 sono policy / catalog updates senza schema change. Ordine consigliato di rollout: **#7 (site_type) → #2 (country) → #1 (raw.direct_entry) → #3 (NCV catalog) → #6 (idempotency key)**.
