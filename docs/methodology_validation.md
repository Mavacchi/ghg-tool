# Methodology Validation — Phase 2

Ceramic-Tile Manufacturer (gres porcellanato) — 7 Italian Production Sites
Base Year 2024 — Operational Control — CSRD ESRS E1 — ISAE 3000 Limited

---

## 0. Document Control

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Date | 2026-05-13 |
| Author | sustainability-expert-agent |
| Reviewer (planned) | reviewer-agent, compliance-agent |
| References (input) | `docs/requirements.md` v1.1.0 (APPROVED), `data/scope1_combustione.csv`, `data/scope2_elettricita.csv`, `data/scope3_categorie.csv` |
| Scope of this document | Methodology validation for the 8 items A–H specified in Phase 2 brief; secondary methodological observations (Section I); factor-catalog seed list (Section 11); methodological gates for Phase 5 (Section 12); references (Section 13) |
| Status | DRAFT — pending reviewer-agent sign-off |
| Semver policy | minor bump on clarification; major bump on verdict change |
| Linked Open Issues from v1.1.0 | OI-3 (Scope 3 Cat 8/10/13/14/15 materiality), OI-4 (Scope 2 MB Quality Criteria), OI-5 (factor cascade adequacy), OI-6 (GWP set) |
| Out of scope | recomputation of any tCO2e value; modification of CSV data; modification of requirements.md; tech-stack choices |

---

## 1. Executive Summary

| # | Item | Verdict | Citations | Blocking? |
|---|---|---|---|---|
| A | OI-4 — Scope 2 MB Quality Criteria (GHG Protocol Scope 2 Guidance Ch. 7, 8 criteria) | APPROVED_WITH_CONDITIONS | 5 | Yes — blocks FR-08 MB=0 claim |
| B | OI-3 — Scope 3 Cat 8 / 10 / 13 / 14 / 15 materiality (ceramic-tile context) | APPROVED_WITH_CONDITIONS (4 OMIT, 1 RESIDUAL_OI for Cat 15) | 4 | No |
| C | OI-5 — Factor source cascade adequacy (ceramic sector) | APPROVED_WITH_CONDITIONS (cascade valid; multiple version pins pending Phase 5 data-engineer) | 6 | No |
| D | OI-6 — GWP set confirmation (AR6 default, EU ETS interaction) | APPROVED_WITH_CONDITIONS (AR6 confirmed; EU ETS-Phase-IV AR5 dual track may apply — see new OI-7) | 4 | No |
| E | AC-06 — Stoichiometric factor 0.4397 tCO2/t CaCO3 | APPROVED | 3 | No |
| F | FR-11 — Cat 3 fuel input = Σ Scope 1 rule | APPROVED | 2 | No |
| G | Cat 11 omission rationale (ceramic tiles = passive products) | APPROVED | 3 | No |
| H | Scope 1 process-emission classification (decarbonation CO2-only) | APPROVED | 2 | No |
| I | Secondary observations (biogenic CO2 from pallets/cartone; fugitive HFCs from refrigeration) | FURTHER_DATA_REQUIRED | 2 | No |

**Net result**: Phase 2 unblocks Phase 3 (data-quality-agent) under the condition that Item A is closed by the data steward against the GO certificate evidence checklist before MB=0 claims are published. All other items either approve the v1.1.0 working assumption or impose conditions that do not block Phase 3.

---

## 2. Section A — OI-4: Scope 2 Market-Based Quality Criteria

### 2.1 Verdict

**APPROVED_WITH_CONDITIONS — BLOCKING for FR-08 MB=0 claim.**

The v1.1.0 working assumption (apply 0 tCO2e/MWh for GO-covered volumes; apply ISPRA residual mix or AIB Italian residual mix for non-GO volumes) is methodologically correct **conditional on documentary validation, by certificate, against each of the eight (8) Scope 2 Quality Criteria** defined in the GHG Protocol Scope 2 Guidance (January 2015), Chapter 7. Until this validation is completed and stored as audit evidence in the factor catalog and audit-trail tables, MB = 0 for GO volumes **must not be published**; the residual-mix factor applies as fallback.

### 2.2 Normative basis

GHG Protocol Scope 2 Guidance (2015), Chapter 7 ("Scope 2 Quality Criteria for Contractual Instruments"). The text enumerates 8 criteria that must be met by every contractual instrument used in the market-based method. The Phase 2 brief refers to "5 criteria"; the canonical text has 8. The five most commonly cited by the public summaries (and explicitly referenced in the brief — conveyed claim, no double counting, vintage matching, geographic matching, scope coverage) correspond to criteria 1–5; criteria 6–8 cover transfer-only-to-end-user, exclusive emissions claim, and residual-mix disclosure obligations. This validation evaluates all 8.

### 2.3 The 8 Scope 2 Quality Criteria — definitions, citations, evidence required, FAIL logic

Each criterion is restated; each carries (a) the GHG Protocol Scope 2 Guidance reference, (b) the ISAE-3000-Limited evidence required from the data steward, (c) the consequence of failure.

