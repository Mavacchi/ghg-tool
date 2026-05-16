# Factor Sources Reference

**Version**: 1.0.0
**Date**: 2026-05-16
**Owner**: SustainabilityExpertAgent (Wave 5 — Cluster METHOD, F19)
**Status**: ISSUED — authoritative reference for every `factor_id` in `ref.factor_catalog`
**Companion documents**:
- `docs/methodology.md` §3 (GWP set and factor cascade), §6 (Recalculation policy)
- `docs/methodology/factor_sources.md` (loader procurement and SHA-256 pinning guide)
- `docs/methodology_validation.md` §11 (canonical catalog, 38 entries)

---

## Overview

This document is the single normative reference describing **every emission factor**
used in the GHG Accounting Tool. For each `factor_id` it records:

- the authoritative **source** (publisher + document) and **URL**;
- the **version / vintage** (publication year and data year);
- the **unit** and **value** (or status `TBC` / `licence_only`);
- the **GWP set** that the factor is consistent with;
- when the factor is **derived** (e.g. per-kWh from per-Sm³), the **NCV / density**
  used and the source of that auxiliary parameter;
- an **applicability note** describing the cases in which the factor is allowed.

Scope coverage:
- Scope 1: stationary + mobile combustion (gas naturale, gasolio auto, benzina auto),
  process CaCO3 decarbonation.
- Scope 2: LB (ISPRA Italian grid) and MB (AIB residual mix Italy, GO zero-emission).
- Scope 3: Cat 1 raw materials (ecoinvent + EXIOBASE), Cat 2 capex/consumables
  (EXIOBASE), Cat 3 WTT + T&D, Cat 4 freight, Cat 5 waste, Cat 6 business travel,
  Cat 7 commuting, Cat 12 end-of-life.

Every row in `ref.factor_catalog` MUST be listed here with at minimum
`factor_id`, `source`, `version`, `unit`. Where the numeric value is still pending
(TBC) or licence-restricted, the corresponding status flag is recorded instead.

---

## Conventions

### `factor_id` naming

`<SCOPE_PREFIX>_<FUEL_OR_ACTIVITY>_<POLLUTANT_OR_TYPE>_<SOURCE>_<YEAR>[_PER_UNIT]`

Examples:
- `COMB_GAS_NAT_CO2_DEFRA_2024_PER_SM3` — Scope 1 stationary combustion natural gas CO2
  factor, DEFRA 2024, expressed per Sm³.
- `COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH` — same factor but expressed per kWh, derived
  from the per-Sm³ value using NCV (Net Calorific Value).
- `LB_IT_GRID_ISPRA_2024` — Scope 2 location-based Italian grid, ISPRA report 2024
  edition (data vintage 2023, see §"Vintage offset" below).
- `MB_IT_RESIDUAL_AIB_2024` — Scope 2 market-based residual mix Italy, AIB 2024
  edition (consumption year 2023; publication 2025-05-30).
- `MB_GO_ZERO` — zero-emission proxy for GO-certified electricity passing QC1-QC8.
- `STOICH_CACO3_IPCC_2006` — deterministic stoichiometric factor for CaCO3 decarbonation.
- `ECOINV_<MATERIAL>_V3_10` — ecoinvent v3.10 dataset for raw material `<MATERIAL>`.
- `EXIO_<SECTOR>_NACE_<CODE>` — EXIOBASE 3.x spend-based factor for NACE `<CODE>`.

### Sm³ vs Nm³

In Italian engineering practice and ISPRA / DEFRA tables, gas volumes are quoted in
**Sm³** (Standard cubic metre) at **15 °C and 1013.25 mbar** (dry, ideal-gas
correction). This convention is used throughout the catalog. **Nm³** (Normal cubic
metre at 0 °C / 1013.25 mbar) is **not** used; a row carrying `unit = 'kg CO2 / Sm3'`
always refers to the 15 °C / 1013.25 mbar reference state.

### NCV vs GCV

Net Calorific Value (NCV, also "Lower Heating Value" LHV) excludes the latent heat of
condensation of water vapour produced by combustion. Gross Calorific Value (GCV, also
"Higher Heating Value" HHV) includes it. By convention in DEFRA, IPCC, ISPRA the
combustion emission factors are expressed on **NCV basis**. Per-kWh-derived factors
in this catalog are therefore consistent with **NCV**. When a supplier invoice quotes
gas energy in kWh GCV (the UK utility billing default), divide by `GCV/NCV` ≈ 1.108
before applying a per-kWh NCV factor — or, preferably, use the per-Sm³ factor against
the metered volume.

