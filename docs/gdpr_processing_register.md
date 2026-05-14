# GDPR Article 30 Records of Processing Activities

**Controller**: Saturnia Ceramica S.r.l. (placeholder — substitute legal entity name before production deployment)
**Document version**: 1.0.0
**Date**: 2026-05-14
**Status**: DRAFT — controller DPO or legal officer must review and countersign before production deployment
**Closes**: COMP-P1-001 (Art. 30 register), COMP-P1-003 (Art. 17 erasure reconciliation)

---

## Controller

**Legal name**: Saturnia Ceramica S.r.l. (placeholder)
**Registered office**: [TBD — insert registered address before deployment]
**VAT / fiscal code**: [TBD]
**Contact point for data protection enquiries**: [TBD — insert DPO email or legal@domain.it]

**Data Protection Officer (DPO)**: Designation is subject to assessment under GDPR Art. 37.
For small-to-medium enterprises not carrying out large-scale systematic monitoring of natural
persons, a DPO is not mandatory under Art. 37(1). The controller must confirm whether the
Art. 37 threshold is met. If a DPO has not been formally designated, the contact point above
serves as the internal privacy reference.

---

## Joint Controllers and Processors

**Joint controllers**: None identified for v1. The GHG accounting tool is operated exclusively
by the controller's internal staff using internal corporate infrastructure.

**Processors (Art. 28 relationship)**:

| Processor | Role | Data transferred | Safeguard |
|---|---|---|---|
| Cloud infrastructure provider | TBD at production deployment — hosting of Docker containers and PostgreSQL database | System-user account data (email, bcrypt hash) + emission records | Data Processing Agreement (DPA) required under Art. 28 before deployment; model clauses or equivalent safeguards to be put in place |
| ISAE 3000 assurance provider | Controller-to-controller relationship; separate assurance engagement letter | Read-only access to audit trail (pseudonymised user IDs) | Engagement letter with confidentiality clause; no DPA required (separate controller) |

Until a production cloud hosting provider is selected, this row remains TBD. Production
deployment is blocked until a DPA is in place per CG-01.

---

## Categories of Data Subjects

**System users**: Internal employees holding one of three RBAC roles:

- ESG Manager (`esg_manager`) — validates methodology, approves CSRD reports
- Data Steward (`data_steward`) — inputs and validates raw activity data, manages factor catalog
- Auditor (`auditor`) — read-only review of calculations and audit trail

**Explicit statement**: Emission records stored in `calc.emissions_consolidated` contain
**no data subject personal data**. Records represent tonnes of CO2-equivalent attributed
to organisational sites (Codice_Sito), not to individuals.

Aggregate FTE headcount figures used as intensity denominators (2024: 506 employees,
2025: 484 employees, per HR confirmation 2026-05-13) are corporate-level totals that
**do not identify any individual**. They are not stored at individual-employee level.
Article 4(1) personal data definition is not satisfied by an aggregate count. GDPR
processing obligations for these figures are therefore limited to those applicable to
any other business reference data.

Employee commuting distance data (Cat 7, 4,452,800 km in 2024) is an aggregate activity
figure derived from headcount and an estimated km/FTE/year parameter. Individual commuting
distances are not collected or stored. No individual-level employee PII is processed by
this system in v1.

---

## Categories of Personal Data

Processing is limited to system-user account management data:

| Category | Fields | Special category (Art. 9)? |
|---|---|---|
| User identity | `username` (corporate account name), `email` (corporate email address) | No |
| Authentication credential | `password_hash` (bcrypt-12; the plaintext password is never stored or logged) | No |
| Access control | `role_id` (FK to `ref.roles`; values: esg_manager, data_steward, auditor), `is_active` flag | No |
| Account lifecycle | `created_at` timestamp | No |
| Operational | `tenant_id` (single-tenant v1; UUID of the controller entity) | No |