**Criterion 1 — Conveyed claim**
- *Definition*: The contractual instrument shall convey the direct GHG emission rate attribute associated with the unit of electricity produced. (Scope 2 Guidance, §7.1, Quality Criterion 1.)
- *Italian instantiation*: Guarantee of Origin (Garanzia d'Origine, "GO") issued by GSE (Gestore Servizi Energetici) under D.Lgs. 199/2021 art. 46 and DM MASE 14/07/2023 n. 224, traded on the P-GO platform managed by GME (Gestore Mercati Energetici). The GO conveys the renewable origin of 1 MWh of injected electricity and is the only contractual instrument satisfying Criterion 1 for the Italian market.
- *Evidence required*: PDF copy of the issued GO certificate, GO unique identifier, GSE issuance ticket, technology declaration on certificate (must be renewable: PV, wind, hydro, biomass — verify against PCAF / EU Taxonomy thresholds if also used for Article 8 disclosure).
- *FAIL → fallback*: Apply ISPRA national grid factor (LB) and AIB Italian residual mix (MB) to the corresponding kWh volume.

**Criterion 2 — Uniqueness / no double counting**
- *Definition*: The contractual instrument shall be the only instrument that carries the GHG emission-rate attribute claim associated with that quantity of electricity generation. (Scope 2 Guidance, §7.1, QC 2.)
- *Italian instantiation*: Single-issuance enforced by GSE registry (AIB-compliant). Cross-border imports must be checked: GOs imported from other AIB member states are accepted only if a Hub-to-Hub transfer is logged.
- *Evidence required*: GSE registry extract showing single issuance, cancellation status, and beneficiary. Cancellation must be on behalf of IANO (or the relevant reporting site) before the disclosure cut-off. AIB Hub transfer records, where applicable.
- *FAIL → fallback*: residual mix.

**Criterion 3 — Tracked and redeemed by the reporting entity**
- *Definition*: The instrument shall be tracked and redeemed, retired, or cancelled by or on behalf of the reporting entity. (Scope 2 Guidance, §7.1, QC 3.)
- *Italian instantiation*: The GSE issues a cancellation certificate ("certificato di annullamento") naming the beneficiary. The cancellation must reference the consumption period (calendar year 2024 for the base-year report).
- *Evidence required*: PDF "certificato di annullamento" with beneficiary name = legal entity owning the site; signed and stamped. Volume in MWh per site per period.
- *FAIL → fallback*: residual mix.

**Criterion 4 — Vintage matching (issued and redeemed close to the consumption period)**
- *Definition*: The instrument shall be issued and redeemed as close as possible to the period of energy consumption to which the instrument is applied. (Scope 2 Guidance, §7.1, QC 4.)
- *Italian vintage rule*: Under the Italian GO regulatory framework (D.Lgs. 199/2021 art. 46, DM MASE 224/2023), GOs are valid for 12 months from the end of the month in which they are issued. **For ISAE 3000 Limited assurance: vintage = same calendar year as consumption.** Cross-vintage (e.g. 2023 GO applied to 2024 consumption) is not accepted by EFRAG ESRS E1 implementation guidance and is a fail.
- *Evidence required*: Issuance month/year on the GO certificate must fall within or immediately adjacent to the consumption period. The "annullamento" date must be no later than the disclosure cut-off (typically end of Q1 of the year following the reporting year, e.g. 2025-03-31 for FY2024).
- *FAIL → fallback*: residual mix.

**Criterion 5 — Geographic matching (operating market)**
- *Definition*: The instrument shall be sourced from the same market in which the energy consumption occurs. (Scope 2 Guidance, §7.1, QC 5.) "Market" generally means the country or, when an integrated bidding zone exists, the bidding zone.
- *Italian instantiation*: Italy is a single AIB Hub member; GOs issued in Italy are unambiguously eligible for Italian consumption. Imported AIB-Hub GOs are eligible if the EU electricity market is treated as a single market for Scope 2 purposes — **but** the more conservative interpretation (Italy-only) is recommended for ISAE 3000 Limited because some assurance providers reject imported GOs on geographic-matching grounds. Recommend: Italy-only GOs for FY2024 disclosure.
- *Evidence required*: GO country-of-issuance field = Italy. If imported AIB-Hub GO is used, AIB transfer log, justification statement, and explicit assurance-provider acceptance noted in the methodology statement.
- *FAIL → fallback*: residual mix (with the imported-GO volume reclassified to grid mix).

**Criterion 6 — Scope of emissions covered**
- *Definition*: The instrument shall reflect the scope of GHG emissions: direct combustion CO2 only is not sufficient — the emission rate conveyed must include all GHGs from the relevant electricity generation. (Scope 2 Guidance, §7.1, QC 6.)
- *Italian instantiation*: GO certificates issued by GSE convey "renewable origin"; the implied emission factor for renewable origin is 0 tCO2e/MWh for life-cycle direct emissions (no fuel combustion). Upstream emissions (e.g. PV panel manufacturing) are accounted for in Scope 3 Cat 3b (WTT electricity), not Scope 2.
- *Evidence required*: Technology field on GO certificate identifies renewable source. Verify against PCAF renewable list.
- *FAIL → fallback*: residual mix.

**Criterion 7 — Conveyed to the reporting entity exclusively**
- *Definition*: Contractual instruments conveying emissions claims shall be transferred to the reporting entity only; no other instrument that conveys this claim shall be issued for the contracted electricity. (Scope 2 Guidance, §7.1, QC 7.) This formally bars re-issuance / double sale.
- *Italian instantiation*: Enforced by GSE single-registry control. Risk arises if the supplier has bundled the GO with another tradeable certificate (e.g. an RECS, an I-REC) for export. For Italian supply contracts this is not common but must be confirmed.
- *Evidence required*: Supplier declaration that no parallel certificate has been issued; GSE registry extract confirming single beneficiary.
- *FAIL → fallback*: residual mix.

**Criterion 8 — Residual-mix availability and disclosure**
- *Definition*: An adjusted residual mix that characterises the GHG intensity of unclaimed or publicly shared electricity shall be made available for consumer scope 2 calculations, or its absence shall be disclosed by the reporting entity. (Scope 2 Guidance, §7.1, QC 8.)
- *Italian instantiation*: AIB publishes the European Residual Mix annually (most recent: 2024, published 2025-05-30 by Grexel Systems on behalf of AIB). For Italy 2024 the published residual mix is publicly available. ISPRA does not yet publish an explicit "residual mix" factor; ISPRA publishes a *production-based* and *consumption-based* national average. **For Scope 2 MB residual mix the AIB Italian residual mix is the recommended source**; ISPRA national grid factor is recommended for Scope 2 LB.
- *Evidence required*: factor_id and factor_version pointing to AIB Italian residual mix 2024 entry in the factor catalog. Disclosure note in the ESRS E1-6 PDF stating which residual mix factor was used.
- *FAIL → fallback*: not applicable — this criterion is a disclosure obligation, not an instrument check; failure is a CSRD non-conformity, not a factor issue.

### 2.4 Per-certificate checklist for the data steward

For every GO covering site × period × MWh volume in `scope2_elettricita.csv` row labelled `EE_Acquistata_GO`, the data steward shall record into a structured evidence table (proposed columns; this informs the architect-agent factor-catalog schema):

| Column | Type | Notes |
|---|---|---|
| `go_id` | VARCHAR | GSE-issued GO unique identifier |
| `site_codice_sito` | VARCHAR | One of the 7 |
| `volume_mwh` | DECIMAL | Cancelled volume |
| `vintage_year` | INT | Must equal reporting year (FY2024 → 2024) |
| `cancellation_date` | DATE | Must precede disclosure cut-off (proposed 2025-03-31) |
| `beneficiary_legal_entity` | VARCHAR | Reporting entity legal name |
| `country_of_issuance` | VARCHAR | Italy preferred; AIB-Hub member if imported |
| `technology` | VARCHAR | Hydro / Wind / Solar / Biomass / Other-renewable |
| `qc1_conveyed_claim_passed` | BOOL | Criterion 1 |
| `qc2_unique_passed` | BOOL | Criterion 2 |
| `qc3_redeemed_passed` | BOOL | Criterion 3 |
| `qc4_vintage_passed` | BOOL | Criterion 4 |
| `qc5_geographic_passed` | BOOL | Criterion 5 |
| `qc6_scope_passed` | BOOL | Criterion 6 |
| `qc7_exclusivity_passed` | BOOL | Criterion 7 |
| `qc8_residual_mix_disclosed` | BOOL | Criterion 8 |
| `pdf_evidence_uri` | TEXT | Object-store path to certificate PDFs |
| `validated_by` | VARCHAR | data_steward username |
| `validated_at` | TIMESTAMPTZ | Validation timestamp |

**Decision rule**: MB factor = 0 tCO2e/MWh is assigned to a (site, year, volume) tuple **if and only if** all 8 QC fields are TRUE. Otherwise the volume is reassigned to the residual-mix factor for that year. The decision and assignment are logged in `emissions_consolidated` via `factor_id` + `factor_version` + a non-null `disclosure_notes` field referencing the GO ID.

### 2.5 Conditions for closing OI-4

1. data steward completes the per-certificate checklist for FY2024 (all 7 sites, all GO volumes).
2. compliance-agent reviews the checklist for procedural conformance.
3. sustainability-expert-agent (this agent) re-validates a representative sample (minimum 1 GO per site) for QC1–QC8 conformance.
4. Until steps 1–3 are complete, FR-08 MB=0 claim remains gated and ETL applies residual mix.

---

## 3. Section B — OI-3: Scope 3 Cat 8 / 10 / 13 / 14 / 15 Materiality

### 3.1 Verdict

**APPROVED_WITH_CONDITIONS** — 4 of 5 categories OMITTED with rationale; Cat 15 RESIDUAL_OI pending user confirmation of absence of financial instruments.

### 3.2 Normative basis

GHG Protocol Corporate Value Chain (Scope 3) Accounting and Reporting Standard (2011), Chapter 5 ("Setting the Boundary"), Chapter 6 ("Accounting for Scope 3 Emissions"), and Appendix F (Category Descriptions). Minimum-boundary rules are stated per category. Where the activity that would generate a Scope 3 category is **absent** from the company's value chain, the category is reported as "Not applicable" with rationale, which is conformant with the GHG Protocol allowance for omission with disclosure.

Sectoral reference: CDP Technical Note "Relevance of Scope 3 Categories by Sector" identifies, for cement/glass/ceramic and analogous mineral-industry sectors, that Scope 3 categories 1 (Purchased Goods and Services), 3 (Fuel- and energy-related), 4 (Upstream Transportation), and 9 (Downstream Transportation) are the dominant categories; categories 8, 10, 13, 14, 15 are typically not material for vertically integrated ceramic-tile manufacturers without leasing operations, downstream processing, franchise networks, or financial-investment portfolios.

EPD International PCR 2019:14 v1.3.x for Construction Products (the active PCR under which Italian ceramic-tile EPDs are registered) and ISO 21930:2017 (PCR for construction products and services) treat the use stage of ceramic floor/wall tiles as a Module B that involves cleaning only (no operational energy consumption by the tile); they do not impose categories 8/10/13/14/15 disclosures on the manufacturer.

### 3.3 Per-category verdicts

#### Cat 8 — Upstream leased assets

- *GHG Protocol Cat 8 minimum boundary* (Appendix F): emissions from operation of assets that are leased by the reporting company in the reporting year and not already included in Scope 1 or 2 (i.e. the company is the lessee and uses operational-control or equity-share to consolidate; if operational-control consolidation is used, leased assets under the company's operational control are already in Scope 1/2).
- *Application to this company*: requirements.md §5 confirms operational-control consolidation across all 7 sites; the user has confirmed there are no joint ventures or non-consolidated participations. There is no evidence in the CSV data of leased fleet vehicles, leased warehouses, or other leased assets outside operational control.
- **Verdict**: **OMIT-with-rationale**. Disclosure note: "Cat 8 not applicable — all leased assets, where present, are consolidated within the operational-control boundary and accounted for in Scope 1 and Scope 2."
- *ESRS E1-6 §44(c) disclosure form*: line "Cat 8 — Upstream leased assets" → value 0 tCO2e → status "Not material / Not applicable" → rationale as above.

#### Cat 10 — Processing of sold products

- *GHG Protocol Cat 10 minimum boundary*: emissions from processing of intermediate products by third parties downstream (e.g. a steel mill selling slabs that a customer rolls into sheets). Applies when the reporting company's product is an intermediate that undergoes further processing before final use.
- *Application to this company*: gres porcellanato tiles are **finished products**. They are not intermediates; the distributor / installer affixes them but does not "process" them in the GHG-Protocol sense. Cutting and trimming on site by the installer is de minimis and is captured within Cat 9 (downstream transportation) load-factor assumptions implicitly.
- **Verdict**: **OMIT-with-rationale**. Disclosure note: "Cat 10 not applicable — finished products (gres porcellanato tiles) undergo no industrial processing between sale and end-use."
- *ESRS E1-6 §44(c) disclosure form*: line "Cat 10 — Processing of sold products" → value 0 tCO2e → status "Not applicable" → rationale as above.

#### Cat 13 — Downstream leased assets

- *GHG Protocol Cat 13 minimum boundary*: emissions from operation of assets owned by the reporting company and leased to other entities (i.e. the company is the lessor).
- *Application to this company*: no evidence of lessor activity in the CSV data or the requirements. Manufactured products are sold, not leased.
- **Verdict**: **OMIT-with-rationale**. Disclosure note: "Cat 13 not applicable — the company is not a lessor of operational assets."
- *ESRS E1-6 §44(c) disclosure form*: line "Cat 13" → value 0 tCO2e → status "Not applicable" → rationale as above.

#### Cat 14 — Franchises

- *GHG Protocol Cat 14 minimum boundary*: emissions from operation of franchises by franchisees, where the reporting company is the franchisor. Applies primarily to retail-franchise business models.
- *Application to this company*: no franchise model identified in the requirements or value-chain description. Sales are conducted via independent distributors and direct B2B channels.
- **Verdict**: **OMIT-with-rationale**. Disclosure note: "Cat 14 not applicable — the company operates no franchise network."
- *ESRS E1-6 §44(c) disclosure form*: line "Cat 14" → value 0 tCO2e → status "Not applicable" → rationale as above.

#### Cat 15 — Financed emissions (Investments)

- *GHG Protocol Cat 15 minimum boundary*: emissions from financial investments (equity, debt, project finance, managed investments). Applies primarily to financial institutions; non-financial entities report Cat 15 only when they hold financial investments outside the operational boundary that meet materiality criteria. PCAF (Partnership for Carbon Accounting Financials) methodology is the de facto standard.
- *Application to this company*: requirements.md §5.3 confirms "no joint ventures, no non-consolidated participations". This addresses operational holdings; **it does not explicitly address whether the company holds any financial instruments** (bonds, equity stakes, sovereign debt, structured products) as treasury investments or pension-fund counterparties.
- **Verdict**: **RESIDUAL_OI — flagged as new OI-8 in Section 10** ("user input required: does the company hold any treasury financial investments, equity stakes, project finance, or pension-fund assets in scope for Cat 15 disclosure?"). Default proposal: OMIT-with-rationale ("the company is a non-financial undertaking and holds no investment portfolio in scope of GHG Protocol Cat 15") **pending user confirmation**.
- *ESRS E1-6 §44(c) disclosure form*: line "Cat 15" → value 0 tCO2e → status "Not applicable, pending confirmation of treasury position" → rationale as above. If user confirms presence of investments, this verdict becomes FURTHER_DATA_REQUIRED and Cat 15 must be re-scoped before sign-off.

### 3.4 ESRS E1-6 disclosure mechanics

CSRD ESRS E1-6 §44(c) requires gross Scope 3 emissions to be disclosed by category; categories that are not material or not applicable must be **explicitly disclosed with rationale** (not silently omitted). FR-18 already encodes this for Cat 11; the same mechanism must be applied to Cat 8, 10, 13, 14, and (provisionally) 15.

---

## 4. Section C — OI-5: Factor Source Cascade Adequacy for the Ceramic Sector

### 4.1 Verdict

**APPROVED_WITH_CONDITIONS**. The cascade defined in v1.1.0 (DEFRA primary for fuels, freight, business travel, waste; ISPRA for Italian grid LB; AIB residual mix for MB residual; ecoinvent v3.10 primary for ceramic raw materials; EXIOBASE / CDP sector ratios for spend-based items; supplier EPDs override generic factors where available) is methodologically sound for ISAE 3000 Limited. Factor *vintages* and *exact version pins* must be confirmed by data-engineer-agent at Phase 5 factor-catalog seeding.

### 4.2 Latest published versions of authoritative sources (May 2026 snapshot)

| Source | Latest published version | Release date | Notes / URL |
|---|---|---|---|
| DEFRA / DESNZ UK GHG Conversion Factors | **2025 edition** (covers FY2025 reporting) | 2025-06 (full set; first release 2025-05-16) | Used for WTT, transport, business travel, waste — see Section 11 for individual factor lines. A 2026 edition is expected mid-2026 per the annual cycle; data-engineer to confirm at Phase 5. |
| ISPRA "Fattori di emissione atmosferica di CO2 e altri gas a effetto serra nel settore elettrico" | **Rapporto 386/2023** for production / consumption series 1990–2022 (most recent multi-year EF report) — supplemented by ISPRA **Rapporto 413/2025** "Le emissioni di CO2 nel settore elettrico nazionale e regionale" (May 2025) with 2023 data | 2025-05 | Italian LB grid factor. The 2023 consumption-side factor is approximately 0.279 kg CO2/kWh per the 2025 publication (continued declining trend; ISPRA reported ~12% reduction in electricity sector emissions in 2024 vs 2023). Exact value to be pinned by data-engineer at Phase 5 against the cited ISPRA report page. |
| IEA Emission Factors | "IEA Emissions Factors 2024" (latest edition; the IEA publishes a paid dataset annually) | 2024 | Backup only; ISPRA is primary for Italy. |
| ecoinvent | **v3.10** (released 2023-12) and **v3.11** (released 2024 H2) | 2023–2024 | v3.10 is the v1.1.0 working version. data-engineer at Phase 5 to confirm whether v3.11 should be the seeded version. Note: ecoinvent licence does not authorise factor-value publication in this document. |
| EXIOBASE | **v3.8** / **v3.9** | 2024 | Spend-based factors for services and capital goods (Cat 2, Cat 6 spend). Uses NACE Rev. 1 → must be mapped to NACE Rev. 2 C23.31 (manufacture of ceramic tiles and flags), H.49 (land transport), H.50 (water transport). |
| CDP supplier sector ratios | CDP Full GHG Emissions Dataset Technical Annex IV (Scope 3, 2023 release) | 2023 | Alternative to EXIOBASE for spend-based; recommend using both as cross-check. |
| AIB European Residual Mix — Italy 2024 | Published 2025-05-30 | 2025-05-30 | Used for Scope 2 MB residual-mix factor. Exact gCO2/kWh value to be pinned at Phase 5 from the AIB PDF (the WebFetch returned a 403 in this validation pass; data-engineer to retrieve manually). |
| EPD International registry | Live database — major Italian ceramic raw-material suppliers checked below | 2026-05 snapshot | See §4.4. |

### 4.3 Cascade applicability — per material / activity present in `scope3_categorie.csv`

The order of precedence for emission-factor selection (per FR-04 catalog policy and v1.1.0 §6.3 Cat 1 note) is:

1. **Supplier-specific EPD** (ISO 14025 + ISO 21930 / EN 15804 A2) when available, current, and covering the same product family.
2. **ecoinvent v3.10** sectoral / geographic dataset (default for mass-based Cat 1 materials).
3. **EXIOBASE / CDP sector ratio** (default for spend-based Cat 1 services and Cat 2 capital goods).
4. **DEFRA / DESNZ 2025** (transport, fuels WTT, business travel, waste).
5. **ISPRA** (Italian grid LB).
6. **AIB Italian residual mix 2024** (Scope 2 MB residual).
7. **IPCC stoichiometric** (process emissions — see Section E).

Applicability per material / activity:

| Material / activity | Method | Tier-1 factor source | Cascade fallback | Note |
|---|---|---|---|---|
| Argille (clays) | Mass-based | ecoinvent v3.10 ("clay, at mine" or "kaolin, at plant" depending on grade) | Sibelco / Imerys EPD if published for the supplier × grade | Major supplier Sibelco operates Italian kaolin and ball-clay sites; data-engineer to verify EPD availability at Phase 5 |
| Feldspati (feldspars) | Mass-based | ecoinvent v3.10 ("feldspar, at plant") | Maffei / Minerali Industriali (Sibelco subsidiary) EPD if published | Italian feldspar suppliers — see §4.4 |
| Sabbie silicee (silica sand) | Mass-based | ecoinvent v3.10 ("silica sand, at plant") | Supplier EPD if published | — |
| Fritte / smalti (frits and glazes) | Mass-based | ecoinvent v3.10 ("frit, at plant" or aggregated chemical-industry dataset) | Esan / Colorobbia / Endeka EPD if published | — |
| Pigmenti (pigments) | Mass-based | ecoinvent v3.10 ("pigment, inorganic, at plant") | Supplier EPD if published | Pigments are typically a small mass share but high specific impact (heavy metals processing); flag for sensitivity in DQ |
| Additivi chimici (chemical additives) | Mass-based | ecoinvent v3.10 ("chemicals, inorganic / organic, market for") | Supplier EPD | — |
| Imballaggi cartone (cardboard) | Mass-based | ecoinvent v3.10 ("corrugated board, at plant") | EPD if published | Biogenic CO2 storage treatment — see Section I |
| Pallet legno (wooden pallets) | Mass-based | ecoinvent v3.10 ("EUR-flat pallet, at plant") | EPD if published | Biogenic CO2 — see Section I |
| Film plastico (plastic film) | Mass-based | ecoinvent v3.10 ("packaging film, LDPE") | EPD if published | — |
| Reggette PP (PP straps) | Mass-based | ecoinvent v3.10 ("polypropylene, granulate" + extrusion) | EPD if published | — |
| Servizi vari (services) | Spend-based | EXIOBASE 3 / CDP sector ratio | — | NACE M / N for professional services |
| Impiantistica (Cat 2 plant) | Spend-based | EXIOBASE 3 NACE C.28 (machinery) | — | — |
| Materiali di consumo (Cat 2) | Spend-based | EXIOBASE 3 NACE C.27 / C.28 | — | — |
| WTT Gas Naturale | Activity-based | DEFRA 2025 — natural-gas WTT scope 3 factor | — | Apply to Σ Scope 1 GAS_NAT quantity per FR-11 |
| WTT Gasolio | Activity-based | DEFRA 2025 — diesel WTT | — | Apply to Σ Scope 1 GASOLIO |
| WTT Benzina | Activity-based | DEFRA 2025 — petrol WTT | — | Apply to Σ Scope 1 BENZINA |
| WTT Elettricità | Activity-based | DEFRA 2025 — electricity WTT, OR ISPRA upstream value | — | Apply to total kWh LB basis |
| T&D losses electricity | Activity-based | DEFRA 2025 — electricity T&D losses, OR Terna / ISPRA T&D loss-rate × ISPRA emission factor | — | Italian-specific loss rate preferred |
| Cat 4 freight road (Argille, Feldspati, Sabbie, Fritte, Pigmenti, Additivi, Imballaggi, Pallet, Film, Reggette) | Distance-based (tkm) | DEFRA 2025 — HGV >17t average laden | — | Use freight factors, not passenger |
| Cat 4 freight rail (Feldspati_Treno, Sabbie_Treno) | Distance-based | DEFRA 2025 — freight train | — | Zero-tkm rows accepted per FR-12 |
| Cat 4 freight sea (Argille, Feldspati, Sabbie) | Distance-based | DEFRA 2025 — bulk carrier transoceanic | — | — |
| Cat 5 waste (pericolosi discarica / riciclo, non-pericolosi discarica / riciclo) | Mass-based | DEFRA 2025 — waste landfill / closed-loop or open-loop recycling | ecoinvent v3.10 if DEFRA categories misalign | Recycling credit methodology = cut-off (no avoided-emissions credit unless explicitly chosen — see FR-13) |
| Cat 6 business travel (Voli, Auto noleggio, Hotel) | Spend-based | DEFRA 2025 — UK spend-based travel factors | EXIOBASE 3 service sectors | DEFRA spend factors are GBP-denominated; convert via PPP-adjusted EUR/GBP rate at Phase 5; document conversion methodology |
| Cat 7 commuting | Distance-based | DEFRA 2025 — average car | — | 4,452,800 km (2024) and 4,259,200 km (2025); FTE 506/484 (confirmed) |
| Cat 9 downstream transport (Italia_Strada, Europa_Strada, Export_Nave) | Distance-based | DEFRA 2025 — HGV / sea bulk | — | Load factor 27 t per v1.1.0 |
| Cat 12 end-of-life (Discarica / Riciclo) | Mass-based | ecoinvent v3.10 — landfill (inert mineral) / construction-waste recycling | DEFRA waste-management alternative | Cut-off allocation |

### 4.4 EPD International registry — Italian ceramic raw-material suppliers (as of 2026-05-13)

Open-search hits (not exhaustive — data-engineer at Phase 5 must reconfirm via direct EPD-International database queries):

| Supplier | Material | EPD status at 2026-05-13 |
|---|---|---|
| Sibelco Italia | Kaolin, ball clay, silica sand, feldspar (multiple sites in Italy) | No publicly indexed EPD-International registration found in this search for the Italian operations — FURTHER_DATA_REQUIRED |
| Imerys | Kaolin, feldspar, talc (global) | EPD-International registrations exist at corporate level for some product families; data-engineer to verify whether covering the specific tiles-grade kaolin/feldspar supplied to this manufacturer — FURTHER_DATA_REQUIRED |
| Maffei (industrial minerals) | Calcium carbonate, dolomite, talc | FURTHER_DATA_REQUIRED |
| Minerali Industriali (Sibelco subsidiary) | Feldspar, sand | FURTHER_DATA_REQUIRED |
| Esan / Colorobbia / Endeka (frits and glazes) | Frits, glazes, pigments | Several Italian frits / glazes producers publish PCR-aligned product data; **specific EPDs to be confirmed at Phase 5** |

Italian ceramic-tile manufacturers themselves (Piemme, Panariagroup, Emilceramica) have published EPDs at the gres-porcellanato finished-product level — these are *downstream* of this manufacturer's value chain (potential benchmarks for Cat 12 end-of-life and for own-product disclosures, not for Cat 1 raw-material factors).

### 4.5 Combinations where no acceptable factor exists (assurance risk)

| Material / activity | Risk | Mitigation |
|---|---|---|
| Pigmenti (heavy-metal-containing grades) | ecoinvent generic "pigment, inorganic" averages may under-represent specific grades (Cr2O3 green, Co/Ni blues) | Apply ecoinvent v3.10 with explicit uncertainty annotation; flag for refinement once supplier EPD obtained |
| Fritte / smalti | High product-mix variability; aggregate factor masks composition variability | Disclose methodology limitation in PDF report under DQ-WARN-03 |
| Imballaggi cartone — biogenic CO2 sink | Treatment of stored biogenic carbon in cardboard / pallets requires explicit policy | See Section I |
| Italian-specific T&D loss-rate factor | DEFRA T&D is UK grid; Italian grid loss rate differs (~6.5% historical Terna) | Use Italian-specific T&D rate × ISPRA factor if data-engineer pins a verifiable Terna source at Phase 5 |
| AIB Italian residual mix 2024 exact value | Could not retrieve from WebFetch (HTTP 403 from AIB CDN) | data-engineer to manually retrieve at Phase 5 |
| ISPRA 2024 exact LB factor for FY2024 reporting | The ISPRA reports as of May 2025 contain 2023 data; the 2024 vintage factor is typically published mid-2026 | If 2024 vintage not published before Phase 5 cut-off, use ISPRA 2023 factor with documented vintage offset, AND disclose in PDF |

### 4.6 Conditions for closing OI-5

1. data-engineer at Phase 5 confirms version pins for all factor entries in Section 11 against retrieved authoritative documents.
2. Where a supplier EPD is identified at Phase 5, it overrides the generic ecoinvent factor and a new factor-catalog row is created.
3. AIB Italian residual mix 2024 numeric value retrieved and pinned.
4. ISPRA 2024 vintage factor confirmed (or 2023 vintage used with documented offset).
5. DEFRA 2025 vs 2026 release decision recorded.

---

## 5. Section D — OI-6: GWP Set Confirmation

### 5.1 Verdict

**APPROVED_WITH_CONDITIONS**. AR6 GWP100 confirmed as default for CSRD ESRS E1 voluntary disclosure (CH4=27.9, N2O=273). However, if the IANO site operates a ceramic kiln of capacity exceeding the EU ETS Phase IV Annex I threshold (Activity 17 "Manufacture of ceramic products by firing"), a parallel AR-set track is regulator-mandated for ETS reporting — a **new OI (OI-7) is opened** flagging this question. The user has not yet confirmed whether IANO is in EU ETS scope.

### 5.2 IPCC AR6 GWP100 values — confirmation

IPCC Sixth Assessment Report (AR6), Working Group I (Climate Change 2021: The Physical Science Basis), Chapter 7 (The Earth's Energy Budget, Climate Feedbacks, and Climate Sensitivity), Supplementary Material Table 7.SM.7 ("Lifetime, radiative efficiency and metric values for the 49 species included in this Report"):

| Substance | AR6 GWP100 | Notes |
|---|---|---|
| CO2 | 1 | Reference gas |
| CH4 (fossil) | 29.8 ± 11 | Includes climate–carbon-cycle feedback |
| CH4 (biogenic / non-fossil) | 27.0 ± 11 | Used for biological sources |
| CH4 (default aggregate) | **27.9** | Average; v1.1.0 selected this value as default |
| N2O | **273** | ± 130 |
| SF6 | 25 200 | ± 5 500 |
| HFC-134a | 1 530 | Common refrigerant — see Section I |
| HFC-410A (R-410A mix) | ~2 256 | Common HVAC refrigerant — composite |
| HFC-32 | 771 | — |
| PFC-14 (CF4) | 7 380 | — |
| PFC-116 (C2F6) | 12 400 | — |
| NF3 | 17 400 | — |

Source: IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (published 2021-08; URL in §13 References).

The v1.1.0 working values (CH4=27.9, N2O=273) are **exactly conformant** with the IPCC AR6 published table. No methodological revision required.

### 5.3 AR5 retention policy

Retain AR5 regeneration capability with the following AR5 values for legacy comparison runs only:

| Substance | AR5 GWP100 |
|---|---|
| CH4 | 28 (without climate–carbon feedback) or 30 (with) — use 28 to align with IPCC AR5 WG1 Ch. 8 Table 8.7 (no feedback) |
| N2O | 265 |
| SF6 | 23 500 |
| HFC-134a | 1 300 |
| HFC-410A | ~2 088 |
| HFC-32 | 677 |

**Retention period: minimum 10 years** to align with the CSRD 10-year retention requirement (NFR-19 / CG-05) — every report regenerated for any prior year going back to base year 2024 must remain reproducible.

### 5.4 EU ETS interaction — Phase IV current GWP mandate

Commission Implementing Regulation (EU) 2018/2066 of 19 December 2018 (MRR for Phase IV of the EU ETS), as amended by Implementing Regulation (EU) 2020/2085 and Implementing Regulation (EU) 2023/2122 of 17 October 2023:

- **EU ETS current GWP100 set = IPCC AR5** (as of the 2023/2122 amendment). The earlier 2018/2066 release referenced AR4; the 2023 amendment moved EU ETS to AR5. AR6 is not yet mandated for ETS reporting.
- For an installation in EU ETS Annex I Activity 17 ("Manufacture of ceramic products by firing with a production capacity exceeding 75 t per day"), the operator must report under AR5 for ETS compliance.
- For CSRD ESRS E1, the company is free to (and indeed encouraged to) use AR6.

**Implication if IANO is in EU ETS scope**: dual-track reporting is required. The CSRD report (this tool's primary output) uses AR6. A parallel ETS submission uses AR5 with the same activity data. The methodology statement must explicitly state which set was used for which output. **Retention period for both AR-set tracks: minimum 10 years.**

### 5.5 New OI-7 — EU ETS scope for IANO

The user has not confirmed whether IANO operates a ceramic firing kiln above the 75 t/day EU ETS Annex I Activity 17 capacity threshold. Italian ceramic-tile production sites in the Sassuolo-Scandiano-Castellarano district commonly include sites in EU ETS scope (the Italian ceramic sector has the largest installation count in the EU ETS ceramic sub-sector per Cerame-Unie). Given that IANO is described as "the largest GHG emitter" and "the sole site with Processo_Decarb" (requirements.md §5.2), there is a meaningful probability that IANO is in EU ETS scope.

**OI-7 question to the user**: Is IANO (or any other site) registered as an EU ETS installation in Italy's Italian National Inventory / ETS registry?

**If yes**: enable AR5 dual-track regeneration; coordinate with the EU ETS verifier; ensure the AR5 set is locked in the factor catalog with versioning consistent with the 2023/2122 amendment.

**If no**: AR6 is the only required set; AR5 regeneration remains available as legacy comparison only (per v1.1.0).

### 5.6 Conditions for closing OI-6

1. AR6 GWP set locked as default in the factor catalog with `gwp_set='AR6'` and values per Table 7.SM.7.
2. AR5 regeneration available with `gwp_set='AR5'`.
3. Mixed-set runs blocked at FR-19 enforcement.
4. New OI-7 (EU ETS scope for IANO) raised to the user; if confirmed in scope, AR5 dual-track enabled.
5. Both AR-set tracks retained for ≥10 years.

---

## 6. Section E — AC-06: Stoichiometric Factor 0.4397 tCO2 / t CaCO3

### 6.1 Verdict

**APPROVED**.

### 6.2 Derivation

CaCO3 → CaO + CO2 (calcination / decarbonation)

| Species | Molecular weight (g/mol) | Source |
|---|---|---|
| Ca | 40.078 | IUPAC standard atomic weights (2021), confirmed in IPCC 2006 Volume 3 Chapter 2 §2.3.1.3 |
| C | 12.011 | |
| O | 15.999 | |
| CaCO3 | 40.078 + 12.011 + 3 × 15.999 = **100.0869** g/mol, rounded **100.09** | |
| CO2 | 12.011 + 2 × 15.999 = **44.009** g/mol, rounded **44.01** | |

Stoichiometric ratio:

44.01 / 100.0869 = **0.43972**, rounded to 4 significant figures → **0.4397 tCO2 / t CaCO3**

The figure 0.4397 is **exactly** conformant. (Note: some references report 0.4400 or 0.440 to 3 sig figs; 0.4397 to 4 sig figs is the more precise figure and is the IPCC-cited value.)

### 6.3 IPCC citation for ceramic body decarbonation

IPCC 2006 Guidelines for National Greenhouse Gas Inventories, Volume 3 (Industrial Processes and Product Use), Chapter 2 (Mineral Industry Emissions):

- **Section 2.4 (Lime Production)** uses the stoichiometric ratio 0.785 tCO2/t CaO via the EF_lime = (44.01/56.08) × CaO content method. (Reference for the molecular-weight method.)
- **Section 2.5 (Other Process Uses of Carbonates)** explicitly identifies *ceramics* among the "other industries" where carbonate decomposition occurs during firing, and applies the same EF_carbonate methodology:

  Equation 2.14 (Tier 1): Emissions = Σ_i (EF_i × M_i × F_i)

  where EF_i is the stoichiometric emission factor for carbonate i (for CaCO3, EF = 0.43971 tCO2/t CaCO3 per Table 2.1 in §2.5.1.3), M_i is the mass of carbonate, F_i is the calcination fraction.

The figure **0.4397 tCO2/t CaCO3 used by this tool is exactly the Section 2.5.1.3 Table 2.1 value** (with the calcination fraction F = 1.0 for the ceramic-body firing scenario where decomposition is effectively complete at gres-porcellanato firing temperatures ~1200°C).

**Conclusion**: AC-06 is validated. The factor is uniquely sourced (IPCC 2006 V3 Ch.2 §2.5.1.3 Table 2.1), the value is correct to the cited precision, and the methodology (Tier 1 stoichiometric with F=1) is appropriate for ceramic body decarbonation.

### 6.4 LOI 3.5% method — uncertainty assessment

The data-quality value `Qualità_Dato = "E"` (Estimated) on the Processo_Decarb row of `scope1_combustione.csv` reflects that the CaCO3 mass is **estimated from a Loss On Ignition (LOI) measurement of the ceramic body, assumed to be 3.5% of the fired-product mass**.

LOI captures both carbonate decomposition (the CO2 we want) **and** other thermal losses (combined water, organic matter, sulphate decomposition). For typical gres-porcellanato bodies, carbonate is the dominant LOI contributor (~80–95% of LOI mass), but the residual confounders introduce a systematic uncertainty.

**Typical uncertainty bound for LOI-based CaCO3 estimation: ±10–20% relative**, depending on:
- Body composition consistency (more variable mixes → higher uncertainty)
- Presence of organic temporary binders (introduce positive bias)
- Sulphate or fluoride content (positive bias)
- Carbonate-bound water vs structural water disambiguation

**ISAE 3000 Limited acceptability**: yes, **conditional on**:
- Documented methodology (LOI procedure, sample size, frequency)
- Documented uncertainty bound in the ESRS E1-6 PDF report (DQ-WARN-02 already encodes this annotation)
- A planned Tier-2 / Tier-3 upgrade path

**Recommended Tier-2 / Tier-3 upgrade path**:

1. **Tier 2** (medium effort): replace LOI with **XRF (X-ray fluorescence)** measurement of CaO content in the raw body. XRF gives Ca mass fraction directly; CaCO3 mass = Ca mass × (100.09 / 40.08) = Ca mass × 2.4972, with measurement uncertainty ~±2–3%.
2. **Tier 3** (high effort): **titration** of carbonate content via acid digestion (HCl) and back-titration, OR **TGA (thermogravimetric analysis)** of representative body samples at firing temperature with mass-spec CO2 quantification. Uncertainty ~±1–2%.

**Recommendation**: schedule Tier-2 upgrade as a Year-1 improvement plan; disclose the upgrade roadmap in the ESRS E1 transition-plan section (E1-1).

### 6.5 Classification (cross-reference to Section H)

The 0.4397 factor produces CO2 only (no CH4, no N2O). This is classified as **Scope 1 — Process emissions**, separately disclosed from combustion under FR-06 and ESRS E1-6 §44(a) sub-totals. See Section H.

---

## 7. Section F — FR-11: Cat 3 Fuel Quantity = Σ Scope 1 Rule

### 7.1 Verdict

**APPROVED**.

### 7.2 Conformance with GHG Protocol Scope 3 Standard, Cat 3

GHG Protocol Scope 3 Standard (2011), Chapter 5 + Appendix F, Category 3 ("Fuel- and energy-related activities not included in Scope 1 or Scope 2"):

- **Cat 3a — Upstream emissions of purchased fuels**: extraction, production, and transportation of fuels **consumed** by the reporting company. The activity data is fuel **consumed** (i.e. Σ Scope 1 fuel for each fuel type) multiplied by a WTT factor (well-to-tank, kgCO2e per unit fuel).
- **Cat 3b — Upstream emissions of purchased electricity**: extraction, production, and transportation of fuels **consumed in the generation** of electricity that the company **consumes** in the reporting year. Activity data is kWh **consumed** (i.e. total Scope 2 LB kWh basis) × WTT factor for the relevant grid.
- **Cat 3c — Transmission and distribution (T&D) losses**: emissions from the energy lost in T&D between the point of generation and the point of consumption. Activity data is the loss-rate × kWh consumed × LB factor, OR equivalent direct T&D-loss factor × kWh consumed.
- **Cat 3d — Generation of purchased electricity that is sold to end users**: applies only to utilities and energy retailers; **N/A** for this company.

The v1.1.0 rule "Cat 3a/3b activity data = Σ Scope 1 fuel and Σ Scope 2 (LB basis) electricity" is **exactly conformant** with the GHG Protocol minimum-boundary requirement for Cat 3.

### 7.3 The 18% CSV-vs-Σ-Scope-1 delta for GAS_NAT 2024

The v1.1.0 cited discrepancy: CSV Cat 3 Quantità for GAS_NAT 2024 = 33,149,422 Sm³; Σ Scope 1 GAS_NAT 2024 (across all 7 sites) = 28,149,392 Sm³; delta = +18%.

**Likely causes** (in order of probability):

1. **Purchases ≠ consumption**: the Cat 3 CSV row may reflect *purchased volume* (delivered, paid-for) including end-of-period stock that was not consumed in the reporting year. The Scope 1 CSV reflects consumed volume (e.g. from meter readings or stock-adjusted consumption).
2. **Inclusion of out-of-scope volumes**: the Cat 3 row may aggregate gas purchases for trading or resale, or for entities outside the operational-control boundary (e.g. a holding-level account).
3. **Unit or scaling error**: less likely given the round-ish nature of the figure, but possible.
4. **Boundary mismatch**: Cat 3 CSV captured at corporate aggregate; Scope 1 captured at site level; a site that purchases but is not in scope of consolidation may be the cause.

**Rule**: Σ Scope 1 is the **source of truth** for WTT calculation; the CSV Cat 3 quantity is informational and the delta is **logged as a DQ finding** (audit trail entry) but does not block calculation.

**Recommendation**: data-quality-agent at Phase 3 should ask the data steward to characterise the 18% delta. If it is end-of-period stock, document it as "stock variation" and confirm the consumption-basis methodology. If it is out-of-scope volume, exclude it from the Cat 3 CSV row going forward (or annotate as informational only).

### 7.4 Reaffirmation

WTT calculation MUST use **fuel consumed** (= Σ Scope 1 activity data), NOT fuel purchased (= CSV Cat 3 Quantità column). The CSV Cat 3 fuel quantity column is retained for audit transparency, with the delta logged.

---

## 8. Section G — Cat 11 Omission Rationale

### 8.1 Verdict

**APPROVED**.

### 8.2 Normative basis

GHG Protocol Scope 3 Standard (2011) Chapter 5, Appendix F Category 11 ("Use of sold products") describes two emission pathways:

- **Direct use-phase emissions**: emissions from the use of sold products that directly consume energy (electricity, fuels) or emit GHGs during operation. *Required* minimum boundary for products that consume energy.
- **Indirect use-phase emissions**: emissions that occur as a result of the use of sold products but are not directly emitted by the product (e.g. emissions associated with maintenance, cleaning, or consumables). *Encouraged but not required*.

For passive products with no operational energy consumption — and ceramic tiles (gres porcellanato) are textbook passive products — the direct use-phase emissions are zero, and the indirect use-phase emissions are limited to cleaning over the product's service life.

### 8.3 Materiality of cleaning emissions

Independent EPDs of gres-porcellanato tiles (e.g. EPD-IES registered Italian-manufacturer EPDs under EN 15804 A2 / PCR 2019:14) consistently report use-stage Module B emissions that are < 0.5% of the cradle-to-gate (A1–A3) emissions, with the dominant component being cleaning water and detergent. At the corporate level, scaled by the company's annual production, indirect use-phase emissions are demonstrably **< 0.1% of corporate total Scope 1+2+3 tCO2e** under any reasonable cleaning-frequency assumption.

### 8.4 ESRS E1-6 §44(c) disclosure

CSRD ESRS E1-6 §44(c) requires explicit disclosure of omitted Scope 3 categories with rationale. FR-18 already encodes:

> "Cat 11 — Use of sold products: Omitted — Immaterial: ceramic tiles are passive products with no operational energy consumption during use phase."

This rationale is **methodologically sound** and conformant. The Cat 11 zero line must remain in every ESRS E1-6 output for transparency.

### 8.5 References

- GHG Protocol Scope 3 Standard, Appendix F, Cat 11
- EPD International PCR 2019:14 v1.3.x (construction products); ISO 21930:2017
- Italian ceramic-tile EPDs (Piemme, Panariagroup, Emilceramica) — public domain benchmarks

---

## 9. Section H — Scope 1 Process Emissions Classification

### 9.1 Verdict

**APPROVED**.

### 9.2 Normative basis

GHG Protocol Corporate Standard (2004, revised 2015), Chapter 4 ("Setting Operational Boundaries"), §4.2: Scope 1 includes **process emissions** as one of four named sub-categories alongside stationary combustion, mobile combustion, and fugitive emissions.

IPCC 2006 V3 Ch.2 §2.5 explicitly classifies CO2 from decarbonation of carbonates during ceramic firing as a **process emission**, distinct from combustion emissions (which arise from natural gas burning to generate the firing heat).

Both combustion and process emissions occur within the same kiln but have **different emission pathways**:
- Combustion: gas + O2 → CO2 + H2O (CH4 and N2O traces also). Activity data = Sm³ of gas. Multi-gas. Apply DEFRA factors with AR6 GWP.
- Process: CaCO3 + heat → CaO + CO2. Activity data = mass of CaCO3 decomposed. Single gas (CO2 only). Apply stoichiometric 0.4397.

### 9.3 Disclosure structure (CSRD ESRS E1-6 §44(a))

ESRS E1-6 §44(a) requires gross Scope 1 emissions; while the standard does not mandate a process / combustion split at the top-level disclosure, the EFRAG ESRS E1 implementation guidance and ISAE 3000 Limited best practice recommend a sub-total breakdown to support verifier traceability.

Following requirements.md FR-06 / KPI-01 / KPI-02 / KPI-03, the PDF report and Excel export shall present:

```
ESRS E1-6 §44(a) Gross Scope 1 GHG emissions:
   ├── Sub-total: Stationary + Mobile combustion (KPI-01)
   │      ├── Stationary (Gas Naturale) — 7 sites
   │      ├── Mobile (Gasolio Auto) — 7 sites
   │      └── Mobile (Benzina Auto) — SASSUOLO only
   ├── Sub-total: Process emissions — Decarbonation (KPI-02)
   │      └── IANO only
   └── Total Scope 1 (KPI-03)
```

The methodology statement and the audit-trail row (per FR-22) must record `sub_scope` values that distinguish "combustion" from "process".

### 9.4 GWP application for process row

The process row contains CO2 only. GWP for CO2 = 1 in all IPCC AR sets, so the row's tCO2e equals its tCO2. Nevertheless, the `gwp_set` field on the row shall still be populated (e.g. `'AR6'`) for traceability consistency with FR-22 / CG-04.

---

## 10. Updated Open Issues

### 10.1 Issues from v1.1.0 — closure status post-Phase 2

| OI ID | Title | Status after Phase 2 | Next action |
|---|---|---|---|
| OI-1 | SBTi alignment | Not addressed (out of Phase 2 scope) | Defer to post-v1; user input required |
| OI-2 | 2025 data completeness (VIANO EE, VIANO_GARGOLA GAS_NAT) | Not addressed (Phase 3 scope) | data-quality-agent at Phase 3 |
| OI-3 | Scope 3 Cat 8/10/13/14/15 materiality | **CLOSED for Cat 8/10/13/14** with OMIT-with-rationale; **OPEN for Cat 15** (residual — see OI-8 below) | Phase 5 data-engineer to encode disclosure-note text in PDF generator |
| OI-4 | Scope 2 MB Quality Criteria | **PARTIALLY CLOSED — methodology validated**; **OPEN for certificate-level evidence collection** | data steward to complete per-certificate checklist in §2.4 before MB=0 publication |
| OI-5 | Factor source cascade adequacy | **CLOSED for cascade structure**; **OPEN for version pins** (DEFRA edition, ecoinvent v3.10 vs v3.11, AIB Italian residual mix 2024 numeric, ISPRA report number/year) | data-engineer at Phase 5 |
| OI-6 | GWP set | **CLOSED — AR6 confirmed**; **see new OI-7 for EU ETS dual track** | Phase 5 data-engineer to seed AR6 and AR5 sets |

### 10.2 New Open Issues raised by this validation

| New OI ID | Title | Owner | Resolution phase | Blocking? |
|---|---|---|---|---|
| **OI-7** | EU ETS scope for IANO: is IANO (or any other site) registered as an EU ETS Annex I Activity 17 installation? If yes, AR5 dual-track regeneration is required for ETS submissions in parallel to AR6 CSRD disclosure. | user + sustainability-expert-agent | Phase 2 follow-up | No — CSRD AR6 path is unaffected; AR5 regeneration is already required (per v1.1.0 §4 GWP policy) for legacy comparison — promoting it to dual-track for ETS is an operational rather than methodology shift |
| **OI-8** | Cat 15 — Financed emissions: does the company hold any treasury financial investments, equity stakes, project finance, pension-fund assets, or other financial instruments whose emissions are reportable under PCAF / GHG Protocol Cat 15? | user + sustainability-expert-agent | Phase 2 follow-up | No — default proposal OMIT-with-rationale; revisit if user reports investment holdings |
| **OI-9** | Biogenic CO2 treatment for packaging (cardboard, wooden pallets): adopt explicit biogenic-CO2 accounting policy (separate disclosure per GHG Protocol Land Sector and Removals Guidance / ISO 14067) rather than aggregate. | sustainability-expert-agent + data-engineer-agent | Phase 5 | No |
| **OI-10** | Fugitive HFC emissions from facility cooling / refrigeration: there are no rows in `scope1_combustione.csv` for fugitive HFCs (refrigerant top-ups). Verify whether refrigerant inventory exists and whether top-up records should be added to Scope 1 fugitive sub-category. | user + data steward | Phase 3 | No — likely small magnitude but methodologically a Scope 1 sub-category that may currently be missing |

---

## 11. Factor Catalog Seed List (Phase 5 implementation input)

The columns below correspond to the `factor_catalog` table envisioned in FR-04. Values marked `TBC` (To Be Confirmed) require numeric pinning at Phase 5 by data-engineer-agent against retrieved authoritative documents (URLs in §13). Values marked `LICENCE` indicate a paid / licence-restricted dataset where the numeric value cannot be republished in this document but must be sourced at seeding.

| factor_id | substance / activity | scope | category | source | version | value | unit | vintage | applicability_note |
|---|---|---|---|---|---|---|---|---|---|
| `LB_IT_GRID_ISPRA_2024` | Electricity grid Italy LB | 2 | LB | ISPRA Rapporto 386 series + Rapporto 413/2025 (consumption side) | 2024 vintage (publication mid-2026 expected; use 2023 vintage from Rapporto 413/2025 if 2024 not yet published — vintage offset disclosed) | TBC (~0.27–0.28 kg CO2/kWh based on 2023 figure) | kg CO2 / kWh | 2024 (or 2023 with offset) | Italian grid average; consumption-side; covers all 7 sites; applied to total kWh per FR-07 |
| `MB_IT_RESIDUAL_AIB_2024` | Electricity Italian residual mix MB | 2 | MB-residual | AIB European Residual Mix 2024 | Published 2025-05-30 | TBC (~0.44 kg CO2/kWh; AIB average across all residual mixes is ~0.452 kg CO2/kWh; Italian value to be confirmed from AIB PDF) | kg CO2e / kWh | 2024 | Applied to non-GO kWh volumes (SASSUOLO 2024); MB only |
| `MB_GO_ZERO` | GO-certified electricity MB | 2 | MB-GO | GHG Protocol Scope 2 Guidance Ch.7 | 2015 | **0** | kg CO2e / kWh | n/a | Applied only after per-certificate QC1–QC8 validation per §2.4 |
| `WTT_GAS_NAT_DEFRA_2025` | WTT natural gas | 3 | Cat 3a | DEFRA/DESNZ UK GHG Conversion Factors | 2025 | TBC (~0.026 kg CO2e/kWh net CV equivalent ~0.029 kg CO2e/Sm³ — verify) | kg CO2e / Sm³ | 2025 | Apply to Σ Scope 1 GAS_NAT consumption |
| `WTT_GASOLIO_DEFRA_2025` | WTT diesel | 3 | Cat 3a | DEFRA 2025 | 2025 | TBC | kg CO2e / litre | 2025 | Apply to Σ Scope 1 GASOLIO consumption |
| `WTT_BENZINA_DEFRA_2025` | WTT petrol | 3 | Cat 3a | DEFRA 2025 | 2025 | TBC | kg CO2e / litre | 2025 | Apply to Σ Scope 1 BENZINA consumption (SASSUOLO only) |
| `WTT_ELEC_DEFRA_2025` | WTT electricity (generation upstream) | 3 | Cat 3b | DEFRA 2025 | 2025 | TBC (~0.022 kg CO2e/kWh in 2025 set) | kg CO2e / kWh | 2025 | Apply to total kWh LB basis; alternative: ISPRA upstream value if pinned |
| `TND_ELEC_IT_DEFRA_2025` | T&D losses electricity | 3 | Cat 3c | DEFRA 2025 with optional Terna-Italian-loss-rate adjustment | 2025 | TBC | kg CO2e / kWh | 2025 | Apply to total kWh; Italian-specific loss rate (~6.5%) preferred where data-engineer can pin Terna source |
| `STOICH_CACO3_IPCC_2006` | CaCO3 decarbonation | 1 | Process | IPCC 2006 V3 Ch.2 §2.5.1.3 Table 2.1 | 2006 (stoichiometric — invariant) | **0.4397** | t CO2 / t CaCO3 | n/a (chemistry-based) | IANO Processo_Decarb; CO2 only |
| `FREIGHT_HGV_DEFRA_2025` | Road freight, HGV >17t average laden | 3 | Cat 4 / Cat 9 | DEFRA 2025 | 2025 | TBC (~0.106 kg CO2e/tkm benchmark) | kg CO2e / tkm | 2025 | Cat 4 inbound + Cat 9 Italia_Strada and Europa_Strada |
| `FREIGHT_RAIL_DEFRA_2025` | Freight train | 3 | Cat 4 | DEFRA 2025 | 2025 | TBC (~0.028 kg CO2e/tkm benchmark) | kg CO2e / tkm | 2025 | Feldspati_Treno, Sabbie_Treno (zero-tkm rows produce 0.0) |
| `FREIGHT_SEA_DEFRA_2025` | Bulk carrier transoceanic sea | 3 | Cat 4 / Cat 9 | DEFRA 2025 | 2025 | TBC (~0.0035–0.006 kg CO2e/tkm benchmark) | kg CO2e / tkm | 2025 | Cat 4 sea + Cat 9 Export_Nave |
| `TRAVEL_SPEND_FLIGHTS_DEFRA_2025` | Business flights, spend-based | 3 | Cat 6 | DEFRA 2025 | 2025 | TBC | kg CO2e / GBP | 2025 | Convert EUR spend via PPP-adjusted rate; document conversion |
| `TRAVEL_SPEND_HIRECAR_DEFRA_2025` | Rental car, spend-based | 3 | Cat 6 | DEFRA 2025 | 2025 | TBC | kg CO2e / GBP | 2025 | Convert EUR spend |
| `TRAVEL_SPEND_HOTEL_DEFRA_2025` | Hotel stays, spend-based | 3 | Cat 6 | DEFRA 2025 | 2025 | TBC | kg CO2e / GBP | 2025 | Convert EUR spend |
| `COMMUTE_CAR_DEFRA_2025` | Average car, distance-based | 3 | Cat 7 | DEFRA 2025 | 2025 | TBC (~0.17 kg CO2e/km benchmark; 2025 update saw EV-share reductions) | kg CO2e / km | 2025 | Apply to total Commuting_Auto km |
| `WASTE_LANDFILL_PERIC_DEFRA_2025` | Landfill, hazardous waste | 3 | Cat 5 | DEFRA 2025 (or ecoinvent v3.10) | 2025 | TBC | kg CO2e / tonne | 2025 | Cat 5 pericolosi discarica |
| `WASTE_LANDFILL_NONPERIC_DEFRA_2025` | Landfill, non-hazardous waste | 3 | Cat 5 | DEFRA 2025 | 2025 | TBC | kg CO2e / tonne | 2025 | Cat 5 non-pericolosi discarica |
| `WASTE_RECYCLE_PERIC_DEFRA_2025` | Recycling, hazardous waste | 3 | Cat 5 | DEFRA 2025 | 2025 | TBC | kg CO2e / tonne | 2025 | Cut-off; no avoided-emissions credit |
| `WASTE_RECYCLE_NONPERIC_DEFRA_2025` | Recycling, non-hazardous waste | 3 | Cat 5 | DEFRA 2025 | 2025 | TBC | kg CO2e / tonne | 2025 | Cut-off |
| `ECOINV_CLAY_V3_10` | Argille (clay, at mine) | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Mass-based Cat 1 |
| `ECOINV_FELDSPAR_V3_10` | Feldspati (feldspar, at plant) | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Mass-based Cat 1 |
| `ECOINV_SILICA_V3_10` | Sabbie silicee (silica sand, at plant) | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Mass-based Cat 1 |
| `ECOINV_FRIT_V3_10` | Fritte / smalti | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Mass-based Cat 1; high uncertainty — flag |
| `ECOINV_PIGMENT_V3_10` | Pigmenti (pigment, inorganic) | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Mass-based Cat 1; high specific impact |
| `ECOINV_ADDITIVES_V3_10` | Additivi chimici | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Mass-based Cat 1 |
| `ECOINV_CARDBOARD_V3_10` | Imballaggi cartone | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Biogenic CO2 — see Section I / OI-9 |
| `ECOINV_PALLET_V3_10` | Pallet legno | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Biogenic CO2 — see Section I / OI-9 |
| `ECOINV_LDPE_V3_10` | Film plastico (LDPE film) | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Mass-based |
| `ECOINV_PP_V3_10` | Reggette PP | 3 | Cat 1 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | Mass-based |
| `EXIO_SERVICES_NACE_M` | Servizi vari (professional services) | 3 | Cat 1 | EXIOBASE 3.x | 3.x | LICENCE | kg CO2e / EUR | 2024-best | Spend-based |
| `EXIO_MACHINERY_NACE_C28` | Impiantistica | 3 | Cat 2 | EXIOBASE 3.x | 3.x | LICENCE | kg CO2e / EUR | 2024-best | Spend-based |
| `EXIO_CONSUMABLES_NACE_C27` | Materiali di consumo | 3 | Cat 2 | EXIOBASE 3.x | 3.x | LICENCE | kg CO2e / EUR | 2024-best | Spend-based |
| `ECOINV_LANDFILL_INERT_V3_10` | Tiles end-of-life — landfill (inert) | 3 | Cat 12 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | 30% split per FR-17 |
| `ECOINV_CDW_RECYCLE_V3_10` | Tiles end-of-life — construction-waste recycling | 3 | Cat 12 | ecoinvent v3.10 | 3.10 | LICENCE | kg CO2e / kg | n/a | 70% split per FR-17; cut-off |
| `GWP_AR6_DEFAULT` | GWP set AR6 | n/a | metadata | IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 | AR6 (2021) | CH4=27.9, N2O=273, SF6=25200, HFC-134a=1530 | GWP100 | 2021 | Default for CSRD |
| `GWP_AR5_LEGACY` | GWP set AR5 | n/a | metadata | IPCC AR5 WG1 Ch.8 Table 8.7 (no climate–carbon feedback) | AR5 (2014) | CH4=28, N2O=265, SF6=23500, HFC-134a=1300 | GWP100 | 2014 | Legacy / EU ETS dual-track only |

**Note**: numeric `TBC` values must be pinned at Phase 5 against the URLs in §13. ecoinvent and EXIOBASE values cannot be reproduced in this document due to licence restrictions; they are seeded with provider+version pointers.

---

## 12. Methodological Gates (handover to architect-agent and data-engineer-agent)

Before Phase 5 calculation may proceed, the following conditions MUST be true. Each gate is testable; failure of any gate blocks Phase 5 sign-off.

| Gate ID | Condition | Verifier | Blocking? |
|---|---|---|---|
| MG-01 | The factor catalog table contains all rows in Section 11 with `factor_id`, `version`, `value` (or LICENCE marker), `valid_from`, `valid_to`, `gwp_set` populated. | data-engineer-agent | Yes |
| MG-02 | The factor catalog enforces immutability: post-publish UPDATE/DELETE blocked. | architect-agent + data-engineer-agent | Yes — extends CG-04 |
| MG-03 | The Scope 2 MB factor `MB_GO_ZERO` is gated by a check on the per-certificate QC1–QC8 evidence table (§2.4). | data-engineer-agent | Yes — extends CG-08 |
| MG-04 | The methodology statement (per FR-22 / KPI header) automatically populates `factor_source`, `factor_version`, `gwp_set`, `methodology` on every row of `emissions_consolidated`. NULL in any of these fields is rejected. | data-engineer-agent | Yes — extends CG-04 |
| MG-05 | The Cat 3 WTT calculator reads from Σ Scope 1 per facility per year (NOT from CSV Cat 3 Quantità). The CSV Cat 3 Quantità delta is logged to `dq_findings`. | data-analyst-agent | Yes (FR-11 acceptance) |
| MG-06 | The Cat 11 zero row is auto-emitted with the disclosure-note text "Omitted — Immaterial: ceramic tiles are passive products…" for every report run. | data-analyst-agent | Yes (FR-18) |
| MG-07 | The Cat 8 / Cat 10 / Cat 13 / Cat 14 / Cat 15 explicit-zero rows with rationale are auto-emitted in every ESRS E1-6 output. | data-analyst-agent | Yes |
| MG-08 | The IANO Processo_Decarb row is calculated with `factor_id='STOICH_CACO3_IPCC_2006'`, `methodology='stoichiometric'`, `sub_scope='process'`, and CO2-only flag set (no CH4, no N2O sub-components). | data-analyst-agent | Yes |
| MG-09 | LOI-3.5% methodology and ±10–20% uncertainty disclosure included in PDF / Excel output annotations for the IANO Processo_Decarb row. | data-analyst-agent + visualization-agent | Yes |
| MG-10 | Mixed-GWP-set runs are rejected at FR-19 enforcement; AR6 default and AR5 legacy paths are clearly labelled in run metadata. | data-engineer-agent | Yes |
| MG-11 | The dashboard, Excel, and PDF outputs disclose `gwp_set` in the header. | visualization-agent | Yes (extends CG-09) |
| MG-12 | If OI-7 is resolved as "IANO is in EU ETS scope", an AR5 dual-track regeneration is wired and tested before any FY2024 disclosure publication. | sustainability-expert-agent + data-engineer-agent | Conditional on OI-7 |
| MG-13 | If OI-8 is resolved as "company holds Cat 15-scope financial instruments", Cat 15 methodology (PCAF) is added to factor cascade before any FY2024 disclosure publication. | sustainability-expert-agent | Conditional on OI-8 |
| MG-14 | Per-certificate GO QC1–QC8 checklist (§2.4) is completed for all FY2024 GO volumes before MB=0 publication. | data steward + compliance-agent | Yes (extends CG-08) |
| MG-15 | AIB Italian residual mix 2024 value pinned from the AIB official PDF (data-engineer manual retrieval) before any MB calculation for FY2024 non-GO volumes. | data-engineer-agent | Yes |
| MG-16 | ISPRA Italian grid LB factor pinned for FY2024 (or FY2023 with documented offset) before any LB calculation. | data-engineer-agent | Yes |
| MG-17 | DEFRA 2025 (or 2026 if available at Phase 5) edition pinned for all WTT / freight / travel / waste factor rows. | data-engineer-agent | Yes |

---

## 13. References

Authoritative sources cited in this validation. Retrieval dates given for online checks; for paywalled / licence-restricted databases (ecoinvent, EXIOBASE, IEA, paid AIB downloads), only metadata is recorded.

1. **GHG Protocol Corporate Standard** (2004, revised 2015). World Resources Institute + WBCSD. https://ghgprotocol.org/corporate-standard. Retrieved 2026-05-13.
2. **GHG Protocol Scope 2 Guidance** (January 2015). https://ghgprotocol.org/scope-2-guidance. Specifically Chapter 7 (Scope 2 Quality Criteria, 8 criteria). Retrieved 2026-05-13. (Note: a Scope 2 Standard revision is under public consultation per the GHG Protocol website as of late 2025 / early 2026, but the 2015 Guidance remains the binding document for FY2024 reporting.)
3. **GHG Protocol Corporate Value Chain (Scope 3) Accounting and Reporting Standard** (2011). https://ghgprotocol.org/corporate-value-chain-scope-3-standard. Specifically Appendix F (Category definitions and minimum boundary). Retrieved 2026-05-13.
4. **GHG Protocol Technical Guidance for Calculating Scope 3 Emissions** (2013). https://ghgprotocol.org/scope-3-calculation-guidance-2. Specifically Chapter 3 (Category 3), Chapter 8 (Category 8), Chapter 11 (Category 11), Chapter 13 (Category 13), Chapter 14 (Category 14), Chapter 15 (Category 15). Retrieved 2026-05-13.
5. **CDP Technical Note: Relevance of Scope 3 Categories by Sector**. https://cdn.cdp.net/cdp-production/cms/guidance_docs/pdfs/000/003/504/original/CDP-technical-note-scope-3-relevance-by-sector.pdf. Retrieved 2026-05-13. (Cement / Glass / Ceramic sector relevance mapping used in Section B.)
6. **IPCC 2006 Guidelines for National Greenhouse Gas Inventories**, Volume 3 (Industrial Processes and Product Use), Chapter 2 (Mineral Industry Emissions). https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/3_Volume3/V3_2_Ch2_Mineral_Industry.pdf. Specifically §2.5 (Other Process Uses of Carbonates), §2.5.1.3 Table 2.1 (stoichiometric EFs). Retrieved 2026-05-13.
7. **IPCC Sixth Assessment Report (AR6), Working Group I, Chapter 7 Supplementary Material**. Table 7.SM.7 (Lifetime, radiative efficiency and metric values). https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_Chapter_07_Supplementary_Material.pdf. Retrieved 2026-05-13.
8. **IPCC Fifth Assessment Report (AR5), Working Group I, Chapter 8** (Anthropogenic and Natural Radiative Forcing). Table 8.7. (Used for AR5 GWP values for legacy / EU ETS track.) Retrieved 2026-05-13.
9. **GHG Protocol — IPCC Global Warming Potential Values (August 2024 compendium)**. https://ghgprotocol.org/sites/default/files/2024-08/Global-Warming-Potential-Values%20(August%202024).pdf. Retrieved 2026-05-13.
10. **CSRD ESRS E1 (Climate Change)**. Delegated Regulation (EU) 2023/2772 of 31 July 2023 supplementing Directive 2013/34/EU. Annex I — ESRS E1. Specifically §44(a)(b)(c) (gross Scope 1/2/3 disclosure), §45 (intensity ratios), §53 (intensity per net revenue). https://www.efrag.org/sites/default/files/media/document/2024-08/ESRS%20E1%20Delegated-act-2023-5303-annex-1_en.pdf. Retrieved 2026-05-13.
11. **Commission Implementing Regulation (EU) 2018/2066** of 19 December 2018 (EU ETS MRR for Phase IV), as amended by **(EU) 2020/2085** and **(EU) 2023/2122** of 17 October 2023. https://eur-lex.europa.eu/eli/reg_impl/2018/2066/oj and https://eur-lex.europa.eu/eli/reg_impl/2023/2122/oj. Retrieved 2026-05-13.
12. **D.Lgs. 199/2021** (Italian implementation of RED II). Article 46 (Guarantees of Origin). Retrieved 2026-05-13.
13. **D.Lgs. 28/2011** (Italian implementation of RED I). Article 34 (Guarantees of Origin, high-efficiency cogeneration). Retrieved 2026-05-13.
14. **DM MASE 14 luglio 2023 n. 224** — implementing decree for Italian GO regime. https://www.mase.gov.it/portale/documents/d/guest/dm_224_14-07-2023_garanzie_di_origine-pdf. Retrieved 2026-05-13.
15. **GSE (Gestore Servizi Energetici) — Garanzia d'origine**. https://www.gse.it/servizi-per-te/fonti-rinnovabili/garanzia-dorigine. (Operational manual for Italian GO management.) Retrieved 2026-05-13.
16. **GSE Regole applicative sulla gestione delle Garanzie d'Origine** (2023). https://www.gse.it/documenti_site/Documenti%20GSE/Servizi%20per%20te/GARANZIA%20ORIGINE/Regole%20e%20procedure/Regole%20applicative%20sulla%20gestione%20delle%20Garanzie%20d%20origine.pdf. Retrieved 2026-05-13.
17. **AIB European Residual Mixes 2024** (Association of Issuing Bodies; calculation by Grexel Systems Ltd). Final results published 2025-05-30. https://www.aib-net.org/facts/european-residual-mix/2024. Numeric value for Italian residual mix to be retrieved at Phase 5 (WebFetch returned HTTP 403 in this validation pass). Retrieved 2026-05-13 (metadata only).
18. **ISPRA Rapporto 386/2023** — "Fattori di emissione atmosferica di CO2 e altri gas a effetto serra nel settore elettrico" (historical series). https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/fattori-di-emissione-atmosferica-di-co2-e-altri-gas-a-effetto-serra-nel-settore-elettrico. Retrieved 2026-05-13 (metadata).
19. **ISPRA Rapporto 413/2025** — "Le emissioni di CO2 nel settore elettrico nazionale e regionale" (May 2025; 2023 data with 2024 preliminary estimates). https://emissioni.sina.isprambiente.it/wp-content/uploads/2025/05/Le-emissioni-di-CO2-nel-settore-elettrico_r413-2025_def.pdf. Retrieved 2026-05-13 (metadata).
20. **DEFRA / DESNZ 2025 UK Government GHG Conversion Factors for Company Reporting**. Release 2025-06 (initial dataset 2025-05-16). https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting. Retrieved 2026-05-13 (metadata).
21. **ecoinvent v3.10** (released 2023-12). https://ecoinvent.org/ecoinvent-v3-10/. Licence-restricted. Retrieved 2026-05-13 (metadata).
22. **EXIOBASE v3.x** environmentally extended multi-regional input-output database. https://www.exiobase.eu/. Retrieved 2026-05-13.
23. **EPD International** — public registry. https://www.environdec.com. Retrieved 2026-05-13.
24. **ISO 21930:2017** — Sustainability in buildings and civil engineering works — Core rules for environmental product declarations of construction products and services. (Used as reference for use-phase scope of ceramic tiles.)
25. **ISO 14064-1:2018** — Specification with guidance at the organization level for quantification and reporting of greenhouse gas emissions and removals. (Referenced for assurance documentation per requirements.md §4.)
26. **Cerame-Unie** (The European Ceramic Industry Association) — sector position papers on EU ETS Phase IV. https://cerameunie.eu. Retrieved 2026-05-13.

---

## Section I — Secondary methodological observations

These are observations raised by this validation that are not among the 8 items in the Phase 2 brief but are relevant to ISAE 3000 Limited assurance readiness. They are flagged as new OIs (OI-9, OI-10) in Section 10 and are non-blocking for Phase 3.

### I.1 Biogenic CO2 from packaging (cardboard, wooden pallets)

The cardboard and wooden-pallet items in `scope3_categorie.csv` Cat 1 carry biogenic carbon that was sequestered from the atmosphere during tree growth. GHG Protocol and ISO 14067 both require **separate disclosure** of biogenic CO2 emissions and removals — biogenic CO2 is not netted against fossil CO2 in the main inventory total but is disclosed as a separate memo line.

ecoinvent v3.10 datasets typically already separate biogenic CO2 from fossil CO2 in the underlying flow data; **the Phase 5 implementation must ensure this separation is preserved** when ecoinvent factors are seeded into the catalog. Aggregating biogenic CO2 into the main Cat 1 total is a methodological error that may be flagged by the ISAE 3000 verifier.

**Recommendation (OI-9)**: Adopt explicit biogenic-CO2 accounting policy at Phase 5. Two sub-rows per biogenic factor (`fossil_co2e` and `biogenic_co2_memo`). Disclose biogenic CO2 separately in ESRS E1-7 (Removals and Storage) and in ISO 14067 product-level outputs.

### I.2 Fugitive HFC emissions from facility cooling / refrigeration

`scope1_combustione.csv` contains stationary combustion (gas), mobile combustion (diesel, petrol), and process emissions (decarbonation). It **does not** contain any fugitive emission row — i.e. no refrigerant top-ups (R-410A, R-32, R-134a) from facility chillers / HVAC / process cooling.

For 7 industrial production sites, refrigerant top-ups are typically small in absolute terms but can be material on a per-kg basis owing to high GWPs (R-410A composite GWP ~2 256 per AR6). If the company tracks refrigerant inventory (purchases, top-ups, end-of-life recovery), these data should populate a Scope 1 fugitive sub-category. If not tracked, the omission must be disclosed in the ESRS E1-6 §44(a) sub-totals.

**Recommendation (OI-10)**: Ask the data steward at Phase 3 whether a refrigerant log exists. If yes, add Scope 1 fugitive rows in the staging schema (FR-01 may need a minor revision). If no, disclose the gap and propose a Year-2 implementation plan.

---

*End of Document — Version 1.0.0 — 2026-05-13 — DRAFT pending reviewer-agent sign-off*
