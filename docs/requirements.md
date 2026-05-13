# Documento Requisiti — GHG Accounting Tool (Ceramic Tile Manufacturer)

---

## 1. Document Control

| Field | Value |
|---|---|
| Version | 1.1.0 |
| Date | 2026-05-13 |
| Author | requirements-agent (v1.0.0); user clarifications (v1.1.0) |
| Review Status | APPROVED — Phase 1 closed; v1.1.0 incorporates: (a) Cat 3 WTT fuel quantities derived from Σ Scope 1 (not CSV column), (b) FTE 506/484 confirmed as official HR headcount, (c) SASSUOLO 2025 EE_Acquistata_Grid = 0 confirmed (100% GO contract) |
| Task ID | ghg-tool-phase-1 |
| Base Year | 2024 |
| Reporting Years | 2024 (consolidated), 2025 (partial — see OI-2) |
| Next Review | Before Phase 2 kick-off |

**Semver policy**: minor bump (1.x.0) for additions or clarifications; major bump (2.0.0) for scope changes that invalidate prior FR/NFR IDs or break the audit trail schema.

---

## 2. Scope & Objectives

### 2.1 What This Tool Does

The GHG Accounting Tool is a purpose-built software system for a ceramic-tile manufacturer (gres porcellanato) operating 7 production sites in Italy. It ingests annual activity data, applies calibrated emission factors from a versioned factor catalog, calculates greenhouse gas emissions across Scopes 1, 2, and 3 per the GHG Protocol Corporate Standard, and produces CSRD-grade outputs for external reporting and internal management.

Primary deliverables for v1:

- Streamlit dashboard with hierarchical drill-down (scope → site → category → year → subcategory), year-over-year (YoY) comparison 2024 → 2025, intensity metrics, and colorblind-safe visualizations.
- Multi-sheet Excel export: emissions by scope, audit trail, metadata, factor catalog snapshot.
- CSRD-ready PDF report with ESRS E1-6 tables (Gross Scopes 1/2/3, categorical breakdown, intensity ratios).
- FastAPI REST API for future integration with CRM/ERP systems (medium priority, read + append-only emission write).

### 2.2 What This Tool Does NOT Do

- No real-time or streaming emissions monitoring; processing is annual batch ETL only.
- No Scope 4 avoided emissions calculation.
- No individual product-SKU life cycle assessment (LCA); Scope 3 Cat 11 is assessed at corporate level and disclosed as zero/omitted with rationale.
- No Science Based Targets (SBTi) target validation workflow in v1 (flagged as OI-1).
- No financed emissions (Scope 3 Cat 15) unless materiality assessment in Phase 2 determines otherwise (flagged as OI-3).
- No multi-tenant architecture in v1; single-tenant design must be architected for future multi-tenancy.
- No mobile application.
- No EU Taxonomy alignment scoring in v1 (flagged for future phase).
- No restatement automation; corrections follow the append-only superseded_by workflow described in Section 10.

---

## 3. Stakeholders & Roles

| Stakeholder | Responsibility | RBAC Role | Output Expected |
|---|---|---|---|
| ESG Manager | System owner; validates methodology, approves reports, signs off on CSRD disclosure | `esg_manager` | Dashboard, PDF CSRD report, Excel export |
| Data Steward | Inputs and validates raw activity data; manages factor catalog updates | `data_steward` | Data ingestion confirmation, DQ gate approval |
| External Auditor | Read-only review of calculations, audit trail, and factor provenance | `auditor` | Audit trail report, immutability evidence, factor catalog metadata |
| Executive Sponsor (CFO/CEO) | Receives top-level KPI summary; approves public disclosure | `esg_manager` (read, no write) | Executive summary page of PDF, intensity ratios |
| IT Operations | Deploys and maintains Docker containers, CI/CD pipeline, backups | `data_steward` (infra scope only) | Deployment runbooks, health metrics |
| External Assurance Provider (ISAE 3000 Limited) | Independent limited assurance engagement per CSRD requirement (years 2024–2026) | `auditor` | Full data lineage from raw row → consolidated emission, factor sources, GWP documentation |

**Note**: IT Operations does not require write access to emissions data; separation of duties must be enforced at DB level (RLS) and application level (RBAC).

---

## 4. Regulatory & Framework Scope

| Framework | Status | Role |
|---|---|---|
| CSRD / ESRS E1 | **PRIMARY — mandatory** | Drives reporting structure, data point list, ESRS E1-6 tables, limited assurance obligation |
| GHG Protocol Corporate Standard (2004 + Scope 2 Guidance 2015 + Scope 3 Standard 2011) | **PRIMARY — methodology** | Defines boundary, calculation methodology, dual Scope 2 reporting, Scope 3 category definitions |
| GRI 305: Emissions 2016 | **SECONDARY — voluntary disclosure** | Supplemental KPI alignment; GRI 305-1/305-2/305-3/305-4 |
| IPCC Sixth Assessment Report (AR6) GWP100 | **PRIMARY — GWP values** | CH4 = 27.9, N2O = 273; AR5 retained for legacy regeneration only |
| ISO 14064-1:2018 | **REFERENCE** | Aligns with GHG Protocol; referenced for assurance documentation |
| EU Taxonomy (Delegated Regulation 2021/2139) | **OUT OF SCOPE v1 — flagged** | Alignment assessment to be scheduled post-v1 |
| SBTi Corporate Standard | **OPEN QUESTION — OI-1** | Target pathway undecided; requirements deferred |
| SFDR PAI indicators | **OUT OF SCOPE v1** | Not applicable for issuer-level tool; investor-facing only |

**Constraint**: GWP sets must never be mixed within a single report run. AR6 is the default. AR5 regeneration is supported as a separate, clearly labelled run for legacy comparison only.

---

## 5. Organizational & Operational Boundary

### 5.1 Boundary Method

**Operational control** — per GHG Protocol Corporate Standard Chapter 4. The company accounts for 100% of emissions from operations over which it has operational control.

### 5.2 Entities In Scope

| Codice_Sito | Role | Geography |
|---|---|---|
| IANO | Main production site; largest GHG emitter; sole site with Processo_Decarb (CaCO3 decarbonation) | Italy |
| VIANO | Secondary production site | Italy |
| VIANO_GARGOLA | Secondary production site | Italy |
| CASALGRANDE | Secondary production site | Italy |
| FIORANO | Secondary production site | Italy |
| SASSUOLO | Secondary production site; sole site with non-GO grid electricity in 2024 (46,786 kWh EE_Acquistata_Grid) | Italy |
| FRASSINORO | Secondary production site; second largest electricity consumer (8,716,707 kWh in 2024) | Italy |

### 5.3 Entities Explicitly Excluded

- Joint ventures: **none present** — confirmed by user.
- Non-consolidated participations: **none present** — confirmed by user.
- Upstream parent entities or holding companies: out of boundary unless separately confirmed.

### 5.4 Base Year

2024 (consolidated, all 7 sites, all fuel types present in raw data). Recalculation policy: a structural change (acquisition, divestiture) or methodology change resulting in a >5% shift in base-year total Scope 1+2 tCO2e triggers mandatory base-year recalculation (see FR-26).