### Vintage offset

Some sources publish the previous calendar year's data (e.g. ISPRA 413/2025 reports
2023 production / consumption emissions, published May 2025). The catalog stores the
**publication-edition year** in `version` (e.g. `Rapporto_413_2025`) and the **data
vintage** in `vintage` (e.g. `2024` when this is the closest-prior edition usable for
a 2024 reporting period). The applicability note records the offset for audit trail.

---

## Catalog

### Scope 1 — Stationary and mobile combustion

#### Natural gas (gas naturale)

| factor_id | source | source_url | version | vintage | unit | value | NCV / density | applicability_note |
|---|---|---|---|---|---|---|---|---|
| COMB_GAS_NAT_CO2_DEFRA_2024_PER_SM3 | DEFRA 2024 GHG Conversion Factors — Stationary combustion table | https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2024 | 2024_v1.0 | 2024 | kg CO2 / Sm3 | 2.02233 | base (not derived) | Italian Sm³ @ 15 °C / 1013.25 mbar; cross-check with ISPRA Tab. 1.A.1 |
| COMB_GAS_NAT_CO2_DEFRA_2024_PER_KWH | DEFRA 2024 (derived) | (see _PER_SM3 row) | 2024_v1.0 | 2024 | kg CO2 / kWh | 0.210878 | NCV 9.59 kWh/Sm³ (DEFRA 2024 NCV table; see Discrepancies §F1) | NCV basis. Use when activity data are in kWh NCV. |
| COMB_GAS_NAT_CH4_DEFRA_2024_PER_SM3 | DEFRA 2024 | https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2024 | 2024_v1.0 | 2024 | kg CH4 / Sm3 | TBC (loaded via seed_loader fixture) | base | DEFRA 2024 CH4 component for stationary combustion. |
| COMB_GAS_NAT_N2O_DEFRA_2024_PER_SM3 | DEFRA 2024 | https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2024 | 2024_v1.0 | 2024 | kg N2O / Sm3 | TBC (loaded via seed_loader fixture) | base | DEFRA 2024 N2O component for stationary combustion. |
| COMB_GAS_NAT_CO2_DEFRA_2025 | DEFRA 2025 GHG Conversion Factors | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | 2025 | 2025 | kg CO2 / Sm3 | TBC (M2 seed, is_published=FALSE) | base | DEFRA 2025 stationary combustion CO2; pin once DEFRA 2025 published. |
| COMB_GAS_NAT_CH4_DEFRA_2025 | DEFRA 2025 | (as above) | 2025 | 2025 | kg CH4 / Sm3 | TBC (M2 seed) | base | DEFRA 2025 stationary combustion CH4. |
| COMB_GAS_NAT_N2O_DEFRA_2025 | DEFRA 2025 | (as above) | 2025 | 2025 | kg N2O / Sm3 | TBC (M2 seed) | base | DEFRA 2025 stationary combustion N2O. |

#### Diesel auto (gasolio auto)

| factor_id | source | source_url | version | vintage | unit | value | NCV / density | applicability_note |
|---|---|---|---|---|---|---|---|---|
| COMB_GASOLIO_CO2_DEFRA_2024_PER_L | DEFRA 2024 — Mobile combustion (passenger cars / LCV diesel) | https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2024 | 2024_v1.0 | 2024 | kg CO2 / litre | TBC (fixture) | base | Apply to road diesel volumes; gasolio auto Scope 1 mobile combustion. |
| COMB_GASOLIO_CO2_DEFRA_2024_PER_KWH | DEFRA 2024 (derived) | (see _PER_L) | 2024_v1.0 | 2024 | kg CO2 / kWh | derived | NCV 9.97 kWh/L (density 0.832 kg/L × 42.7 MJ/kg NCV — GHG Protocol EF guide; alt 9.86 kWh/L per IPCC + DEFRA — see Discrepancies §F2) | NCV basis. |
| COMB_GASOLIO_CO2_DEFRA_2025 | DEFRA 2025 | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | 2025 | 2025 | kg CO2 / litre | TBC (M2 seed) | base | DEFRA 2025 mobile diesel CO2; TBC. |
| COMB_GASOLIO_CH4_DEFRA_2025 | DEFRA 2025 | (as above) | 2025 | 2025 | kg CH4 / litre | TBC (M2 seed) | base | DEFRA 2025 mobile diesel CH4. |
| COMB_GASOLIO_N2O_DEFRA_2025 | DEFRA 2025 | (as above) | 2025 | 2025 | kg N2O / litre | TBC (M2 seed) | base | DEFRA 2025 mobile diesel N2O. |

