# Data Protection Impact Assessment (DPIA)

**System**: Carbontrace GHG Accounting Tool  
**Controller**: Gruppo Ceramiche Gresmalt S.p.A.  
**Version**: 1.0.0  
**Date**: 2026-05-14  
**Prepared by**: Data Protection Officer (TBD — see Open Items, Section 8)  
**Legal framework**: GDPR (EU) 2016/679, Italian Legislative Decree 196/2003 as amended by D.Lgs. 101/2018  
**EDPB structure**: This document follows the EDPB "Guidelines on Data Protection Impact Assessment (DPIA)" WP248 rev.01 (2017).

> **DPIA mandatory threshold assessment (GDPR Article 35(3)):**
> Carbontrace does not perform large-scale systematic monitoring of individuals,
> does not process special categories of data (Art. 9), and is not used in a
> publicly accessible space. None of the three mandatory DPIA triggers under
> Art. 35(3) apply. However, the combination of employee PII with a regulatory
> audit trail accessible to external auditors warrants a DPIA as best practice,
> consistent with EDPB WP248 criterion 7 (data concerning vulnerable subjects —
> employees — in an employer context) and criterion 9 (innovative use of
> technology for regulatory reporting).

---

## 1. Description of the Processing

### 1.1 Purpose

Carbontrace processes personal data as part of a GHG emissions accounting
system designed to enable Gresmalt's compliance with:

- **CSRD Directive 2022/2464/EU** and **ESRS E1** (Climate Change disclosure).
- **EU ETS Phase IV** Monitoring, Reporting and Verification (Regulation
  2018/2066 as amended by 2023/2122) for the IANO site (Annex I Activity 17).
- **ISAE 3000** external assurance of sustainability disclosures.

Personal data is incidental to the primary purpose of emissions accounting.
The system would function with pseudonymous identifiers alone; however,
human-readable usernames and email addresses are retained to satisfy the audit
trail requirements of CSRD Art. 33 and ISAE 3000 (auditors must be able to
identify which individual performed which action).

### 1.2 Categories of data subjects

| Category | Description | Estimated count |
|---|---|---|
| Gresmalt employees — data stewards | Operational staff who ingest and validate raw emissions data | ~5–15 |
| Gresmalt employees — ESG managers | Senior staff who review KPIs, approve disclosures, and manage users | ~2–5 |
| External auditors | Third-party assurance providers under NDA with Gresmalt | ~2–4 |

Total estimated data subjects: fewer than 25. Processing is not large-scale.

### 1.3 Categories of personal data

| Data element | Location in system | Classification |
|---|---|---|
| Username (email-format string) | `ref.users.username` | PII — identifiable |
| Email address | `ref.users.email` | PII — identifiable |
| Password hash (bcrypt, never plaintext) | `ref.users.password_hash` | Pseudonymous (hash only) |
| User UUID (sub claim) | `ref.users.id`; JWT `sub` claim; `calc.audit_log.actor_sub` | Pseudonymous |
| IP address | Application logs (structlog JSON to container stdout) | PII — potentially identifiable |
| User-agent string | Application logs | Potentially identifying |
| JWT `jti` (token ID, UUID) | Application logs; in-memory only | Pseudonymous |
| Truncated `sub` in logs | Application logs — only first 8 chars of UUID | Pseudonymous (NFR-08) |

Carbontrace does NOT process: names, phone numbers, physical addresses,
biometric data, health data, financial data, or any special category data
under GDPR Article 9.

### 1.4 Recipients of personal data

| Recipient | Access scope | Legal basis for disclosure |
|---|---|---|
| Internal Gresmalt IT/ops staff | Full DB access for maintenance | Employment contract; legitimate interest (Art. 6(1)(f)) |
| ESG manager (Gresmalt employee) | User management via API; audit log read | Employment obligations (Art. 6(1)(c)) |
| External auditor | Read-only access to `calc.audit_log` and emissions data under NDA | Contractual obligation + CSRD Art. 26 assurance requirement |
| Secrets manager operator | Access to JWT secret and DB credentials only, not to personal data | Legitimate interest (security operations) |

No personal data is disclosed to any advertising platform, data broker, or
third party outside the above.