---

## 6. Reporting Boundary by Scope

### 6.1 Scope 1 — Direct Emissions

| Sub-category | Status | Sites | Data Source (2024 rows / 2025 rows) |
|---|---|---|---|
| Gas Naturale (GAS_NAT, Sm³) — combustion | **IN** | All 7 | 7 records / 7 records |
| Gasolio_Auto (GASOLIO, litres) — mobile combustion | **IN** | All 7 | 7 records / 7 records |
| Benzina_Auto (BENZINA, litres) — mobile combustion | **IN** | SASSUOLO only | 1 record / 1 record |
| Processo_Decarb (PROCESSO_DECARB, kg CaCO3) — process emissions | **IN** | IANO only | 1 record (9,363,616 kg CaCO3) / 1 record (9,061,067 kg CaCO3) |

**Process emissions methodology**: stoichiometric factor 0.4397 tCO2 / t CaCO3, classified as "Scope 1 — Process emissions", reported separately from combustion in all outputs. Source data quality: `E` (Estimated, via LOI 3.5% method) — flagged for assurance review.

**Scope 1 raw record count**: 32 data rows across 2024 and 2025 in `scope1_combustione.csv` (header excluded). 2024: 16 rows covering all 7 sites. 2025: 16 rows covering all 7 sites.

**Notable 2025 data point**: VIANO_GARGOLA Gas_Naturale 2025 = 11 Sm³ (vs expected hundreds of thousands). This near-zero value must be flagged as a DQ anomaly and investigated by data-quality-agent in Phase 3 (see DQ-CRIT-04).

### 6.2 Scope 2 — Indirect Energy Emissions

Dual reporting is **mandatory** and non-negotiable per GHG Protocol Scope 2 Guidance. LB and MB are never aggregated; they are always reported as separate, labelled values.

| Voice | Status | Notes |
|---|---|---|
| EE_Acquistata_GO (kWh, with Guarantees of Origin) | **IN — MB instrument** | All 7 sites both years; GO certificates must satisfy GHG Protocol Scope 2 Quality Criteria (see OI-4) |
| EE_Acquistata_Grid (kWh, no GO) | **IN — LB and MB residual mix** | SASSUOLO: 46,786 kWh in 2024; 0 kWh confirmed in 2025 (full switch to 100% GO contract, user-confirmed 2026-05-13). ETL inserts explicit zero row. |

**Scope 2 raw record count**: 15 native data rows in `scope2_elettricita.csv` (header excluded) + 1 ETL-synthesised zero row = 16 total in staging. 2024: 8 rows (7 sites GO + 1 SASSUOLO Grid). 2025: 7 native rows (7 sites GO only) + 1 ETL-synthesised explicit `EE_Acquistata_Grid = 0 kWh` row for SASSUOLO with provenance flag `auto_zero_user_confirmed` (per user confirmation of 100% GO contract switch). Synthesised row neutralises DQ-CRIT-05 (temporal gap) while preserving auditability.

**Known risk — 2025 VIANO electricity**: VIANO EE_Acquistata_GO 2025 = 3,268,364 kWh vs 2024 = 6,551,604 kWh, representing approximately 50% reduction. Flagged as suspected incomplete data. Investigation deferred to Phase 3 / data-quality-agent (OI-2).

**Location-based (LB) factor**: ISPRA Italia electricity grid emission factor for Italy (primary source). IEA as backup.
**Market-based (MB) factor**: 0 tCO2e/MWh for GO-covered volumes (subject to Quality Criteria validation — OI-4); ISPRA residual mix for EE_Acquistata_Grid volumes.

### 6.3 Scope 3 — Value Chain Emissions

**Confirmed IN** (activity data present in `scope3_categorie.csv`):

| Category (GHG Protocol) | Subcategories Present | Method | 2024 rows | 2025 rows |
|---|---|---|---|---|
| Cat 1 — Purchased goods and services | Argille, Feldspati, Sabbie silicee, Fritte/smalti, Pigmenti, Additivi chimici, Imballaggi cartone, Pallet legno, Film plastico, Reggette PP, Servizi vari (4 lines) | Mass-based + spend-based | 15 records | 14 records |
| Cat 2 — Capital goods | Impiantistica, Materiali di consumo | Spend-based | 2 records | 2 records |
| Cat 3 — Fuel and energy-related (WTT + T&D) | WTT Gas Naturale, WTT Gasolio, WTT Benzina, WTT Elettricità (generazione), T&D Losses Elettricità | Activity-based | 5 records | 5 records |
| Cat 4 — Upstream transportation | Argille (road/rail/sea), Feldspati (road/sea), Sabbie silicee (road/sea), Fritte e smalti (road), Pigmenti (road), Additivi chimici (road), Imballaggi cartone (road), Pallet legno (road), Film plastico (road), Reggette PP (road) | Distance-based (tkm) | 14 records | 14 records |
| Cat 5 — Waste generated in operations | Rifiuti pericolosi/non pericolosi: discarica + riciclo | Mass-based | 4 records | 4 records |
| Cat 6 — Business travel | Voli, Auto noleggio, Hotel | Spend-based | 3 records | 3 records |
| Cat 7 — Employee commuting | Commuting_Auto | Distance-based | 1 record (506 dipendenti, 4,452,800 km) | 1 record (484 dipendenti, 4,259,200 km) |
| Cat 9 — Downstream transportation | Italia_Strada, Europa_Strada, Export_Nave | Distance-based (tkm) | 3 records | 3 records |
| Cat 12 — End-of-life treatment of sold products | Piastrelle_Discarica (30%), Piastrelle_Riciclo (70%) | Mass-based (proxy) | 2 records | 2 records |

**Total Scope 3 raw record count**: 101 data rows across 2024 and 2025 in `scope3_categorie.csv` (header excluded). 9 categories present across both years.

**Cat 4 note**: Feldspati_Treno and Sabbie silicee_Treno are present in both years with Quantità = 0 tkm. These zero-quantity records must be retained as explicit disclosures (no rail transport used for these materials) and not treated as data gaps.

**Confirmed OUT — Cat 11 (Use of sold products)**:

Omitted with documented immateriality rationale: ceramic tiles (gres porcellanato) are passive products with no operational energy consumption during use phase. Cat 11 must appear as a disclosed line in ESRS E1-6 output with status "Omitted — Immaterial" and the above rationale. Zero value reported.

**Pending materiality assessment (Phase 2 — sustainability-expert-agent)**:

| Category | Rationale for Pending Status |
|---|---|
| Cat 8 — Upstream leased assets | No upstream leased assets identified; pending confirmation |
| Cat 10 — Processing of sold products | Tiles sold to distributors/customers; downstream processing undetermined |
| Cat 13 — Downstream leased assets | No downstream leased assets identified; pending confirmation |
| Cat 14 — Franchises | No franchise operations identified; pending confirmation |
| Cat 15 — Financed emissions | No financial instruments held; pending confirmation |

Default proposal for Phase 2: omit Cat 8/10/13/14/15 pending materiality assessment. Each omission must be disclosed in ESRS E1-6 with reason code.

---

## 7. KPIs