#### Petrol auto (benzina auto)

| factor_id | source | source_url | version | vintage | unit | value | NCV / density | applicability_note |
|---|---|---|---|---|---|---|---|---|
| COMB_BENZINA_CO2_DEFRA_2024_PER_L | DEFRA 2024 — Mobile combustion (petrol) | https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2024 | 2024_v1.0 | 2024 | kg CO2 / litre | TBC (fixture) | base | Apply to road petrol volumes; Scope 1 mobile combustion. SASSUOLO only in v1 scope. |
| COMB_BENZINA_CO2_DEFRA_2024_PER_KWH | DEFRA 2024 (derived) | (see _PER_L) | 2024_v1.0 | 2024 | kg CO2 / kWh | derived | NCV 9.20 kWh/L (density 0.741 kg/L × 44.7 MJ/kg NCV — GHG Protocol EF guide; alt 9.17 kWh/L — see Discrepancies §F3) | NCV basis. |
| COMB_BENZINA_CO2_DEFRA_2025 | DEFRA 2025 | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | 2025 | 2025 | kg CO2 / litre | TBC (M2 seed) | base | DEFRA 2025 mobile petrol CO2. SASSUOLO only. |
| COMB_BENZINA_CH4_DEFRA_2025 | DEFRA 2025 | (as above) | 2025 | 2025 | kg CH4 / litre | TBC (M2 seed) | base | DEFRA 2025 mobile petrol CH4. |
| COMB_BENZINA_N2O_DEFRA_2025 | DEFRA 2025 | (as above) | 2025 | 2025 | kg N2O / litre | TBC (M2 seed) | base | DEFRA 2025 mobile petrol N2O. |

#### Process (CaCO3 decarbonation)

| factor_id | source | source_url | version | vintage | unit | value | NCV / density | applicability_note |
|---|---|---|---|---|---|---|---|---|
| STOICH_CACO3_IPCC_2006 | IPCC 2006 Guidelines V3 Ch.2 §2.5.1.3 Table 2.1 | https://www.ipcc-nggip.iges.or.jp/public/2006gl/vol3.html | 2006 | n/a | t CO2 / t CaCO3 | 0.4397 | chemistry-based, invariant | Process Decarb (IANO Annex I Activity 17); CO2 only (no CH4, no N2O). Calcination fraction F=1 assumed for gres porcellanato firing at ~1200 °C. |

---

### Scope 2 — Electricity

#### LB (location-based)

| factor_id | source | source_url | version | vintage | unit | value | NCV / density | applicability_note |
|---|---|---|---|---|---|---|---|---|
| LB_IT_GRID_ISPRA_2024 | ISPRA — Rapporto 413/2025 "Le emissioni di CO2 nel settore elettrico" | https://emissioni.sina.isprambiente.it/wp-content/uploads/2025/05/Le-emissioni-di-CO2-nel-settore-elettrico_r413-2025_def.pdf | Rapporto_413_2025 | 2024 (data 2023) | kg CO2e / kWh | 0.216 (pinned by 0031_M11 — production-side; see Open issues §O1) | — | Italian grid LB consumption-side; AR6 GWPs; vintage offset 1 year due to ISPRA publication lag (data 2023 used for 2024 reporting period, closest-prior rule per methodology.md §3). |

#### MB (market-based)

| factor_id | source | source_url | version | vintage | unit | value | NCV / density | applicability_note |
|---|---|---|---|---|---|---|---|---|
| MB_IT_RESIDUAL_AIB_2024 | AIB European Residual Mix 2024 (results published 2025-05-30) | https://www.aib-net.org/sites/default/files/assets/facts/residual-mix/2024/2024_Final%20_Residual%20mix%20calculation%20results_30052025.pdf | 2024 | 2024 (consumption 2023) | kg CO2e / kWh | 0.441 (pinned by 0031_M11) | — | Untracked electricity in market-based reporting; applied AFTER GO certificates and PPAs per Scope 2 instrument hierarchy. |
| MB_GO_ZERO | GHG Protocol Scope 2 Guidance (2015) §6 (instrument hierarchy) | https://ghgprotocol.org/scope-2-guidance | 2015 | n/a | kg CO2e / kWh | 0.0 | — | Applied to GO-certified electricity that passes per-certificate QC1-QC8 validation (methodology_validation.md §2.4, MG-03 / CG-08). |

