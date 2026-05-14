# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NEXUS v2** — Enterprise Knowledge Graph Platform. A FastAPI + Streamlit stack that provides natural language querying, Solutions Architecture advising, and Application Portfolio Management over a Stardog RDF/OWL graph. All queries are LLM-translated to SPARQL, with responsible AI guardrails, role-based security filters, PII redaction, and immutable audit logging.

## Setup & Running

```bash
# First-time setup (installs deps, creates .env from example)
setup.bat

# Edit .env with credentials (required before running):
# STARDOG_ENDPOINT, STARDOG_TOKEN, OPENAI_API_KEY

# Start API (port 8000) — in one terminal
start_api.bat
# Equivalent: python -m uvicorn nexus.api.main:app --reload --port 8000 --host 0.0.0.0

# Start UI (port 8501) — in another terminal
start_ui.bat
# Equivalent: python -m streamlit run nexus\ui\app.py --server.port 8501

# Generate a JWT for API testing
generate_token.bat analyst alice
```

Run `validation_app.py` as a standalone Streamlit app to test the full query pipeline interactively without the main UI. It walks through each stage (guard → clarify → SPARQL → execute → synthesise) and shows intermediate results.

## Architecture

### Layer Stack (top to bottom)

```
UI (Streamlit)         ui/app.py, ui/guided_sa_tab.py
API (FastAPI)          api/main.py, api/auth.py, api/middleware.py
Agents                 agents/guard.py, clarifier.py, registry.py, findings.py, session.py, context_provider.py
Core Reasoning         core/nl_to_sparql.py, answer_engine.py, sa_advisor.py, apm_agent.py, artifact_creator.py
Config & Access        config/settings.py, config/ontology_prefixes.py, core/stardog_client.py, core/ontology.py
Audit & Security       audit/logger.py, audit/pii_scanner.py
```

### Query Pipeline

Every natural language question flows through these stages in order:

1. **Guard** (`agents/guard.py`) — LLM classifies intent; blocks unsafe requests (credential exfiltration, mass PII dump, privilege escalation). Returns `GuardResult(allowed, risk_level, reason)`.
2. **Clarifier** (`agents/clarifier.py`) — LLM maps the question to ontology domains/entities. Returns `ClarificationPlan`.
3. **Security Filter** (`guard.py → build_security_filter()`) — injects SPARQL `FILTER` clauses based on JWT role + department; caps row counts by role.
4. **NL→SPARQL** (`core/nl_to_sparql.py`) — uses `o3-mini` (reasoning) to translate to SPARQL with injected prefixes and live ontology snapshot.
5. **Complexity Check** (`stardog_client.py → estimate_complexity()`) — heuristic score on triple patterns/UNION/OPTIONAL depth; rejects if > `MAX_SPARQL_COMPLEXITY`.
6. **Execute** (`core/stardog_client.py`) — HTTP POST to Stardog SPARQL endpoint.
7. **PII Scan** (`audit/pii_scanner.py`) — regex detection + redaction of email, phone, SSN, NINO, IP, passport, credit card.
8. **Synthesise** (`core/answer_engine.py`) — `gpt-4o` turns result set into three-part prose (Direct Answer / Reasoning / Confidence & Caveats).
9. **Audit Log** (`audit/logger.py`) — immutable JSON-L record (file by default; optionally Postgres or Azure Monitor).

### Key Abstractions

| File | What it does |
|------|-------------|
| `config/settings.py` | Single source for all env config. Frozen dataclasses (`StardogSettings`, `OpenAISettings`, etc.). Never call `os.getenv()` outside this file. |
| `config/ontology_prefixes.py` | 40+ RDF namespace PREFIX declarations, `SPARQL_PREFIX_BLOCK` string, and `DOMAIN_HINTS` guide injected into LLM prompts. |
| `core/ontology.py` | Fetches and caches class/property definitions live from Stardog (1-hour TTL). Injected into every SPARQL generation prompt so the LLM always sees the current schema. |
| `core/stardog_client.py` | Thin HTTP wrapper around the Stardog SPARQL endpoint. Also estimates query complexity before execution. |
| `agents/guard.py` | Two-layer safety: (1) LLM intent classification, (2) SPARQL `FILTER` injection for row-level security. These are distinct — one is policy, one is query transformation. |
| `core/artifact_creator.py` | Diagram generator using `@diagram_type(name)` decorator registration. `generate_diagram()` dispatches by type. Each diagram type is a function returning `DiagramResult`. |
| `core/apm_agent.py` | Scores applications against Gartner TIME model (Tolerate / Invest / Migrate / Eliminate). |
| `core/sa_advisor.py` | Produces architectural health reports with scored recommendations (`SARecommendation` with category, priority, effort, impact, quick_win). |

### LLM Model Assignments

Different models are used per task (configurable in `.env`):

| Task | Default Model |
|------|--------------|
| SPARQL generation | `o3-mini` (reasoning) |
| Intent clarification / guard | `gpt-4o-mini` |
| Answer synthesis / SA reports | `gpt-4o` |