| KPI ID | Metric | Unit | ESRS E1-6 Mapping | Source Type | Disaggregation |
|---|---|---|---|---|---|
| KPI-01 | Scope 1 Gross (Combustion) | tCO2e | E1-6 §44(a) — Gross Scope 1 | Computed | By site, by fuel type, by year |
| KPI-02 | Scope 1 Gross (Process — Decarbonation) | tCO2e | E1-6 §44(a) — Gross Scope 1, sub-type "Process" | Computed | IANO only, by year |
| KPI-03 | Scope 1 Gross (Total = KPI-01 + KPI-02) | tCO2e | E1-6 §44(a) | Computed | By site, by year |
| KPI-04 | Scope 2 Location-Based (LB) | tCO2e | E1-6 §44(b) — Gross Scope 2 LB | Computed | By site, by year |
| KPI-05 | Scope 2 Market-Based (MB) | tCO2e | E1-6 §44(b) — Gross Scope 2 MB | Computed | By site, by year |
| KPI-06 | Scope 3 by Category (Cat 1–9, 12) | tCO2e | E1-6 §44(c) — Gross Scope 3 per category | Computed | By category, subcategory, year |
| KPI-07 | Total Gross Emissions (Scope 1 + 2 LB + 3) | tCO2e | E1-6 §44 aggregate | Computed | By year |
| KPI-08 | Total Gross Emissions (Scope 1 + 2 MB + 3) | tCO2e | E1-6 §44 aggregate (MB variant) | Computed | By year |
| KPI-09 | Intensity: tCO2e per tonne produced | tCO2e / t product | E1-6 §45 — Intensity ratios | Computed | By year; numerator = KPI-07 (LB) and KPI-08 (MB) |
| KPI-10 | Intensity: tCO2e per M€ revenue | tCO2e / M€ | E1-6 §45 | Computed | By year |
| KPI-11 | Intensity: tCO2e per FTE | tCO2e / FTE (headcount) | E1-6 §45 | Computed | By year; FTE = employee headcount confirmed by user (2024: 506, 2025: 484; official HR figure 2026-05-13). "FTE" here = total headcount; if a future strict FTE (part-time-weighted) value differs, a correction row will be inserted. |
| KPI-12 | Scope 2 GO Coverage | % kWh covered by GO | Disclosure — GHG Protocol Scope 2 Quality | Reference | By site, by year |
| KPI-13 | Facility Coverage Rate | % of sites with complete data | Data quality disclosure | Reference | By scope, by year |
| KPI-14 | Scope 3 Cat 3 — WTT + T&D emissions | tCO2e | E1-6 §44(c) Cat 3 | Computed | By energy carrier, by year |
| KPI-15 | YoY change Scope 1+2 (LB) | % change vs base year 2024 | E1-6 trend disclosure | Computed | By year |

**Notes**:
- Revenue (EUR) and production tonnage must be provided as reference inputs by the data steward; they are not derived from the CSV files.
- FTE count (506 in 2024, 484 in 2025) confirmed by user 2026-05-13 as official HR employee headcount, not proxy-derived. The commuting-distance-derived figure used in earlier drafts is consistent with the HR figure (cross-check: 4,452,800 km ÷ 8,800 km/FTE/yr ≈ 506; 4,259,200 km ÷ 8,800 km/FTE/yr ≈ 484). Treat as primary input, not estimate.
- GWP set used in all computations must be stated in every KPI output header.

---

## 8. Functional Requirements