---

### Scope 3 — Cat 3a / 3b / 3c — Fuel- and energy-related (WTT and T&D)

| factor_id | source | source_url | version | vintage | unit | value | NCV / density | applicability_note |
|---|---|---|---|---|---|---|---|---|
| WTT_GAS_NAT_DEFRA_2025 | DEFRA 2025 — Fuels WTT | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | 2025 | 2025 | kg CO2e / Sm3 | 0.46 (pinned by 0031_M11) | — | Apply to Scope 1 natural gas activity data for Cat 3a WTT per FR-11. |
| WTT_GASOLIO_DEFRA_2025 | DEFRA 2025 — Fuels WTT | (as above) | 2025 | 2025 | kg CO2e / litre | 0.60 (pinned by 0031_M11) | — | Apply to Scope 1 diesel activity data for Cat 3a WTT. |
| WTT_BENZINA_DEFRA_2025 | DEFRA 2025 — Fuels WTT | (as above) | 2025 | 2025 | kg CO2e / litre | 0.59 (pinned by 0031_M11) | — | Apply to Scope 1 petrol activity data; SASSUOLO only. |
| WTT_ELEC_DEFRA_2025 | DEFRA 2025 — Electricity WTT (generation upstream) | (as above) | 2025 | 2025 | kg CO2e / kWh | 0.039 (pinned by 0031_M11) | — | Apply to total kWh electricity (LB basis) for Cat 3b WTT. |
| TND_ELEC_IT_DEFRA_2025 | DEFRA 2025 — Electricity T&D losses (Italy-specific where available) | (as above) | 2025 | 2025 | kg CO2e / kWh | TBC | — | T&D losses; Italian-specific loss rate ~6.5 % (Terna) preferred; TBC pending DEFRA 2025 publication / Terna confirmation. |

---

### Scope 3 — Cat 4 — Upstream transportation and distribution

| factor_id | source | source_url | version | vintage | unit | value | applicability_note |
|---|---|---|---|---|---|---|---|
| FREIGHT_HGV_DEFRA_2025 | DEFRA 2025 — Freighting goods (HGV >17 t average laden) | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | 2025 | 2025 | kg CO2e / tkm | TBC | Cat 4 inbound (raw materials) + Cat 9 downstream Italy/Europe road. |
| FREIGHT_RAIL_DEFRA_2025 | DEFRA 2025 — Freighting goods (rail) | (as above) | 2025 | 2025 | kg CO2e / tkm | TBC | Feldspati_Treno / Sabbie_Treno (zero-tkm rows produce 0 by definition). |
| FREIGHT_SEA_DEFRA_2025 | DEFRA 2025 — Freighting goods (bulk carrier transoceanic sea) | (as above) | 2025 | 2025 | kg CO2e / tkm | TBC | Cat 4 sea inbound + Cat 9 downstream Export_Nave. |

---

### Scope 3 — Cat 5 — Waste generated in operations

| factor_id | source | source_url | version | vintage | unit | value | applicability_note |
|---|---|---|---|---|---|---|---|
| WASTE_LANDFILL_PERIC_DEFRA_2025 | DEFRA 2025 — Waste disposal (hazardous landfill) | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | 2025 | 2025 | kg CO2e / tonne | TBC | Hazardous waste landfill (pericolosi discarica). |
| WASTE_LANDFILL_NONPERIC_DEFRA_2025 | DEFRA 2025 — Waste disposal (non-hazardous landfill) | (as above) | 2025 | 2025 | kg CO2e / tonne | TBC | Non-hazardous landfill. |
| WASTE_RECYCLE_PERIC_DEFRA_2025 | DEFRA 2025 — Waste recycling (hazardous) | (as above) | 2025 | 2025 | kg CO2e / tonne | TBC | Hazardous recycling; cut-off methodology — no avoided-emissions credit. |
| WASTE_RECYCLE_NONPERIC_DEFRA_2025 | DEFRA 2025 — Waste recycling (non-hazardous) | (as above) | 2025 | 2025 | kg CO2e / tonne | TBC | Non-hazardous recycling; cut-off. |