**No special-category data** (Art. 9) is processed: no health data, no racial or ethnic origin,
no biometric data, no trade-union membership, no criminal records.

---

## Lawful Basis for Processing

### Emission inventory calculation and reporting

**Lawful basis: Art. 6(1)(c) — Legal obligation.**

The Corporate Sustainability Reporting Directive (CSRD, Directive 2022/2464/EU), as transposed
into Italian law, imposes a mandatory obligation on in-scope undertakings to prepare and
disclose sustainability information including greenhouse gas emissions per ESRS E1. The
controller is subject to CSRD disclosure obligations. Processing of business operational
data (energy consumption, material quantities, transportation distances) to produce the
required ESRS E1-6 tables is necessary to comply with this legal obligation.

Additionally, IANO is an Annex I installation under EU ETS Phase IV (Directive 2003/87/EC;
MRR Regulation 2018/2066 as amended by 2023/2122), imposing a further legal obligation
to report verified annual GHG emissions. The dual-track AR5 output supports compliance
with this obligation.

Because the lawful basis is Art. 6(1)(c), the Art. 17(3)(b) exception to erasure applies
to emission records (see Art. 17 section below).

### System-user account management

**Lawful basis: Art. 6(1)(b) — Contract.**

The employment contract or service arrangement between the controller and each system user
constitutes the contractual basis for providing secure access to internal business systems.
Processing of username, email, and authentication credentials is necessary to perform the
access-control obligations under that arrangement. Bcrypt hashing satisfies the Art. 5(1)(f)
integrity-and-confidentiality principle.

---

## Recipients

**Internal only**. No personal data is disclosed to third parties in v1 except:

- **ISAE 3000 assurance provider**: receives read-only access to the audit trail for limited
  assurance engagement. Audit trail entries contain `user_id` (UUID, truncated to 8 chars
  in structured logs per SEC-P0-005) and `user_role`. The assurance provider acts as a
  separate controller under its own engagement letter; no DPA is required.
- **Cloud infrastructure provider**: if production deployment uses a third-party cloud host,
  the provider acts as a processor (see Processors section above). A DPA under Art. 28
  must be in place before personal data is transferred to that provider's infrastructure.

**No marketing, advertising, analytics, or data-broker recipients.**

---

## International Transfers

**None in v1.** The system is designed for single-region EU deployment (Italy). No personal
data is transferred to third countries (outside the EEA) in the v1 architecture.

If a future cloud infrastructure provider operates data centres outside the EEA, Standard
Contractual Clauses (SCCs) under Art. 46(2)(c) or equivalent transfer mechanism must be
put in place before deployment in that configuration. This must be assessed at the production
deployment planning stage.

---

## Retention Periods

| Data category | Retention period | Legal basis for retention | Implementation |
|---|---|---|---|
| Emission records (`calc.emissions_consolidated`) | 10 years from the end of the reporting year | CSRD Art. 19a; sustainability statements must be retained in accordance with the general obligation on financial records; ISAE 3000 assurance continuity | Append-only DB table; no DELETE trigger (`trg_emissions_deny_mutation`); backup retention policy to be aligned to this period by IT Operations |
| Audit log (`calc.audit_log`) | 10 years | CSRD assurance continuity; NFR-19 | Append-only; same backup policy |
| DQ findings and DLQ (`calc.dq_findings`, `calc.dlq`) | 10 years | Assurance evidence package | Append-only |
| Factor catalog (`ref.factor_catalog`) | Lifetime of the emissions records that reference each factor version | ISAE 3000 Limited evidence requirement: auditor must reproduce historical calculations | Immutable post-publish; `valid_to` set when superseded, records retained |
| System-user accounts (`ref.users`) | Active: duration of employment or service arrangement. Inactive: 5 years after employment ends, aligned to Italian statutory limitation period for employment disputes (Art. 2948 c.c. and 3 years for INPS obligations) | Art. 6(1)(b) contract; Italian employment law | `is_active` flag set to false on departure; erasure by pseudonymisation on request (see Art. 17 section) |
| Bcrypt password hashes | Same as user account; erasable on Art. 17 request | Art. 6(1)(b) | Replace with pseudonymised string on erasure request |
| Structured application logs | 90 days rolling (operational monitoring); SIEM: 12 months | Legitimate interest (NFR-08, SG-07 security monitoring) | Usernames SHA-256 hashed in all log lines (SEC-P0-005); no plaintext PII in logs |