| ID | Title | Description | Acceptance Criteria | Priority | Owner Agent |
|---|---|---|---|---|---|
| FR-01 | Raw data ingestion — Scope 1 | Ingest `scope1_combustione.csv`; validate schema (columns, data types, allowed Codice_Sito values, allowed Categoria_S1/Combustibile pairs, non-negative Quantità) using pandera schema; reject invalid rows to DLQ with error code. | All 32 data rows loaded or DLQ-ed with reason; no silent data loss; idempotent on re-run. | MUST | data-engineer |
| FR-02 | Raw data ingestion — Scope 2 | Ingest `scope2_elettricita.csv`; validate schema; enforce allowed Voce_S2 values; ETL auto-inserts an explicit `EE_Acquistata_Grid = 0 kWh` row for SASSUOLO 2025 (user-confirmed 100% GO contract switch) with provenance flag `auto_zero_user_confirmed`, so DQ-CRIT-05 temporal-gap does not fire; flag VIANO 2025 ~50% kWh reduction as DQ-WARN-01 (OI-2). | All 15 native data rows loaded; 1 ETL-synthesised zero-row inserted with provenance tag; VIANO 2025 anomaly triggers DQ-WARN-01; idempotent on re-run. | MUST | data-engineer |
| FR-03 | Raw data ingestion — Scope 3 | Ingest `scope3_categorie.csv`; validate schema; allow zero-quantity rows (Cat 4 rail entries) as valid explicit disclosures; enforce allowed Categoria_S3 values (1–15). | All 101 data rows loaded or DLQ-ed; zero-tkm records retained, not filtered. | MUST | data-engineer |
| FR-04 | Versioned emission factor catalog | Maintain a versioned, read-only (post-publish) factor catalog table with columns: factor_id, substance, scope, category, source (DEFRA/ISPRA/IEA/ecoinvent/EXIOBASE/IPCC/EPD), version, gwp_set, value, unit, valid_from, valid_to, created_by, notes. Source cascade enforced per Section methodology constraints. | Catalog entries are immutable after publish; updates create new version; every factor has a unique (factor_id, version, gwp_set) key. | MUST | data-engineer |
| FR-05 | Scope 1 combustion calculation | Calculate tCO2e for Gas_Naturale, Gasolio_Auto, and Benzina_Auto using DEFRA factors, AR6 GWP. Output includes CO2, CH4, N2O components. Link each output row to raw row ID and factor_id + version. | Calculation reproducible to 6 significant figures; all output rows carry factor_source, factor_version, gwp_set, methodology, calc_timestamp, created_by, correlation_id. | MUST | data-analyst |
| FR-06 | Scope 1 process emissions calculation | Calculate tCO2e for Processo_Decarb (IANO only) using stoichiometric factor 0.4397 tCO2/t CaCO3. Classify as "Scope 1 — Process emissions" in all outputs, separate from combustion. | Factor applied only to IANO rows; output labelled "Process emissions" in all reports; factor_source = "IPCC AR6 stoichiometric", factor_version documented. | MUST | data-analyst |
| FR-07 | Scope 2 location-based (LB) calculation | Calculate Scope 2 LB tCO2e using ISPRA Italia grid emission factor (primary) or IEA (backup) for all kWh consumed per site per year. | LB and MB are always separate columns/rows in DB and reports; never aggregated. LB factor source and version documented. | MUST | data-analyst |
| FR-08 | Scope 2 market-based (MB) calculation | Calculate Scope 2 MB tCO2e: apply 0 tCO2e/MWh for EE_Acquistata_GO volumes (pending GO Quality Criteria validation — OI-4); apply ISPRA residual mix for EE_Acquistata_Grid volumes (SASSUOLO 2024). | MB calculation blocked if GO Quality Criteria not validated (Phase 2 gate); residual mix factor sourced from ISPRA; no LB/MB mixing. | MUST | data-analyst |
| FR-09 | Scope 3 Cat 1 calculation | Calculate tCO2e for purchased goods (mass-based: ecoinvent v3.10 primary, superseded by supplier EPD where available) and services (spend-based: EXIOBASE/CDP sector ratios). | All mass-based subcategories use ecoinvent; all spend-based subcategories use EXIOBASE; EPD override documented per supplier in factor catalog. | MUST | data-analyst |
| FR-10 | Scope 3 Cat 2 calculation | Calculate tCO2e for capital goods (Impiantistica, Materiali di consumo) using spend-based method with EXIOBASE/CDP sector ratios. | Factor source and sector classification documented for each spend line. | MUST | data-analyst |
| FR-11 | Scope 3 Cat 3 calculation | Calculate WTT and T&D loss emissions for Gas Naturale, Gasolio, Benzina (DEFRA WTT factors) and Electricity (DEFRA/IEA WTT + T&D factors). **Fuel input quantities are derived from Σ Scope 1 fuel data per facility/year (NOT from the Cat 3 CSV `Quantità` column).** Electricity input = Σ kWh consumed per Scope 2 (LB basis). Discrepancy between CSV-provided Cat 3 quantity and Σ Scope 1 fuel is logged as DQ finding for audit trail (e.g. GAS_NAT 2024: CSV Cat 3 = 33,149,422 Sm³ vs Σ Scope 1 = 28,149,392 Sm³, delta +18% — Scope 1 is source of truth). | WTT factors from DEFRA current year; T&D loss factor from ISPRA/IEA; WTT fuel calculated on Σ Scope 1 fuel quantity per facility/year; WTT Electricity calculated on total kWh consumed (LB basis); source-of-truth reconciliation rule documented in methodology.md; CSV Cat 3 fuel quantity column retained as informational + DQ delta logged. | MUST | data-analyst |
| FR-12 | Scope 3 Cat 4 calculation | Calculate tCO2e for upstream transport using distance-based method (tkm × DEFRA mode-specific freight factors). Handle road, rail, and sea modes. Zero-tkm rows produce 0 tCO2e (not NULL). | DEFRA freight factors by mode; zero-tkm rows produce explicit 0.0 tCO2e; all tkm and mode documented. | MUST | data-analyst |
| FR-13 | Scope 3 Cat 5 calculation | Calculate tCO2e for waste generated in operations using mass-based method. Separate factors for landfill (pericolosi/non-pericolosi) and recycling. | Waste type × disposal route matrix; factors sourced from DEFRA or ecoinvent; recycling credit methodology documented (avoided emissions vs allocation). | MUST | data-analyst |
| FR-14 | Scope 3 Cat 6 calculation | Calculate tCO2e for business travel (Voli spend-based, Auto noleggio spend-based, Hotel spend-based) using DEFRA spend-based factors. | DEFRA factors for each travel type; currency denomination (EUR) documented; spend-based methodology noted as lower accuracy. | MUST | data-analyst |
| FR-15 | Scope 3 Cat 7 calculation | Calculate tCO2e for employee commuting (Commuting_Auto distance-based) using DEFRA car factors. FTE count (506 in 2024, 484 in 2025) is the official HR employee headcount (user-confirmed 2026-05-13). km/FTE/year (8,800) remains an estimation input. | Factor = DEFRA average car; FTE from HR (confirmed 2026-05-13); km/FTE estimation basis documented; any change to FTE requires recalculation and new row with superseded_by. | MUST | data-analyst |
| FR-16 | Scope 3 Cat 9 calculation | Calculate tCO2e for downstream transport (Italia_Strada, Europa_Strada, Export_Nave) using distance-based method and DEFRA freight factors by mode (HGV road, transoceanic sea). | Mode-specific DEFRA factors; tkm source methodology (proxy sectorial, load factor 27t) documented; market share percentages stored as metadata. | MUST | data-analyst |
| FR-17 | Scope 3 Cat 12 calculation | Calculate tCO2e for end-of-life treatment using mass-based method. Discarica 30% / Riciclo 70% split from proxy sectoral data. Factor source: ecoinvent v3.10. | Split percentages stored as assumptions in metadata; ecoinvent v3.10 factor referenced; zero credit for recycling unless recycled content method explicitly chosen. | MUST | data-analyst |
| FR-18 | Cat 11 zero-line disclosure | Scope 3 Cat 11 must appear in all ESRS E1-6 outputs as an explicit disclosed line with value 0 and rationale: "Omitted — Immaterial: ceramic tiles are passive products with no operational energy consumption during use phase." | Cat 11 line present in every ESRS E1-6 table; rationale text stored in disclosure_notes field; auditor-visible. | MUST | data-analyst |
| FR-19 | GWP set enforcement | System enforces a single GWP set (AR6 default: CH4=27.9, N2O=273) per report run. AR5 regeneration (CH4=25, N2O=298) supported as a separate, explicitly labelled run. Mixed GWP sets within a single report are a hard block. | Run metadata includes gwp_set field; validation rejects mixed sets; AR5 runs produce output clearly labelled "AR5 — legacy comparison only". | MUST | data-engineer |
| FR-20 | Append-only emission storage | All calculated emissions stored in `emissions_consolidated` table per schema in Section 10. Insert only; UPDATE and DELETE blocked by DB trigger. | Trigger verified by test (attempt UPDATE → exception); DQ checks pass pre-insert; no orphan rows. | MUST | data-engineer |
| FR-21 | Restatement / correction workflow | Corrections to prior-year data create a new row with updated values; the superseded row receives superseded_by = new row's ID and valid_to = correction timestamp. | Old row accessible in full history; new row identifiable as correction; API endpoint /corrections returns full chain; reason_code is mandatory. | MUST | data-engineer |
| FR-22 | Audit trail traceability | Every emission row in `emissions_consolidated` carries: raw_row_id (FK to ingestion table), factor_id + factor_version, gwp_set, methodology, calc_timestamp, created_by, correlation_id (UUID linking batch run). | Auditor can trace any tCO2e value back to the original CSV row and the factor applied; no unlinked rows permitted. | MUST | data-engineer |
| FR-23 | Streamlit dashboard — drill-down | Dashboard exposes 5-level drill-down: Scope → Site → Category → Year → Subcategory. All charts are colorblind-safe (Okabe-Ito or equivalent). Tooltips on data points expose: factor_source, factor_version, gwp_set, methodology. | Drill-down navigation functional for all in-scope categories; tooltip data sourced from DB metadata fields; palette verified against WCAG contrast AA aspirational. | MUST | visualization |
| FR-24 | Dashboard — YoY comparison | Dashboard includes dedicated YoY view comparing 2024 (base year, consolidated) vs 2025 (partial — flagged with data quality warning banner if OI-2 unresolved). | YoY delta (absolute tCO2e and %) shown per scope and category; 2025 VIANO anomaly displayed with DQ warning annotation. | MUST | visualization |
| FR-25 | Dashboard — intensity metrics | Dashboard displays KPI-09 (tCO2e/t produced), KPI-10 (tCO2e/M€ revenue), KPI-11 (tCO2e/FTE) with reference input fields for production tonnage and revenue. | Intensity ratios update dynamically from reference inputs; FTE sourced from HR reference table; all intensities show both LB and MB Scope 2 variants. | MUST | visualization |
| FR-26 | Recalculation policy trigger | System detects and flags when a structural change (site acquisition/divestiture) or methodology change causes >5% shift in base-year (2024) Scope 1+2 total tCO2e. Triggers mandatory base-year recalculation workflow. | Automated comparison post-recalculation; if delta > 5% threshold, workflow creates notification to esg_manager and data_steward; reason_code required. | MUST | data-engineer |
| FR-27 | Excel multi-sheet export | Export workbook with sheets: (1) Emissions by Scope, (2) Emissions by Site × Year, (3) Scope 3 by Category, (4) Audit Trail (raw_row_id, factor, gwp_set per row), (5) Factor Catalog Snapshot, (6) Metadata (run ID, timestamp, gwp_set, version). | Export generated on demand by esg_manager or data_steward; file locked for edit (xlsx protection); all sheets reference same correlation_id. | MUST | visualization |
| FR-28 | CSRD-ready PDF report | Generate PDF with ESRS E1-6 tables: §44(a) Scope 1 (combustion + process split), §44(b) Scope 2 LB + MB, §44(c) Scope 3 by category including Cat 11 disclosure, §45 intensity ratios. Document header includes gwp_set, base year, boundary statement, assurance level. | PDF passes visual review by ESG manager; all mandatory ESRS E1-6 data points present; Cat 11 rationale text included; assurance level = "ISAE 3000 Limited" stated. | MUST | visualization |
| FR-29 | FastAPI — read endpoints | REST API exposes GET endpoints for: /emissions (filterable by scope, site, year, category), /kpis, /audit-trail, /factor-catalog. JWT authentication required on all endpoints. RBAC enforced: auditor = read-only, esg_manager = read + trigger export, data_steward = read + write. | All endpoints return JSON; unauthorized requests return 401; forbidden role requests return 403; API documented via OpenAPI 3.1 spec. | SHOULD | backend |
| FR-30 | FastAPI — append-only write endpoint | REST API exposes POST /emissions (data_steward role only) for programmatic ingestion from future ERP/CRM systems. Enforces same validation and append-only rules as batch ETL. | POST accepts valid payload, inserts to `emissions_consolidated`, returns row ID and correlation_id; attempt to POST with missing mandatory metadata fields returns 422; no direct DB writes bypassing API validation. | SHOULD | backend |
| FR-31 | RBAC enforcement | Three roles enforced at application and DB levels: `auditor` (read-only all), `esg_manager` (read + export + approve), `data_steward` (read + ingest + manage factor catalog). PostgreSQL Row-Level Security (RLS) enforces tenant isolation. | Penetration test scenario: auditor attempts to insert emission row → blocked at API (403) and DB (RLS deny); data_steward cannot approve/sign off PDF (esg_manager only). | MUST | backend |
| FR-32 | Data quality gate execution | DQ gates listed in Section 11 execute as pre-insert validation in the batch ETL pipeline. CRIT-level failures block the pipeline and write to DLQ with structured error payload. WARN-level failures annotate rows but allow processing. | All DQ-CRIT conditions block insertion; DLQ entries include: rule_id, row_id, value, threshold, timestamp; esg_manager and data_steward notified. | MUST | data-engineer |
| FR-33 | Internationalization — IT/EN labels | All user-facing labels, report headers, and dashboard text support both Italian and English. Domain-standard Italian terms (Codice_Sito, Sm³, Gasolio, etc.) retained in Italian in both modes. | Language toggle in dashboard; PDF report generated in selected language; EN is default for API responses. | SHOULD | visualization |