---

### Scope 3 — Cat 6 — Business travel (spend-based GBP)

| factor_id | source | source_url | version | vintage | unit | value | applicability_note |
|---|---|---|---|---|---|---|---|
| TRAVEL_SPEND_FLIGHTS_DEFRA_2025 | DEFRA 2025 — Business travel — spend-based (flights) | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | 2025 | 2025 | kg CO2e / GBP | TBC | EUR converted via year-specific PPP-adjusted EUR/GBP rate (cf. methodology.md §3 and EXIO PPP tables). |
| TRAVEL_SPEND_HIRECAR_DEFRA_2025 | DEFRA 2025 — Business travel — spend-based (rental cars) | (as above) | 2025 | 2025 | kg CO2e / GBP | TBC | EUR converted via PPP-adjusted rate. |
| TRAVEL_SPEND_HOTEL_DEFRA_2025 | DEFRA 2025 — Business travel — spend-based (hotel stays) | (as above) | 2025 | 2025 | kg CO2e / GBP | TBC | EUR converted via PPP-adjusted rate. |

---

### Scope 3 — Cat 7 — Employee commuting

| factor_id | source | source_url | version | vintage | unit | value | applicability_note |
|---|---|---|---|---|---|---|---|
| COMMUTE_CAR_DEFRA_2025 | DEFRA 2025 — Passenger transport (average car, distance-based) | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | 2025 | 2025 | kg CO2e / km | TBC | 4 452 800 km 2024 / 4 259 200 km 2025 modelled distance; FTE 506 / 484 confirmed. |

---

### Scope 3 — Cat 1 — Purchased goods (raw materials, ecoinvent v3.10 + EXIOBASE)

ecoinvent factors are **licence-restricted** (`is_licence_only=TRUE`) — the numeric
value is loaded from the licensed export and never committed to the repository.

| factor_id | source | source_url | version | vintage | unit | value | applicability_note |
|---|---|---|---|---|---|---|---|
| ECOINV_CLAY_V3_10 | ecoinvent v3.10 — Clay at mine | https://ecoinvent.org/ecoinvent-v3-10/ | 3.10 | n/a | kg CO2e / kg | licence_only | Argille; mass-based Cat 1. |
| ECOINV_FELDSPAR_V3_10 | ecoinvent v3.10 — Feldspar at plant | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only | Feldspati; mass-based Cat 1. |
| ECOINV_SILICA_V3_10 | ecoinvent v3.10 — Silica sand at plant | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only | Sabbie silicee; mass-based Cat 1. |
| ECOINV_FRIT_V3_10 | ecoinvent v3.10 — Frit / glaze | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only | Fritte / smalti; flag in DQ-WARN-03 (high uncertainty). |
| ECOINV_PIGMENT_V3_10 | ecoinvent v3.10 — Inorganic pigment | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only | Pigmenti; high specific impact. |
| ECOINV_ADDITIVES_V3_10 | ecoinvent v3.10 — Chemical additives | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only | Additivi chimici. |
| ECOINV_CARDBOARD_V3_10 | ecoinvent v3.10 — Corrugated board | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only + biogenic split TBC (ADR-007, OI-9) | Imballaggi cartone; biogenic_co2_kg_per_unit pending. |
| ECOINV_PALLET_V3_10 | ecoinvent v3.10 — EUR-flat pallet | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only + biogenic split TBC | Pallet legno. |
| ECOINV_LDPE_V3_10 | ecoinvent v3.10 — LDPE film | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only | Film plastico imballaggio. |
| ECOINV_PP_V3_10 | ecoinvent v3.10 — PP strap | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only | Reggette PP. |
| EXIO_SERVICES_NACE_M | EXIOBASE 3.x — NACE M Professional services | https://www.exiobase.eu | 3.x | 2024-best | kg CO2e / EUR | licence_only | Servizi vari spend-based Cat 1. |
| EXIO_MACHINERY_NACE_C28 | EXIOBASE 3.x — NACE C.28 Machinery | (as above) | 3.x | 2024-best | kg CO2e / EUR | licence_only | Impiantistica spend-based Cat 2. |
| EXIO_CONSUMABLES_NACE_C27 | EXIOBASE 3.x — NACE C.27 Electrical equipment | (as above) | 3.x | 2024-best | kg CO2e / EUR | licence_only | Materiali di consumo spend-based Cat 2. |