### 1.5 Retention

| Data element | Retention period | Basis |
|---|---|---|
| `ref.users` active accounts | Duration of employment | GDPR Art. 5(1)(e) storage limitation |
| `ref.users` deactivated accounts | 7 years post-deactivation | Italian Codice Civile art. 2220 (business records); also needed for audit trail attribution |
| `calc.audit_log` (includes `actor_sub` UUID) | 10 years | CSRD Art. 33; ISAE 3000 |
| Application logs (IP address, user-agent) | 90 days | Proportionate to security / incident response needs |
| JWT tokens | TTL: access 1 h, refresh 24 h (NFR-05); no server-side store | Tokens expire and are not retained |

After 7 years post-deactivation, user records in `ref.users` must be
anonymised (replace `username` and `email` with a non-reversible pseudonym,
null out `password_hash`). This anonymisation is a planned cron job — see
Section 3.2 (TODO item).

### 1.6 Transfers outside the EEA

No personal data is transferred outside the European Economic Area. The
PostgreSQL 15 database is hosted in an EU region (to be confirmed by the
infrastructure team — see Open Items, Section 8). Gresmalt employees and
auditors access the system from Italy.

If any object storage (backup bucket) is hosted outside the EU, the WAL
archive and logical backups may contain pseudonymous personal data. Ensure the
backup bucket is also in an EU region or that an adequacy decision / Standard
Contractual Clauses cover the transfer.

---

## 2. Necessity and Proportionality

### 2.1 Lawful basis

| Processing activity | Lawful basis | Article |
|---|---|---|
| Authentication (username, email, password hash) | Compliance with a legal obligation — CSRD requires identified persons to certify data submissions | GDPR Art. 6(1)(c) |
| Audit trail (`actor_sub` in `calc.audit_log`) | Compliance with a legal obligation (CSRD Art. 33) + Legitimate interest in ledger integrity | GDPR Art. 6(1)(c) and Art. 6(1)(f) |
| Application logs (IP, user-agent) | Legitimate interest in security monitoring and incident response | GDPR Art. 6(1)(f) |
| User account management by ESG manager | Compliance with a legal obligation (CSRD operator obligations) | GDPR Art. 6(1)(c) |

There is no consent-based processing in Carbontrace. All processing is
grounded in legal obligation or legitimate interest, which is appropriate for
an employer-employee regulatory compliance tool.

### 2.2 Data minimisation measures

| Measure | Implementation |
|---|---|
| Password never stored in plaintext | `ref.users.password_hash` stores only the bcrypt hash (via `ghg_tool.infrastructure.security.password.hash_password()`). The API never returns or logs the hash. |
| JWT `sub` claim is a UUID, not email | `create_access_token()` in `src/ghg_tool/infrastructure/security/jwt.py` populates `sub` with the user's UUID string, not their email address. |
| Log truncation of `sub` | Per NFR-08, structured log entries truncate `sub` to the first 8 characters of the UUID. Full UUIDs are not present in logs. |
| No PII in error responses | `_safe_error()` in `src/ghg_tool/api/main.py` strips `input`, `url`, and `ctx` fields from Pydantic validation errors (NFR-08, NFR-09). |
| No Swagger UI in production | `GHG_ENVIRONMENT=production` disables `/docs` and `/redoc`, reducing the attack surface and preventing inadvertent disclosure of API schema to unauthenticated users. |
| Correlation IDs are UUIDs | `CorrelationIdMiddleware` generates a new UUID per request. Correlation IDs in logs are not linked to user identity unless the JWT is also present in the same log line (and `sub` is truncated). |

### 2.3 Accuracy

Users can update their own email address via the admin API. Currently only
the `esg_manager` role can update other users' accounts. A self-service
profile update endpoint is planned (TODO — see Open Items, Section 8).

### 2.4 Storage limitation

- Active user accounts: retained while the employment relationship exists.
  The IT manager is responsible for deactivating accounts when employees leave.
- Deactivated accounts: retained 7 years then anonymised by a cron job
  (not yet implemented — see Open Items, Section 8).
- Application logs: 90-day retention policy enforced by the log aggregator
  (e.g. CloudWatch log group retention setting; Loki stream TTL).