---

## 9. Non-Functional Requirements

| ID | Category | Description | Metric / Target |
|---|---|---|---|
| NFR-01 | Performance | Annual batch ETL run (all scopes, all sites, both years) completes within target time. | < 10 minutes wall-clock on reference hardware (4 vCPU, 16 GB RAM, PostgreSQL local) |
| NFR-02 | Performance | Dashboard initial load time after cold start. | < 5 seconds for top-level scope view |
| NFR-03 | Performance | PDF report generation time. | < 60 seconds |
| NFR-04 | Performance | Excel export generation time. | < 30 seconds |
| NFR-05 | Security | JWT authentication on all API endpoints; no anonymous access. | alg=none rejected; token expiry enforced (max 1h access token, 24h refresh); HS256 minimum, RS256 preferred |
| NFR-06 | Security | RBAC enforced at API middleware and PostgreSQL RLS level on every request. | Zero unauthorized writes in penetration test scenario; RLS policy tested in CI |
| NFR-07 | Security | Input validation on all ingestion paths using pandera schemas. | Invalid rows rejected to DLQ, never silently coerced; SQL injection vectors blocked |
| NFR-08 | Security | No PII in application logs; secret detection in CI. | gitleaks scan in GitHub Actions pipeline; structured logs exclude personal identifiers; GDPR Art. 6/9/30 compliance |
| NFR-09 | Security | OWASP Top 10 mitigation on all FastAPI endpoints. | Addressed: A01 Broken Access Control (RBAC+RLS), A02 Cryptographic Failures (TLS, JWT RS256), A03 Injection (pandera + parameterized queries), A07 Auth Failures (expiry, alg=none), A09 Logging (PII-free) |
| NFR-10 | Security | TLS 1.2+ on all network interfaces; no plaintext HTTP in production. | TLS enforced in Docker Compose / deployment config; HTTP→HTTPS redirect |
| NFR-11 | Security | Rate limiting on API endpoints to prevent abuse. | Max 100 req/min per authenticated user; 429 response on breach |
| NFR-12 | Reliability | ETL pipeline is idempotent; re-running with same input produces identical output without duplicates. | Idempotency key = (Codice_Sito, Anno, Categoria, Combustibile, correlation_id); duplicate detection pre-insert |
| NFR-13 | Reliability | Dead-letter queue (DLQ) captures all failed rows with structured error payload; failed runs are replayable. | DLQ persisted to DB; replay endpoint available to data_steward; no data loss on partial failure |
| NFR-14 | Reliability | Append-only immutability proven by automated test in CI. | pytest test: attempt UPDATE on emissions_consolidated → assert DB exception raised |
| NFR-15 | Maintainability | Test coverage thresholds enforced in CI. | Global: ≥ 85%; emission calculation modules: 100% |
| NFR-16 | Maintainability | Function length and cyclomatic complexity limits. | Max 50 lines per function; max cyclomatic complexity 15 (enforced via flake8-cognitive-complexity or radon) |
| NFR-17 | Maintainability | Python version constraint. | Python 3.11+ only; pinned in pyproject.toml / Dockerfile |
| NFR-18 | Traceability | Every row in `emissions_consolidated` links to its source raw row. | raw_row_id FK enforced; orphan rows blocked by DB constraint; verifiable by auditor via /audit-trail endpoint |
| NFR-19 | Retention | Emissions data retained for minimum 10 years per CSRD requirement. | DB backup policy documented; row-level retention metadata; no delete cascade on emission tables |
| NFR-20 | Compliance | GDPR Art. 30 processing register maintained; DPIA completed where required. | Art. 30 register exists as living document; DPIA triggered if employee PII (FTE, commuting) stored at individual level |
| NFR-21 | Compliance | Append-only property proven by anti-mutation DB trigger. | Trigger definition in migration; CI test validates trigger behaviour; documented in assurance package |
| NFR-22 | Accessibility | Dashboard uses colorblind-safe palette throughout. | Okabe-Ito 8-color palette (or equivalent); verified with WCAG contrast ratio tools; WCAG AA aspirational for text contrast |
| NFR-23 | Internationalization | All user-facing strings externalised to locale files (IT/EN). | No hardcoded non-domain strings in Python/JS; locale files version-controlled |
| NFR-24 | Operability | Docker Compose deployment for local development; Docker images for production. | docker compose up produces a running stack (DB + API + dashboard) in < 5 min on clean environment |
| NFR-25 | Operability | GitHub Actions CI/CD pipeline: lint → test → coverage → build → security scan. | Pipeline must pass on every PR; gitleaks, bandit, pytest, coverage enforced as required checks |