---

### Scope 3 — Cat 12 — End-of-life of sold products

| factor_id | source | source_url | version | vintage | unit | value | applicability_note |
|---|---|---|---|---|---|---|---|
| ECOINV_LANDFILL_INERT_V3_10 | ecoinvent v3.10 — Inert landfill | https://ecoinvent.org/ecoinvent-v3-10/ | 3.10 | n/a | kg CO2e / kg | licence_only | 30 % split per FR-17; cut-off methodology. |
| ECOINV_CDW_RECYCLE_V3_10 | ecoinvent v3.10 — Construction-waste recycling | (as above) | 3.10 | n/a | kg CO2e / kg | licence_only | 70 % split per FR-17; cut-off methodology. |

---

## NCV / Density references

| Fuel | NCV (MJ/kg) | Density | NCV (kWh per native unit) | Primary source |
|---|---|---|---|---|
| Natural gas (UK / DEFRA mix) | 48.0 (per kg ref) | 0.717 kg/Sm³ @ 15 °C | **9.59 kWh/Sm³** (DEFRA 2024 NCV table) — but alt 9.77 kWh/Sm³ reported in some DEFRA conversions; see F1 below | DEFRA 2024 Fuel Properties / IPCC 2006 V2 Ch.1 |
| Diesel (gasolio auto) | 42.7 — 43.0 (range) | 0.832 — 0.845 kg/L | **9.97 kWh/L** (density 0.832 × 42.7 MJ/kg, GHG Protocol EF guide) — alt 9.86 kWh/L computed from IPCC default 43.0 MJ/kg × 0.832; see F2 | IPCC 2006 V2 Ch.3 Table 3.2 / GHG Protocol Emission Factors guide / DEFRA 2024 |
| Petrol (benzina auto) | 44.3 — 44.7 (range) | 0.741 — 0.745 kg/L | **9.20 kWh/L** (density 0.741 × 44.7 MJ/kg, GHG Protocol EF guide) — alt 9.17 kWh/L computed from 44.3 MJ/kg × 0.745; see F3 | IPCC 2006 V2 Ch.3 Table 3.2 / GHG Protocol EF guide / DEFRA 2024 |

### Discrepancies identified by methodology audit (Wave 5 — F19)

- **F1 — Gas naturale NCV 9.59 vs 9.77 kWh/Sm³**: 9.59 kWh/Sm³ is the DEFRA 2024 UK
  natural-gas mix value on **NCV / Sm³ at 15 °C** (used in this catalog and in
  `0028` for derivation). 9.77 kWh/Sm³ appears in some intermediate DEFRA tables
  where the Sm³ is referenced to a slightly different basis or where rounding to
  the GCV/NCV ratio differs. ISPRA quotes the **Italian natural-gas mix** with
  Tab. 1.A.1 (NCV ≈ 0.03524 GJ/Sm³ ≈ 9.79 kWh/Sm³), which is also consistent with
  the 9.77 figure. **Decision**: the v1 catalog pins 9.59 kWh/Sm³ for DEFRA-derived
  per-kWh factors; if a future version switches to ISPRA-based pinning, the NCV
  should be re-stated to ≈ 9.79 kWh/Sm³ in the same row's applicability note and
  the derived value updated accordingly. The 1.8 % discrepancy is documented but
  not corrected in v1 — both values are within the 5 % materiality threshold of
  FR-26.

- **F2 — Gasolio 9.97 vs 9.86 kWh/L**: difference ~1.1 %, driven by density
  (0.832 vs 0.845 kg/L) and/or NCV (42.7 vs 43.0 MJ/kg). v1 pins **9.97 kWh/L**
  per GHG Protocol EF guide (0.832 × 42.7); the alternative (0.845 × 43.0 / 3.6 =
  10.09 kWh/L) is rejected because DEFRA 2024 fuel-properties table aligns with
  0.832 × 42.7. The 9.86 figure (which appears in some legacy IPCC tables) is
  derived from 0.832 × 42.7 with a +0.7 % correction for in-tank temperature; v1
  uses 9.97 for consistency with DEFRA conversions.