### 2.5 Integrity and confidentiality

| Control | Implementation |
|---|---|
| TLS in transit | Mandatory per `docs/deployment.md` Section 4. Plain HTTP is not routable to the application from outside the cluster. |
| Encryption at rest | PostgreSQL volume or managed DB encryption enabled at the infrastructure level (see `docs/deployment.md` Section 5 checklist). |
| Bcrypt password hashing | Bcrypt with cost factor ≥12 recommended. The `hash_password()` function uses the `bcrypt` library. |
| RBAC | Three roles: `data_steward`, `esg_manager`, `auditor`. Role is embedded in the JWT and enforced by API route dependencies. |
| Append-only emission ledger | DB triggers (MG-02) block `UPDATE` and `DELETE` on `calc.emissions_*`. The audit log itself is protected by the same triggers. |
| Rate limiting | `RateLimitMiddleware` limits authenticated users to 100 req/min; the login endpoint is limited to 5 attempts/min/IP (SEC-P1-003). |
| `alg=none` rejection | `decode_token()` in `jwt.py` peeks at the JWT header before decoding and explicitly rejects `alg=none` (SG-01). |

---

## 3. Risk Assessment

### 3.1 Risk register

| # | Threat | Data affected | Impact | Likelihood (before mitigation) | Controls in place | Residual risk |
|---|---|---|---|---|---|---|
| R1 | JWT secret leak → mass session takeover; attacker can impersonate any user | All user sessions; all data accessible by those users | HIGH — attacker gains full API access as any user | LOW — secret stored in secrets manager, not in repo or image | Vault/Secrets Manager; `GHG_ENVIRONMENT=production` enforces secret presence; `_load_jwt_secret()` raises `RuntimeError` if absent | LOW |
| R2 | Database dump exfiltration → bcrypt brute-force on weak passwords | `ref.users.password_hash`; indirectly all emissions data | MEDIUM — bcrypt slows brute force; emissions data itself is not secret (CSRD reports are public) | LOW — DB access requires network + credentials; encryption at rest | Bcrypt hashing; TLS; encryption at rest; network isolation | LOW |
| R3 | Audit log tampering → loss of CSRD defensibility | `calc.audit_log`; `calc.emissions_*` | HIGH — CSRD and ISAE 3000 assurance depends on audit trail integrity | VERY LOW — DB triggers block UPDATE/DELETE at the PostgreSQL level; object-lock on backups | Immutability triggers (MG-02); Object Lock on backup storage; append-only design | VERY LOW |
| R4 | Inadvertent PII in logs (full email in `sub` claim) | IP address; email address in logs | LOW — logs are internal only; `sub` is a UUID not email | ADDRESSED — `sub` is UUID by design; logs truncate to 8 chars; Pydantic validator on `CurrentUser.sub` | NFR-08 implementation; UUID sub; log truncation | VERY LOW |
| R5 | Insider threat: ESG manager creates or modifies user accounts inappropriately | `ref.users` | MEDIUM — could grant unauthorised access | LOW — only `esg_manager` role can manage users; all user operations logged in `calc.audit_log` | RBAC; audit log; separation of duties (IT manager handles infra, ESG manager handles data) | LOW |
| R6 | Unpatched container image vulnerability → remote code execution | Entire database and personal data in scope | HIGH — RCE gives attacker full access | LOW — non-root user `ghg` in container; image rebuilt from `python:3.11-slim`; no dev tools in runtime | Non-root user (NFR-21); minimal runtime image; update policy required (see Open Items) | LOW |
| R7 | External auditor access overly broad | `calc.audit_log`, emissions data, potentially user data | MEDIUM — auditor should see emissions but not user PII beyond attribution | LOW — `auditor` role is read-only; scope of read access defined by API route dependencies | RBAC `auditor` role; NDA with auditor firm | LOW — pending confirmation that `auditor` role excludes `ref.users` read |

### 3.2 Risks requiring additional action

| Risk | Additional action required | Owner | Target date |
|---|---|---|---|
| R1 | Implement JWT secret rotation procedure in the incident playbook | IT manager | TBD |
| R3 | Implement `ops.audit_log_hash_chain` as described in `docs/disaster_recovery.md` Section 5 | Development team | TBD |
| R5 | Implement a self-service account deactivation flow triggered by HR offboarding | Development team | TBD |
| R6 | Establish container image update cadence (monthly base image rebuild) | Ops | TBD |