---

## 10. Audit Trail & Immutability Requirements

### 10.1 Table: `emissions_consolidated`

This table is the single source of truth for all calculated emissions. It is **append-only**. No UPDATE or DELETE is permitted under any circumstances.

**Schema (mandatory columns)**:

| Column | Type | Description |
|---|---|---|
| id | UUID | Primary key, generated server-side |
| correlation_id | UUID | Links all rows from a single batch run |
| raw_row_id | UUID FK | References the originating row in the ingestion staging table |
| scope | INT | 1, 2, or 3 |
| sub_scope | VARCHAR | e.g., "combustion", "process", "LB", "MB", "Cat1", "Cat3_WTT" |
| codice_sito | VARCHAR | Facility code; NULL for corporate-level Scope 3 rows |
| anno | INT | Reporting year |
| tco2e | DECIMAL(14,6) | Calculated emission value |
| co2_tonne | DECIMAL(14,6) | CO2 component (nullable for non-combustion) |
| ch4_tco2e | DECIMAL(14,6) | CH4 component in CO2e (nullable) |
| n2o_tco2e | DECIMAL(14,6) | N2O component in CO2e (nullable) |
| factor_id | VARCHAR | FK to factor catalog |
| factor_version | VARCHAR | Catalog version at time of calculation |
| factor_source | VARCHAR | Source label (DEFRA, ISPRA, IEA, ecoinvent, EXIOBASE, IPCC, EPD) |
| gwp_set | VARCHAR | "AR6" or "AR5" |
| methodology | VARCHAR | e.g., "stoichiometric", "spend-based", "distance-based", "activity-based" |
| calc_timestamp | TIMESTAMPTZ | UTC timestamp of calculation |
| created_by | VARCHAR | Authenticated user or service account |
| valid_from | TIMESTAMPTZ | Bitemporal: when this row became the valid record |
| valid_to | TIMESTAMPTZ | NULL = current; set when superseded |
| superseded_by | UUID FK | NULL = active; set to ID of replacement row on correction |
| reason_code | VARCHAR | Mandatory on correction rows; NULL on original rows |
| disclosure_notes | TEXT | Narrative for ESRS disclosure (mandatory for Cat 11, optional otherwise) |

### 10.2 Immutability Enforcement

- A `deny_update_delete` trigger on `emissions_consolidated` raises an exception on any UPDATE or DELETE attempt.
- The trigger must be created in a DB migration, tested in CI (pytest: assert trigger fires), and documented in the assurance package for the external auditor.
- Bitemporal design (valid_from / valid_to) supports point-in-time queries for historical audit without mutation.

### 10.3 Correction Workflow

1. Data steward identifies error in emission row R1.
2. New row R2 is inserted with corrected values; all metadata fields required.
3. R1 is updated with: `valid_to = now(), superseded_by = R2.id, reason_code = <code>`. (This is the only permitted quasi-update, implemented as a single DB function with audit logging, not a general UPDATE permission.)
4. Correction reason codes: `DATA_ERROR`, `FACTOR_UPDATE`, `BOUNDARY_CHANGE`, `METHODOLOGY_REVISION`, `RESTATEMENT_>5PCT`.
5. All correction chains are traversable via the /corrections API endpoint.

### 10.4 Retention

All emission records retained for a minimum of **10 years** from the reporting year, per CSRD Article 19a and delegated acts. Retention enforced at DB level; backup policy to be documented by IT Operations.

---

## 11. Data Quality Gates

Gates executed as pre-insert validation in the batch ETL pipeline. CRIT = pipeline block + DLQ. WARN = row annotation + notification.

| ID | Level | Rule | Threshold | Trigger |
|---|---|---|---|---|
| DQ-CRIT-01 | CRIT | Facility coverage: all 7 sites must have at least one record for each in-scope scope per reporting year. | Coverage < 7/7 sites (< 100% for Scope 1 and Scope 2 per year) | Block pipeline; notify esg_manager |
| DQ-CRIT-02 | CRIT | Missing values: mandatory columns (Quantità, Unità, Codice_Sito, Anno) must not be NULL or empty. | Any NULL in mandatory column | Block row; write to DLQ |
| DQ-CRIT-03 | CRIT | Negative physical values: Quantità < 0 for any fuel, electricity, or mass quantity. | Quantità < 0 | Block row; write to DLQ |
| DQ-CRIT-04 | CRIT | Outlier detection: z-score > 4 on site × fuel × year quantity vs. population of same site × fuel across known years. | \|z\| > 4 | Block row; write to DLQ with z-score value; flag VIANO_GARGOLA GAS_NAT 2025 = 11 Sm³ as known candidate |
| DQ-CRIT-05 | CRIT | Temporal gap: site is present in 2024 but absent in 2025 (or vice versa) without explicit zero-quantity record. | Site × scope present in year T but missing in year T+1 (no zero record) | Block pipeline; require explicit zero record or DQ waiver by esg_manager |
| DQ-WARN-01 | WARN | VIANO electricity 2025 approximately 50% of 2024 value (3,268,364 vs 6,551,604 kWh). | Ratio VIANO EE 2025 / VIANO EE 2024 < 0.6 | Annotate row; banner warning in dashboard; referenced in OI-2 |
| DQ-WARN-02 | WARN | Process emission data quality = "E" (Estimated). IANO Processo_Decarb uses internal estimate via LOI 3.5%. | Qualità_Dato = "E" | Annotate row with quality flag; disclose estimation methodology in PDF report |
| DQ-WARN-03 | WARN | Spend-based Scope 3 subcategories (services, Cat 2, Cat 6) carry higher inherent uncertainty. | Metodo = "Spend-based" | Annotate rows; disclose uncertainty level in ESRS E1-6 |
| DQ-WARN-04 | WARN | Proxy-based Scope 3 subcategories (Cat 7 commuting, Cat 9, Cat 12) use sector estimates. | Qualità_Dato = "E" or Fonte_Dato = "Proxy settoriale" or "Stima interna" | Annotate rows; disclose proxy methodology and assumptions |
| DQ-WARN-05 | RESOLVED | SASSUOLO EE_Acquistata_Grid 2025 confirmed = 0 kWh by user 2026-05-13 (full GO contract). ETL inserts explicit 0-row with provenance `auto_zero_user_confirmed`. Rule retained in catalog for future analogous cases. | N/A | No runtime alert; audit history preserved |

