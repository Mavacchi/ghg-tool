# Subagent — Team Multi-Agente

Questa directory contiene **20 subagent Claude Code** in formato `.md` con
frontmatter YAML. Claude Code li riconosce automaticamente al lancio (vedi
`/agents`) e può invocarli:

- **automaticamente**, in base al campo `description` di ciascun file, quando
  la richiesta utente matcha il trigger;
- **esplicitamente**, tramite il `Task` tool (es. delega dell'`OrchestratorAgent`
  a `BackendAgent`).

Il system prompt completo di tutti gli agenti — con le 8 sezioni standard,
glossario ESG e tabella severità — è in
[`../../system_prompts_multi_agent_team.md`](../../system_prompts_multi_agent_team.md).

---

## Indice — 15 agenti ESG specialist

| # | Agent | Model | Tools | Trigger sintetico |
|---|---|---|---|---|
| 1 | `orchestrator-agent` | opus | Read, Task, AskUserQuestion, Bash | Entry point per workflow ESG complessi |
| 2 | `requirements-agent` | sonnet | Read, Edit, Write, AskUserQuestion | Disambigua richieste ESG vaghe |
| 3 | `sustainability-expert-agent` | opus | Read, Edit, Write, WebFetch, WebSearch | Interpretazione normative ESG/GHG/CSRD/EU Tax |
| 4 | `architect-agent` | opus | Read, Edit, Write | Design architetture ESG (append-only ledger, RBAC) |
| 5 | `data-analyst-agent` | opus | Read, Edit, Write, Bash | Calcoli GHG, analisi statistica, normalizzazione |
| 6 | `data-quality-agent` | sonnet | Read, Bash | Validazione DQ (DQ-CRIT su negativi, copertura, outlier) |
| 7 | `backend-agent` | sonnet | Read, Edit, Write, Bash | FastAPI, Pydantic v2, RBAC, append-only endpoint |
| 8 | `data-engineer-agent` | sonnet | Read, Edit, Write, Bash | ETL, PostgreSQL, Alembic, immutable tables |
| 9 | `visualization-agent` | sonnet | Read, Edit, Write, Bash | Streamlit + plotly, dashboard ESG |
| 10 | `test-agent` | sonnet | Read, Edit, Write, Bash | pytest + hypothesis, coverage 85% / 100% calc |
| 11 | `security-agent` | opus | Read, Bash | **GATE BLOCCANTE** — audit OWASP, RLS, secret |
| 12 | `compliance-agent` | opus | Read, Bash | **GATE BLOCCANTE** — GDPR, CSRD audit trail, ESRS |
| 13 | `reviewer-agent` | sonnet | Read, Bash | Code review qualitativa, severità REQUIRED |
| 14 | `debugger-agent` | opus | Read, Edit, Write, Bash | Hypothesis-driven debug, snapshot-only su dati ESG |
| 15 | `documentation-agent` | sonnet | Read, Edit, Write | README, docstring, `docs/methodology.md` |

## Indice — 5 agenti generalisti

| # | Agent | Model | Tools | Trigger sintetico |
|---|---|---|---|---|
| 16 | `python-expert-agent` | sonnet | Read, Edit, Write, Bash | Idiom Python 3.11+, packaging, performance |
| 17 | `devops-agent` | sonnet | Read, Edit, Write, Bash | CI/CD, Docker, GitHub Actions, deploy |
| 18 | `refactor-agent` | sonnet | Read, Edit, Write, Bash | Refactoring sicuro (mai su dati ESG storici) |
| 19 | `cli-architect-agent` | sonnet | Read, Edit, Write, Bash | Strumenti CLI (Click, Typer), UX terminale |
| 20 | `project-scaffolder-agent` | sonnet | Read, Edit, Write, Bash | Bootstrap nuovi progetti (pyproject, ruff, CI) |

---

## Regole trasversali

1. **Gate bloccanti** — nessun deployment può procedere senza `APPROVED`
   esplicito sia da `security-agent` sia da `compliance-agent`.
2. **Severità workflow** — tre livelli ortogonali:
   - `BLOCK` (solo Security/Compliance): ferma tutto.
   - `DQ-CRIT` (solo DataQuality): sospende pipeline.
   - `REQUIRED` (solo Reviewer): must-fix prima del merge, non blocca deploy.
3. **Immutabilità ESG** — nessun agente tocca tabelle emissioni storiche.
   Correzioni come nuova riga con `superseded_by`, mai `UPDATE` né `DELETE`.
4. **Logica ESG centralizzata** — interpretazione normativa solo via
   `sustainability-expert-agent`; calcoli quantitativi solo via
   `data-analyst-agent`. Altri agenti consumano risultati certificati.
5. **GHG calculations** — sempre dichiarare GWP set (AR4/AR5/AR6, default AR6),
   sempre separare Scope 2 location-based e market-based, sempre traceability
   columns (`factor_source`, `factor_version`, `gwp_set`, `methodology`,
   `calc_timestamp`).

---

## Come usarli

### Invocazione automatica
Claude Code legge la `description` di ogni file e attiva l'agente quando il
prompt utente combacia. Esempio: scrivere "calcola Scope 1+2 stabilimenti
italiani 2024" attiva tipicamente `orchestrator-agent` → `requirements-agent`
→ `sustainability-expert-agent` → `data-analyst-agent` → `test-agent` →
`security-agent` + `compliance-agent` → `documentation-agent`.

### Invocazione esplicita
Da dentro Claude Code, oppure programmaticamente via `Task` tool:

```
Task(
  description="Audit sicurezza endpoint emissions",
  subagent_type="security-agent",
  prompt="Esegui audit OWASP + secret scan + RLS check su src/api/emissions.py..."
)
```

### Vedere/gestire gli agent
- `/agents` — lista interattiva degli agent attivi
- `/agents <name>` — dettaglio singolo agent
- Modifiche: edita direttamente i file `.md` in questa directory

---

## Personalizzazione

- I `model` sono indicativi: gli agenti decisori e di interpretazione
  normativa usano `opus`, gli esecutori usano `sonnet`. Modifica liberamente
  nei rispettivi frontmatter.
- I `tools` sono restrittivi per sicurezza (es. `security-agent` ha solo
  Read+Bash, niente Edit/Write). Allarga solo se serve.
- Le `description` sono in inglese perché il matcher Claude Code è ottimizzato
  per l'inglese — il body del prompt invece è in italiano.