---

## 4. Measures to Address Risks

| Threat | Mitigation measure | Status |
|---|---|---|
| JWT secret leak (R1) | Store in secrets manager; enforce presence at startup; rotate on any suspected exposure; use RS256 with key pair for higher assurance | Implemented (startup enforcement); RS256 optional upgrade path documented in `docs/deployment.md` |
| Database exfiltration (R2) | Bcrypt hashing; encryption at rest; network isolation; DB credentials in secrets manager | Implemented |
| Audit log tampering (R3) | DB-level immutability triggers (MG-02); append-only schema; Object Lock on backups; future hash chain hardening | Implemented (triggers); hash chain is a future item |
| PII in logs (R4) | UUID `sub` claim; 8-char truncation in logs; Pydantic validator on `CurrentUser.sub`; `_safe_error()` strips input fields | Implemented |
| Insider misuse (R5) | RBAC; all user operations in `calc.audit_log`; separation of duties | Implemented; HR offboarding procedure needed |
| Unpatched image (R6) | Non-root `ghg` user; minimal runtime image; monthly rebuild cadence to be established | Partially implemented; cadence TBD |
| Auditor over-access (R7) | `auditor` role limited to read-only on emissions and audit routes; confirm `ref.users` exclusion in route dependencies | Needs confirmation |

---

## 5. DPO Consultation

### 5.1 Threshold assessment

As noted in the preamble, none of the three mandatory DPIA triggers under
GDPR Article 35(3) apply to Carbontrace:

1. Systematic and extensive profiling: No — the system does not profile individuals.
2. Large-scale processing of special categories: No — no special categories.
3. Systematic monitoring of publicly accessible areas: No — internal enterprise tool.

This DPIA is conducted as best practice.

### 5.2 DPO involvement

The DPO of Gresmalt must:

1. Review this DPIA before the system goes live in production (GDPR Art. 35(2)).
2. Be named in this document (see Open Items, Section 8).
3. Be notified immediately on any DR event that involves suspected data breach
   (see `docs/disaster_recovery.md` Section 7).
4. Review this DPIA annually or when a significant change to the processing
   occurs (e.g. new data categories, new recipients, new jurisdictions).

### 5.3 Residual risk acceptance

The overall residual risk of Carbontrace processing is assessed as LOW.
The ESG manager and the DPO should formally sign off on this assessment before
production go-live. Signature fields are in Section 9.

---

## 6. Record of Processing Activities (ROPA) — Article 30 GDPR

This section constitutes Gresmalt's Article 30 GDPR record for the Carbontrace
processing activity.

| Field | Value |
|---|---|
| **Controller name and contact** | Gruppo Ceramiche Gresmalt S.p.A., [address TBD], Italy |
| **DPO contact** | TBD (see Open Items) |
| **Purpose of processing** | GHG emissions accounting for CSRD / ESRS E1 compliance; EU ETS Phase IV MRV; ISAE 3000 external assurance |
| **Lawful basis** | Art. 6(1)(c) legal obligation (CSRD); Art. 6(1)(f) legitimate interest (audit trail integrity, security) |
| **Categories of data subjects** | Gresmalt employees (data stewards, ESG managers); external auditors |
| **Categories of personal data** | Username, email address, bcrypt password hash, user UUID, IP address (logs), user-agent (logs) |
| **Categories of recipients** | Internal IT/ops; ESG managers; external auditors under NDA |
| **Third-country transfers** | None — all processing in EU region |
| **Retention** | User accounts: duration of employment + 7 years post-deactivation; Audit log: 10 years; Application logs: 90 days |
| **Security measures** | Bcrypt password hashing; TLS in transit; encryption at rest; RBAC (3 roles); DB immutability triggers; in-process rate limiting; non-root container user; secrets manager for credentials |
| **System name** | Carbontrace (Carbontrace GHG Accounting Tool v1.0.0) |
| **System description** | FastAPI + PostgreSQL 15 + Streamlit; containerised; deployed in EU; 7 Gresmalt production sites in scope |
| **Date of record** | 2026-05-14 |
| **Next review** | 2027-05-14 (annual) or on significant change |