---

## Security Measures

The following technical and organisational measures (TOMs) are implemented per Art. 32:

| Measure | Implementation | Reference |
|---|---|---|
| Encryption in transit | TLS 1.2+ enforced on all network interfaces; HTTP redirected to HTTPS in production | NFR-10, SG-06 |
| Encryption at rest — passwords | bcrypt cost factor 12; plaintext password never stored or logged | NFR-05 |
| Encryption at rest — backups | AES-256 (TBD — to be confirmed with cloud provider selection; must be documented in the cloud DPA) | NFR-19 |
| Access token security | JWT HS256, secret key >= 32 characters enforced at startup (raises RuntimeError if shorter); 1-hour access token TTL; 24-hour refresh token TTL | SEC-P0-001, NFR-05 |
| Role-based access control | Three RBAC roles (auditor, data_steward, esg_manager) enforced at API middleware and PostgreSQL RLS layer independently (defence in depth) | FR-31, SG-02 |
| Row-level security | PostgreSQL RLS on `raw.*` and `calc.{emissions_consolidated, dq_findings, dlq, audit_log}` tables (M4 migration); security-barrier views `calc.v_kpi_summary` and `calc.v_intensity_metrics` (M7 migration, required because PostgreSQL 15 materialised views do not inherit RLS) | SG-03, SEC-P0-002 |
| Append-only audit trail | `trg_emissions_deny_mutation` trigger blocks UPDATE/DELETE on `calc.emissions_consolidated`; `ops.deny_mutation()` blocks mutation on `calc.dq_findings`, `calc.dlq`, `calc.audit_log` | FR-20, NFR-14, CG-03 |
| PII-free structured logging | Usernames SHA-256 hashed to 16-char prefix in all structured log lines; user IDs truncated to 8 chars after authentication | SEC-P0-005, SG-07 |
| Login rate limiting | 5 login attempts per minute per source IP (in-process slowapi); note: applies per pod in multi-replica deployments (see deployment.md for acknowledged risk SEC-ADV-008) | SEC-P1-003, SG-10 |
| Credential-stuffing probe detection | Failed login and suspicious refresh events logged with `probe_attempt=True` for SIEM alerting | SEC-P1-006 |
| Secret detection in CI | gitleaks runs on every PR and push; no secrets committed to version control | NFR-25, SG-08 |
| Input validation | pandera schema validation on all CSV ingestion paths; Pydantic v2 on all API inputs; parameterised SQL queries throughout | SG-04, SG-05 |

---

## Article 17 Right to Erasure — Reconciliation

This section documents how the controller reconciles erasure rights under GDPR Art. 17
with the append-only audit trail required for CSRD/ISAE 3000 assurance. **Closes COMP-P1-003.**

### Emission records

Emission records in `calc.emissions_consolidated` contain **no personal data** as defined
by GDPR Art. 4(1). They record organisational activity (site-level energy consumption,
material quantities) and calculated tCO2e values. Art. 17 (right to erasure) does not
apply to these records.

Furthermore, even if a broader interpretation were adopted, Art. 17(3)(b) provides an
explicit exception: the right to erasure does not apply "for compliance with a legal
obligation which requires processing by Union or Member State law to which the controller
is subject". The CSRD legal obligation under Art. 6(1)(c) activates this exception.
Emission records must be retained for 10 years per CSRD Art. 19a.