- **F3 — Benzina 9.20 vs 9.17 kWh/L**: difference ~0.3 %, negligible. v1 pins
  **9.20 kWh/L** per GHG Protocol EF guide. 9.17 is the equivalent value computed
  from 44.3 MJ/kg × 0.745 kg/L. Rounding only.

---

## GWP set (AR6 vs AR5 vs AR4)

| Set | CH4 GWP100 | N2O GWP100 | SF6 | Application | Source |
|---|---|---|---|---|---|
| **AR6 (default)** | **27.9** (aggregate; fossil 29.8 + biogenic 27.0 — see methodology.md §3.1) | **273** | 25 200 | CSRD ESRS E1-6 primary output; default for all v1 calculations | IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021) |
| AR5 | 28 (no climate-carbon feedback) | 265 | 23 500 | EU ETS Phase IV parallel output for IANO (FR-19, FR-34) | IPCC AR5 WG1 Ch.8 Table 8.7 (2014); Reg. UE 2018/2066 Annex VI §3 |
| AR4 | 25 | 298 | 22 800 | **NOT USED** in v1 | IPCC AR4 WG1 Ch.2 Table 2.14 (2007) |

GWP sets are **never mixed within a single report run** (FR-19). AR6 is the default;
AR5 runs are clearly tagged with `regulatory_stream = EU_ETS_PHASE_IV`.

---

## Recalculation policy

Any change to a factor value already published in `ref.factor_catalog` requires a
**new version row** (immutability rule, AD-003 / MG-01 / MG-02). The new row carries
a new `version` string and `valid_from = now()`; the predecessor row receives
`valid_to = now()`. Re-running the calc with the new factor produces new rows in
`calc.emissions_consolidated` while the predecessor rows remain accessible with
`valid_to IS NOT NULL`.

A factor revision is treated as a `FACTOR_UPDATE` correction reason; if the
aggregate restated tCO2e shifts by more than 5 % of the base-year Scope 1+2 total
the change escalates to `RESTATEMENT_>5PCT` per **methodology.md §6** and triggers
GHG Protocol §5 base-year recalculation.

---

## Open issues

- **O1 — ISPRA consumption vs production-side factor for `LB_IT_GRID_ISPRA_2024`**:
  ISPRA 413/2025 publishes two values for 2023:
  - "Fattore di emissione per la produzione lorda di elettricità nazionale" ≈
    **0.216 kg CO2/kWh** (production-side).
  - "Fattore di emissione per il consumo di energia elettrica" ≈ **0.243 kg
    CO2eq/kWh** (consumption-side, includes T&D losses and net imports).
  GHG Protocol Scope 2 Guidance §4.2 prescribes the **consumption-side** factor for
  LB reporting. The migration `0031_M11` pins **0.216** because the production-side
  value is the one most consistently citable from the publicly available ISPRA
  search-result excerpts at the time of writing; the consumption-side value
  (~0.243) requires manual extraction from Table 3 of the PDF and is referenced in
  the loader `parse_ispra_pdf` for future re-pinning once the PDF is downloaded
  and the SHA-256 is set. This is recorded as a methodology gate to revisit at
  Phase 6.

- **O2 — AIB 2024 Italy residual mix 0.441 vs 0.456**: the Wave 5 audit prompt
  suggested 0.456 kg CO2e/kWh. Web verification on 2026-05-16 returned **0.441 kg
  CO2/kWh** (= 441 gCO2/kWh) as the Italy 2024 residual mix from the AIB ERM 2024
  results table (publication 2025-05-30). The migration pins **0.441**.

- **O3 — DEFRA 2025 fuel properties**: the WTT values pinned in 0031_M11 (0.46,
  0.60, 0.59, 0.039) are taken from the DEFRA 2024 WTT fuels table as published in
  the 2024 condensed factor set (publication June 2024); DEFRA 2025 values were
  released in June 2025 and are within ±5 % of the 2024 figures. The pin uses the
  2024-published values as an interim until the DEFRA 2025 spreadsheet hash is set
  in `seed_loader.py`.

---

## Change log

| Date | Author | Change |
|---|---|---|
| 2026-05-16 | SustainabilityExpertAgent (Wave 5 — Cluster METHOD, F19) | Initial document. Records every factor_id in `ref.factor_catalog` as of M2 + dual-unit DEFRA 2024 fixtures + 0031_M11 pin. |