Reasoning models (`o3`, `o1` families) use `max_completion_tokens` not `max_tokens`. The `_token_param()` helper in each module handles this automatically.

## Ontology URI Migration

`sparql_corrections.py` is a reference catalog of corrected SPARQL for the v8→v2.1 ontology migration. Key changes:

| Old | New |
|-----|-----|
| `agent:AIAgent` | `ai:Agent` |
| `agent:AgentFinding` | `nexus:AgentFinding` |
| `ea:BusinessCapability` | `ea:BusinessCapabilityL3` |
| `ea:realisedBy` (app→cap) | `ea:enablesBusinessCapability` (direction flipped) |
| Base URI `http://nexus.enterprise.com/` | `https://ontology.ea.example.org/` + `https://nexus.platform/ops#` |

When loading new TTL files or updating SPARQL queries, consult `sparql_corrections.py` first, then test with `validation_app.py`.

## UI Structure

Nine Streamlit tabs (all wired in `ui/app.py`):

| Tab | File | What it does |
|-----|------|-------------|
| 💬 Knowledge Graph Chat | `app.py` | NL query → 9-stage pipeline, SPARQL inspector, PII warnings, audit |
| 🧭 Guided SA Advisor | `guided_sa_tab.py` | 4-step interview → graph-grounded SA recommendation |
| 🏛 Freeform SA Diagram | `app.py` | ArchiMate 3.1 diagram generation via Claude API, draw.io export |
| 📊 Data Query | `data_query_tab.py` | NL→SQL over Unity Catalog, BU/Domain governance panel |
| 📊 Portfolio Intelligence | `portfolio_tab.py` | **QW-1** — APM TIME model quadrant + health score (auto-scored from graph) |
| 🏥 SA Health | `sa_health_tab.py` | **QW-3** — 6-query architecture health: gaps, debt, orphans, hotspots |
| 🗺️ Architecture Diagrams | `diagram_tab.py` | **QW-2** — 7 diagram types from graph (DOT/Mermaid), draw.io export |
| 💥 Change Impact | `impact_tab.py` | **D-1** — 6-traversal blast radius: dependents, capabilities, data, agents, people |
| 🔍 Audit | `audit_tab.py` | **QW-5** — JSONL audit log viewer, metrics, filters, export |

Brand colours: GSK orange `#F36633`.

## Core Modules (complete list)

| File | What it does |
|------|-------------|
| `core/impact_analyzer.py` | Change Impact Radar — 6 parallel SPARQL traversals, GPT-4o narrative |
| `core/apm_agent.py` | Gartner TIME model portfolio scoring (4 dimensions → 0–10 scores) |
| `core/sa_advisor.py` | Portfolio health: 6 queries + LLM synthesis → SAAdvisorResult |
| `core/sa_advisor_v2.py` | Guided SA advisor (ontology-driven, resolves classes at runtime) |
| `core/artifact_creator.py` | 7 diagram types via `@diagram_type()` decorator; returns DOT/Mermaid |
| `core/nl_to_sparql.py` | NL→SPARQL with o3-mini; fallback to gpt-4o; prefix injection |
| `core/nl_to_sql.py` | NL→SQL with keyword blocking; BU/Domain-scoped table context |
| `core/ontology.py` | Live ontology snapshot from Stardog (TTL-cached, thread-safe) |
| `core/stardog_client.py` | Singleton HTTP SPARQL client; complexity estimation |
| `core/databricks_client.py` | Singleton Databricks SQL connector |
| `core/answer_engine.py` | GPT-4o result synthesis (Direct Answer / Reasoning / Caveats) |
| `core/clarifier.py` | Intent mapping → ClarificationPlan (HitL pre-flight) |

## API Endpoints

FastAPI auto-docs at `http://localhost:8000/docs`. Key endpoints:

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/query` | NL or SPARQL query (main pipeline) |
| `POST /v1/sa-advisor` | Full SA Advisor report |
| `POST /v1/apm/analyze` | Portfolio analysis (TIME model) |
| `POST /v1/artifact/diagram` | Generate architecture diagram |
| `POST /v1/impact/analyze` | **Change Impact Radar** — 6-ring blast radius |
| `POST /v1/assert` | Agent writes finding to graph |
| `POST /v1/context` | Fetch entity context bundle |
| `GET  /v1/health/graph` | Graph health metrics (Kubernetes readiness probe) |

All endpoints require a Bearer JWT (`generate_token.bat` creates one for testing).

## Security Notes

- `api/main.py::_safe_filter_param()` — rejects `}`, `{`, `#`, `;` in all filter params (SPARQL injection guard)
- `ui/app.py::make_client()` — calls `invalidate_schema_cache()` on Stardog reconnect (stale ontology fix)
- `config/settings.py` — JWT secret randomised per-process in dev if `JWT_SECRET` unset; fails fast in production