### System-user records

For system-user accounts in `ref.users`, a data subject may exercise the Art. 17 right
to erasure. The controller handles erasure requests for departed employees as follows:

**Pseudonymisation procedure** (deterministic, operator-implementable):

1. Compute the erasure token: `erased_{hashlib.sha256(str(user_id).encode()).hexdigest()[:16]}`
   where `user_id` is the UUID primary key of the user record.
2. Set `ref.users.username = erased_{token}`.
3. Set `ref.users.email = erased_{token}@erased.invalid`.
4. Set `ref.users.password_hash = '[ERASED]'` (bcrypt hash destroyed; login impossible).
5. Set `ref.users.is_active = False`.
6. Retain `ref.users.id`, `ref.users.role_id`, `ref.users.tenant_id`, `ref.users.created_at`.

**Rationale for partial retention**: The `id` UUID appears as `created_by` in the
`calc.audit_log` and as `user_id` in audit trail entries. Deleting the UUID or replacing
it with a random value would break the audit chain required by ISAE 3000 Limited (the
assurance provider must be able to confirm that actions in the audit trail were performed
by an authorised user in the correct role). The pseudonymised `erased_{token}` string is
not personal data: it cannot be linked back to the natural person without access to the
original UUID (which is retained internally for chain-continuity only and cannot be reverse-
engineered to a name or email from the hash alone).

The `created_at` timestamp is retained because it is not personal data per se (it records
when the account was provisioned, not personal attributes of the individual).

**Bcrypt hash destruction** is achieved in step 4 above. The plaintext password is never
stored; the hash is replaced with a non-parseable string, making authentication impossible
for the erased account.

**Record of erasure**: Each erasure action must be logged in `calc.audit_log` with
`action = 'USER_ERASURE_PSEUDONYMISED'`, `user_role = 'controller_admin'`, and the
`user_id` of the administrator performing the erasure. This log entry itself contains no
personal data (the erased user's new `erased_{token}` identifier is already pseudonymised).

---

## DPIA Non-Trigger Rationale

A Data Protection Impact Assessment (DPIA) under GDPR Art. 35 is required when processing
is "likely to result in a high risk to the rights and freedoms of natural persons". The
EDPB Guidelines 09/2022 on Art. 35 identify nine criteria indicative of high risk; processing
meeting two or more criteria likely requires a DPIA.

Assessment for this system against the nine criteria:

| Criterion | Assessment |
|---|---|
| Evaluation or scoring | Not applicable — no profiling of natural persons |
| Automated decision-making with legal effects | Not applicable — all emission calculations are organisational-level; no individual-affecting automated decisions |
| Systematic monitoring | Not applicable — no systematic monitoring of natural persons; login audit logs are for security purposes and contain pseudonymised identifiers |
| Sensitive data (Art. 9/10) | Not applicable — no special-category or criminal-record data |
| Large-scale processing | Not applicable — three internal RBAC roles; not large-scale by any reasonable interpretation |
| Matching or combining datasets | Not applicable |
| Data on vulnerable subjects | Not applicable |
| Innovative use or new technological solution | Not applicable — standard JWT + PostgreSQL + REST API architecture |
| Data subjects prevented from exercising rights | Not applicable — erasure procedure documented above |

**Conclusion**: Fewer than two high-risk criteria are met. A DPIA is **not required** for
v1 of this system. This assessment must be revisited if the scope expands to include
individual-level employee data (e.g. individual commuting records, biometric access logs,
or health-related absence data linked to FTE counts).

---

## Review Cadence

This register must be reviewed at least **annually** by the controller's DPO or compliance
officer, and additionally:

- Before any change to data categories or processing purposes
- Before onboarding a new processor (cloud provider, SaaS tool) that receives personal data
- Before extending the system to process individual-level employee data
- Before a cross-border transfer of personal data outside the EEA

Next scheduled review: 2027-05-14.