**Reference to Phase 3**: Full data quality audit (completeness, accuracy, consistency, timeliness) is delegated to data-quality-agent in Phase 3. DQ gates in this section represent the minimum blocking conditions for Phase 2 calculation work to proceed.

---

## 12. Compliance Gates

Hard gates that must be resolved in design before any production deployment.

| ID | Gate | Consequence if Unmet |
|---|---|---|
| CG-01 | GDPR Art. 30 processing register exists and is current. | Block production deployment |
| CG-02 | DPIA completed if employee-level PII (individual FTE commuting data) is stored in the system. | Block production deployment |
| CG-03 | Audit trail is provably append-only: deny_update_delete trigger tested in CI. | Block CSRD submission |
| CG-04 | Every row in `emissions_consolidated` carries factor_source, factor_version, gwp_set, methodology. NULL in any of these fields is rejected by DB constraint. | Block pipeline insert |
| CG-05 | 10-year data retention policy implemented and documented. | Block CSRD submission |
| CG-06 | All mandatory ESRS E1-6 data points present in PDF report: Gross Scope 1 (incl. process/combustion split), Gross Scope 2 LB, Gross Scope 2 MB, Gross Scope 3 by category, intensity ratios, GWP reference, base year, boundary statement. | Block CSRD submission |
| CG-07 | Scope 3 Cat 11 zero-line with immateriality rationale present in every ESRS E1-6 output. | Block CSRD submission |
| CG-08 | GO certificates for Scope 2 MB validated against GHG Protocol Scope 2 Quality Criteria (contract instrument, no double counting, vintage matching, geographic matching). | Block MB = 0 claim; fallback to residual mix until validated (OI-4) |
| CG-09 | GWP set (AR6) documented in report header; AR5 runs clearly labelled as legacy. | Block report publication |
| CG-10 | EU Taxonomy alignment assessment — out of scope for v1; a placeholder disclosure must state "EU Taxonomy alignment: assessment deferred to v2" in the PDF report. | WARN — not a production block for v1, but must appear in report |
| CG-11 | ISAE 3000 Limited assurance scope agreed with assurance provider before Phase 2 closes. | Block external assurance engagement |

---

## 13. Security Gates

| ID | Gate | Standard Reference |
|---|---|---|
| SG-01 | All API endpoints require JWT; alg=none and expired tokens rejected. | OWASP A07, RFC 7519 |
| SG-02 | RBAC enforced at API middleware level and DB RLS level independently (defence in depth). | OWASP A01 |
| SG-03 | PostgreSQL RLS policies restrict each RBAC role to permitted rows and operations. | Single-tenant v1; design must accommodate future multi-tenant row isolation. |
| SG-04 | All DB queries use parameterized statements; no string interpolation in SQL. | OWASP A03 |
| SG-05 | Input validation via pandera on all ingestion paths; FastAPI Pydantic models on all API inputs. | OWASP A03 |
| SG-06 | TLS 1.2+ enforced on all network interfaces; HTTP redirects to HTTPS in production. | OWASP A02 |
| SG-07 | No PII logged in application logs (employee names, individual travel amounts if linked to person). Structured logging with explicit PII exclusion rules. | GDPR Art. 9, OWASP A09 |
| SG-08 | gitleaks secret detection runs in GitHub Actions on every PR and push; no secrets in version control. | OWASP A02 |
| SG-09 | bandit static analysis runs in CI; HIGH severity findings block merge. | OWASP A03/A05 |
| SG-10 | Rate limiting: 100 req/min per authenticated user; 429 with Retry-After header. | OWASP A04 |
| SG-11 | Docker images built from pinned base images; Dependabot or equivalent for dependency CVE scanning. | OWASP A06 |
| SG-12 | Separation of duties: data_steward cannot approve CSRD PDF; esg_manager cannot ingest raw data files directly. | Internal control principle |

---

## 14. Out of Scope — v1

The following are explicitly deferred and must not be designed into v1 architecture without a formal requirements change:

1. **Multi-tenancy**: single-tenant v1; architecture must not prevent future multi-tenant extension (schema-per-tenant design preferred, but not required for v1).
2. **Real-time / streaming emissions monitoring**: annual batch ETL only; no Kafka, no CDC, no rolling restatement.
3. **Mobile application**: no mobile-specific UI; responsive web is aspirational only.
4. **SBTi target validation workflow**: target pathways not yet committed (OI-1); no SBTi-specific data models or calculation logic in v1.
5. **Individual-product LCA**: no SKU-level Scope 3 Cat 11; corporate-level Cat 11 disclosed as zero with rationale.
6. **Scope 4 avoided emissions**: not a GHG Protocol Scope; explicitly excluded from all reports.
7. **Financed emissions (Scope 3 Cat 15)**: excluded unless Phase 2 materiality assessment determines otherwise (OI-3).
8. **EU Taxonomy alignment scoring**: assessment deferred; placeholder disclosure only in PDF.
9. **SFDR PAI indicators**: not applicable for this tool in v1.
10. **Automated regulatory update ingestion**: factor catalog updates are manual, performed by data_steward.

---

## 15. Open Issues

Issues that remain unresolved and must not be closed by any agent without explicit user or domain-expert input.

| ID | Description | Owner | Resolution Phase | Blocking? |
|---|---|---|---|---|
| OI-1 | SBTi alignment: does the company intend to commit to a 1.5°C pathway? Target year 2030/2035/2050? This determines whether SBTi-specific data models (sectoral decarbonization approach for ceramics) are needed in future versions. | sustainability-expert-agent + user | Post-v1 / Phase 9 documentation | No — v1 unblocked |
| OI-2 | 2025 data completeness: VIANO EE_Acquistata_GO 2025 = 3,268,364 kWh vs 2024 = 6,551,604 kWh (~50% reduction). Suspected incomplete data ingestion rather than genuine operational change. 2025 report cannot be consolidated until this is resolved. Also: VIANO_GARGOLA GAS_NAT 2025 = 11 Sm³ (anomalous near-zero). | data-quality-agent | Phase 3 | Yes — blocks 2025 YoY report sign-off |
| OI-3 | Scope 3 Cat 8 (upstream leased assets), Cat 10 (processing of sold products), Cat 13 (downstream leased assets), Cat 14 (franchises), Cat 15 (financed emissions): materiality assessment required. Default proposal: omit with rationale. Each omitted category must be disclosed in ESRS E1-6. | sustainability-expert-agent | Phase 2 | No — 2024 report can proceed with omission disclosures |
| OI-4 | Scope 2 GO Quality Criteria validation: existing GO certificates must be reviewed against GHG Protocol Scope 2 Guidance criteria (contract instrument type, no double counting, vintage matching ≤ 1 year, geographic matching Italy). Until validated, MB calculation with 0 tCO2e/MWh for GO volumes is blocked; residual mix applies. | sustainability-expert-agent | Phase 2 | Yes — blocks Scope 2 MB = 0 claim |
| OI-5 | Emission factor source cascade adequacy for the ceramic sector: confirm DEFRA factors are appropriate for Italian-context transport and fuel; confirm ecoinvent v3.10 ceramic material datasets (argille, feldspati) are sector-representative; identify available supplier EPDs to supersede generic factors. | sustainability-expert-agent | Phase 2 | No — calculations can proceed with cascade; EPD supersession updates factors catalog post-Phase 2 |
| OI-6 | GWP set confirmation: AR6 is the default per IPCC and aligns with CSRD/ESRS E1. Confirm whether the sector regulator (Confindustria Ceramica, EU ETS authority for IANO if applicable) or any sectoral reporting protocol mandates AR5 for specific reporting streams. Clarify AR5 regeneration retention period (10 years? Indefinite?). | sustainability-expert-agent | Phase 2 | No — AR6 is the working assumption; AR5 regeneration is available |