---

## 7. Data Subject Rights

| Right | Mechanism | Notes |
|---|---|---|
| Right of access (Art. 15) | ESG manager can export a user's data on request via the admin API | Individual data exports not yet automated; manual process |
| Right to rectification (Art. 16) | ESG manager can update email and username via the admin API | Self-service TBD |
| Right to erasure (Art. 17) | NOT applicable for audit-log entries (CSRD Art. 33 retention obligation overrides); user account data anonymised after 7-year retention period | GDPR Art. 17(3)(b): erasure does not apply where processing is necessary for compliance with a legal obligation |
| Right to restriction (Art. 18) | Can deactivate account (prevents new processing); historical audit log entries retained | |
| Right to data portability (Art. 20) | Not applicable — processing is not based on consent or contract with the data subject | |
| Right to object (Art. 21) | Not applicable — processing is based on legal obligation, not legitimate interest of the controller | Legitimate interest basis in Art. 6(1)(f) for logs; data subjects may object to log retention; to be assessed by DPO |

Data subject requests should be directed to the DPO (contact TBD). Response
deadline: 30 days (GDPR Art. 12(3)), extendable by 2 months for complex
requests.

---

## 8. Open Items Requiring Human Decision Before Production

The following items must be resolved by Gresmalt before this DPIA can be
considered complete. They are tracked here because they affect the accuracy or
completeness of the DPIA, not because they block the technical deployment.

| # | Item | Required action | Owner |
|---|---|---|---|
| OI-1 | DPO identity | Confirm the name and contact of Gresmalt's appointed DPO (or document that Gresmalt is not required to appoint one under Art. 37 and has instead designated a privacy contact) | Gresmalt legal / HR |
| OI-2 | EU region confirmation | Confirm that the production PostgreSQL instance and backup storage bucket are hosted in an EU region (no EEA transfer) | IT manager |
| OI-3 | User anonymisation cron job | Implement and schedule the cron job that anonymises deactivated user accounts after 7 years | Development team |
| OI-4 | Auditor role scope | Confirm that the `auditor` API role excludes read access to `ref.users` (PII table); verify in route dependency code | Development team |
| OI-5 | Self-service email update | Decide whether data subjects (employees) can update their own email address via the UI without ESG manager involvement | Gresmalt ESG manager + DPO |
| OI-6 | Container update cadence | Establish a formal monthly base-image rebuild schedule to address CVEs in `python:3.11-slim` and runtime system libraries | Ops / IT manager |
| OI-7 | DPO sign-off | Obtain formal DPO review and sign-off on this DPIA before production go-live | DPO |
| OI-8 | ESG manager sign-off | Obtain ESG manager sign-off on residual risk acceptance | ESG manager |

---

## 9. Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| DPO | TBD | | |
| ESG Manager | TBD | | |
| IT Manager | TBD | | |

---

## References

- GDPR (EU) 2016/679, Articles 5, 6, 12, 15–22, 30, 33, 35, 37
- EDPB Guidelines on DPIA (WP248 rev.01, 2017)
- Italian Legislative Decree 196/2003 as amended by D.Lgs. 101/2018
- Italian Codice Civile Article 2220 (business record retention 10 years; correspondence 7 years)
- CSRD Directive 2022/2464/EU, Article 33 (sustainability information retention)
- ISAE 3000 (Revised) — Assurance Engagements Other Than Audits or Reviews
- `docs/deployment.md` — security controls, TLS, secrets management
- `docs/disaster_recovery.md` — data breach response procedure (Section 6 and Section 7)
- `docs/methodology.md` — ESG methodology (no additional personal data processing)
- `src/ghg_tool/infrastructure/security/jwt.py` — JWT implementation
- `src/ghg_tool/api/main.py` — middleware stack, PII-stripping in error responses
- `src/ghg_tool/api/middleware/security_headers.py` — security response headers
- `src/ghg_tool/api/middleware/rate_limit.py` — rate limiting controls
- `scripts/create_user.py` — user provisioning (password never in shell history)