---

## 16. Acceptance Criteria for Phase 1 Sign-Off

Before Phase 2 (methodology validation and factor assignment) begins, the user must confirm:

| AC-ID | Criterion | Confirmed? |
|---|---|---|
| AC-01 | Organizational boundary (operational control, 7 sites, no JVs) is correct and complete. | Confirmed in brief |
| AC-02 | 2024 is the base year; 2025 is a secondary reporting year pending data quality resolution. | Confirmed in brief |
| AC-03 | Scope 3 Cat 11 omission with disclosed immateriality rationale is acceptable. | Confirmed in brief |
| AC-04 | ISAE 3000 Limited assurance is the target assurance level for 2024–2026 reporting cycle. | Confirmed in brief |
| AC-05 | GWP AR6 as default (CH4=27.9, N2O=273) is accepted; AR5 regeneration is a legacy tool only. | Confirmed in brief |
| AC-06 | Stoichiometric factor 0.4397 tCO2/t CaCO3 for IANO Processo_Decarb is validated by sustainability expert. | Pending Phase 2 — sustainability-expert-agent |
| AC-07 | Annual batch ETL (no streaming) is confirmed as the update frequency model. | Confirmed in brief |
| AC-08 | The 4-deliverable scope (dashboard, Excel, PDF, API) is confirmed with the relative priorities stated. | Confirmed in brief |
| AC-09 | Tech stack (Python 3.11+, FastAPI, Streamlit, PostgreSQL, pandera, pytest, Docker, GitHub Actions) is approved by IT Operations. | Pending IT Operations sign-off |
| AC-10 | Revenue (EUR) and production tonnage reference data for intensity metrics will be provided by the data steward before intensity KPI calculation in Phase 3. | Pending data steward commitment |
| AC-11 | FTE count (506 in 2024, 484 in 2025) is confirmed by user as official HR employee headcount; not proxy-derived. | Confirmed by user 2026-05-13 |
| AC-12 | OI-4 (GO Quality Criteria) will be resolved in Phase 2 before Scope 2 MB values are published. | Accepted as Phase 2 gate |

---

## 17. Traceability Matrix (FR → KPI → ESRS E1-6 Data Point)

| FR | FR Title (abbreviated) | KPI | ESRS E1-6 Data Point | Priority |
|---|---|---|---|---|
| FR-05 | Scope 1 combustion calc | KPI-01, KPI-03 | E1-6 §44(a) Gross Scope 1 | MUST |
| FR-06 | Scope 1 process emissions calc | KPI-02, KPI-03 | E1-6 §44(a) Gross Scope 1 — Process sub-type | MUST |
| FR-07 | Scope 2 LB calc | KPI-04, KPI-07 | E1-6 §44(b) Gross Scope 2 LB | MUST |
| FR-08 | Scope 2 MB calc | KPI-05, KPI-08 | E1-6 §44(b) Gross Scope 2 MB | MUST |
| FR-09 | Scope 3 Cat 1 calc | KPI-06 (Cat1) | E1-6 §44(c) Scope 3 Cat 1 | MUST |
| FR-10 | Scope 3 Cat 2 calc | KPI-06 (Cat2) | E1-6 §44(c) Scope 3 Cat 2 | MUST |
| FR-11 | Scope 3 Cat 3 calc | KPI-06 (Cat3), KPI-14 | E1-6 §44(c) Scope 3 Cat 3 | MUST |
| FR-12 | Scope 3 Cat 4 calc | KPI-06 (Cat4) | E1-6 §44(c) Scope 3 Cat 4 | MUST |
| FR-13 | Scope 3 Cat 5 calc | KPI-06 (Cat5) | E1-6 §44(c) Scope 3 Cat 5 | MUST |
| FR-14 | Scope 3 Cat 6 calc | KPI-06 (Cat6) | E1-6 §44(c) Scope 3 Cat 6 | MUST |
| FR-15 | Scope 3 Cat 7 calc | KPI-06 (Cat7), KPI-11 | E1-6 §44(c) Scope 3 Cat 7 | MUST |
| FR-16 | Scope 3 Cat 9 calc | KPI-06 (Cat9) | E1-6 §44(c) Scope 3 Cat 9 | MUST |
| FR-17 | Scope 3 Cat 12 calc | KPI-06 (Cat12) | E1-6 §44(c) Scope 3 Cat 12 | MUST |
| FR-18 | Cat 11 zero-line disclosure | — | E1-6 §44(c) Scope 3 Cat 11 — Omitted/Immaterial | MUST |
| FR-19 | GWP set enforcement | KPI-01 … KPI-08 | E1-6 §44 GWP reference (AR6) | MUST |
| FR-20 | Append-only storage | All KPIs | Assurance basis — immutability | MUST |
| FR-21 | Restatement workflow | All KPIs | ESRS E1 restatement disclosure | MUST |
| FR-22 | Audit trail traceability | All KPIs | Assurance basis — data lineage | MUST |
| FR-23 | Dashboard drill-down | KPI-01 … KPI-14 | Management reporting (not ESRS mandatory) | MUST |
| FR-24 | YoY comparison | KPI-15 | E1-6 trend (YoY change vs base year) | MUST |
| FR-25 | Intensity metrics | KPI-09, KPI-10, KPI-11 | E1-6 §45 Intensity ratios | MUST |
| FR-26 | Recalculation trigger | KPI-03, KPI-07, KPI-08 | ESRS E1 base-year recalculation disclosure | MUST |
| FR-27 | Excel export | All KPIs | Supplemental disclosure / audit support | MUST |
| FR-28 | CSRD PDF report | All KPIs | E1-6 primary output | MUST |
| FR-29 | FastAPI read endpoints | All KPIs | ERP/CRM integration (future) | SHOULD |
| FR-30 | FastAPI write endpoint | All KPIs | ERP/CRM integration (future) | SHOULD |
| FR-31 | RBAC enforcement | — | Assurance basis — access control | MUST |
| FR-32 | DQ gate execution | KPI-13 | Data quality disclosure | MUST |
| FR-33 | IT/EN internationalization | — | Accessibility / stakeholder usability | SHOULD |

---

*End of Document — Version 1.1.0 — 2026-05-13 — APPROVED (Phase 1 closed)*
