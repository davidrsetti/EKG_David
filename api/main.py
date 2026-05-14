"""
api/main.py — NEXUS FastAPI application  (v2)

Endpoints (original):
  POST /v1/query         — Natural language or SPARQL query
  POST /v1/context       — Entity context bundle for agents
  GET  /v1/agent/{id}    — Agent profile + tools
  GET  /v1/lineage/{id}  — Data lineage for an asset
  POST /v1/assert        — Write agent findings to graph
  POST /v1/session       — Create/update conversation session
  GET  /v1/health/graph  — Graph health metrics

New endpoints (v2):
  POST /v1/sa-advisor            — Solutions Architect advisory report
  POST /v1/sa-advisor/ask        — Ad-hoc SA question (NL → graph → answer)
  POST /v1/apm/analyze           — Full APM portfolio analysis (TIME model)
  GET  /v1/apm/application/{id}  — Single application TIME score + context
  POST /v1/artifact/diagram      — Generate architecture diagram (DOT or Mermaid)
"""
from __future__ import annotations
import re
import time
import logging
from typing import Annotated, Any

from fastapi import FastAPI, Depends, HTTPException, Body, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nexus.api.auth import AuthenticatedUser, get_current_user, require_role
from nexus.api.middleware import RateLimitMiddleware
from nexus.config.settings import settings

# Characters that can break out of SPARQL string interpolation
_SPARQL_INJECTION_RE = re.compile(r"[}{#;]")


def _safe_filter_param(value: str, param_name: str) -> str:
    """Reject strings that could inject SPARQL via f-string interpolation."""
    if _SPARQL_INJECTION_RE.search(value):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid characters in '{param_name}': characters '}}', '{{', '#', ';' are not allowed.",
        )
    return value

logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="NEXUS Enterprise Knowledge Graph API",
    version="2.0.0",
    description=(
        "Semantic intelligence layer for enterprise AI, agents, and orchestration. "
        "v2: SA Advisor, APM Agent, Artifact Creator."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else ["https://nexus.internal"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    question:              str  = Field(..., min_length=3, max_length=2000, description="Natural language question")
    sparql:                str  = Field("", description="Raw SPARQL (skip NL translation if provided)")
    use_virtual_graph:     bool = Field(False)
    session_id:            str  = Field("")
    clarification_context: str  = Field("")


class QueryResponse(BaseModel):
    question:        str
    sparql:          str
    answer:          str
    columns:         list[str]
    rows:            list[dict]
    row_count:       int
    total_count:     int
    pii_detected:    bool
    redacted:        bool
    latency_ms:      int
    error:           str | None


class ContextRequest(BaseModel):
    entity: str = Field(..., description="Entity name or URI to fetch context for")


class AssertRequest(BaseModel):
    agent_id:    str
    label:       str
    severity:    str = "Medium"
    asset_uri:   str
    description: str


class SessionRequest(BaseModel):
    user_id:   str
    user_role: str = "analyst"


# v2 request models
class SAAdvisorRequest(BaseModel):
    focus_domain: str = Field("", description="Optional domain filter (e.g. 'finance', 'hr'). Empty = all.")


class SAAdvisorAskRequest(BaseModel):
    question: str = Field(..., description="Natural language SA question")


class APMAnalyzeRequest(BaseModel):
    focus_domain: str = Field("", description="Optional domain to scope the portfolio analysis.")


class DiagramRequest(BaseModel):
    diagram_type:  str  = Field(..., description=(
        "Type of diagram: dependency | capability_map | data_lineage | "
        "agent_ecosystem | c4_context | org_ownership | integration"
    ))
    entity:        str  = Field("", description="Entity name to centre diagram on (required for c4_context, data_lineage)")
    depth:         int  = Field(2,  ge=1, le=4, description="Traversal depth")
    fmt:           str  = Field("dot", description="Output format: dot | mermaid")
    domain_filter: str  = Field("", description="Optional domain to scope the diagram")
    max_nodes:     int  = Field(60,  ge=5, le=150, description="Maximum nodes (keep diagrams legible)")


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL ENDPOINTS (unchanged from v1)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/v1/query", response_model=QueryResponse, tags=["Query"])
async def query(req: QueryRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """Execute a natural language question against the NEXUS knowledge graph."""
    from nexus.agents.guard        import check_intent, build_security_filter
    from nexus.core.nl_to_sparql   import nl_to_sparql
    from nexus.core.stardog_client  import get_stardog
    from nexus.core.answer_engine   import synthesise
    from nexus.audit.logger         import log_query, log_guard_event
    from nexus.audit.pii_scanner    import scan_and_redact

    t0       = time.monotonic()
    question = req.question.strip()

    guard = check_intent(question, user.user_role)
    log_guard_event(user.user_id, question, guard.allowed, guard.risk_level.value, guard.flags)
    if not guard.allowed:
        raise HTTPException(status_code=403, detail=f"Query blocked: {guard.reason}")

    sec_filter = build_security_filter(user.user_role, user.department)

    try:
        sparql = req.sparql or nl_to_sparql(
            question,
            clarification_context=req.clarification_context,
            user_role=user.user_role,
            use_virtual_graph=req.use_virtual_graph,
            extra_filters=sec_filter.sparql_data_filter,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"SPARQL generation failed: {exc}")

    db = get_stardog()
    complexity = db.estimate_complexity(sparql)
    if complexity > settings.security.max_sparql_complexity:
        raise HTTPException(status_code=400,
            detail=f"Query complexity {complexity} exceeds limit {settings.security.max_sparql_complexity}.")

    try:
        raw = db.query(sparql)
        columns, rows = db.to_rows(raw)
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        log_query(user.user_id, user.user_role, req.session_id, question, sparql,
                  0, [], [], latency, settings.openai.sparql_model, str(exc))
        raise HTTPException(status_code=500, detail=f"Query execution failed: {exc}")

    total_count = len(rows)
    rows        = rows[:sec_filter.max_rows]
    scan        = scan_and_redact(rows, redact=True)
    classifications = list({r.get("classification", "") for r in rows if r.get("classification")})
    answer      = synthesise(question, columns, scan.redacted_rows, sparql, total_count)
    latency     = int((time.monotonic() - t0) * 1000)
    log_query(user.user_id, user.user_role, req.session_id, question, sparql,
              len(rows), columns, classifications, latency, settings.openai.answer_model,
              pii_detected=scan.pii_found)

    return QueryResponse(
        question=question, sparql=sparql, answer=answer,
        columns=columns, rows=scan.redacted_rows,
        row_count=len(scan.redacted_rows), total_count=total_count,
        pii_detected=scan.pii_found, redacted=scan.pii_found,
        latency_ms=latency, error=None,
    )


@app.post("/v1/context", tags=["Agents"])
async def get_context(req: ContextRequest, user: AuthenticatedUser = Depends(get_current_user)):
    from nexus.agents.context_provider import get_context
    from nexus.agents.guard            import check_agent_permission
    from nexus.audit.logger            import log_agent_action

    bundle = get_context(req.entity, requesting_agent=user.agent_id if user.is_agent else "")
    if user.is_agent and bundle.classification:
        perm = check_agent_permission(user.agent_id, bundle.domain, bundle.classification)
        log_agent_action(user.agent_id, "context_request", bundle.entity_uri,
                         perm.permitted, perm.policy_applied, bundle.classification, bundle.domain)
        if not perm.permitted:
            raise HTTPException(status_code=403, detail=f"Agent denied: {perm.reason}")
    return bundle.to_dict()


@app.get("/v1/agent/{agent_id}", tags=["Agents"])
async def get_agent(agent_id: str = Path(...), user: AuthenticatedUser = Depends(get_current_user)):
    from nexus.agents.registry import get_agent_profile, get_agent_tools
    profile = get_agent_profile(agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return {"profile": profile, "tools": get_agent_tools(agent_id)}


@app.get("/v1/lineage/{asset}", tags=["Data"])
async def get_lineage(
    asset: str = Path(...),
    direction: str = Query("both"),
    depth: int = Query(3, ge=1, le=6),
    user: AuthenticatedUser = Depends(get_current_user),
):
    from nexus.core.stardog_client import get_stardog
    db      = get_stardog()
    results = {}

    if direction in ("upstream", "both"):
        up_q = f"""
        SELECT ?asset ?assetLabel ?upstream ?upstreamLabel WHERE {{
            ?asset rdfs:label ?assetLabel .
            FILTER(CONTAINS(LCASE(STR(?assetLabel)), "{asset.lower()}"))
            ?asset (data:lineageFrom){{1,{depth}}} ?upstream .
            OPTIONAL {{ ?upstream rdfs:label ?upstreamLabel }}
        }} LIMIT 50
        """
        try:
            _, up_rows = db.to_rows(db.query(up_q))
            results["upstream"] = up_rows
        except Exception as exc:
            results["upstream"] = []; results["upstream_error"] = str(exc)

    if direction in ("downstream", "both"):
        down_q = f"""
        SELECT ?asset ?assetLabel ?downstream ?downstreamLabel WHERE {{
            ?asset rdfs:label ?assetLabel .
            FILTER(CONTAINS(LCASE(STR(?assetLabel)), "{asset.lower()}"))
            ?downstream (data:lineageFrom){{1,{depth}}} ?asset .
            OPTIONAL {{ ?downstream rdfs:label ?downstreamLabel }}
        }} LIMIT 50
        """
        try:
            _, down_rows = db.to_rows(db.query(down_q))
            results["downstream"] = down_rows
        except Exception as exc:
            results["downstream"] = []; results["downstream_error"] = str(exc)

    return {"asset": asset, "depth": depth, "lineage": results}


@app.post("/v1/assert", tags=["Agents"])
async def assert_finding(req: AssertRequest, user: AuthenticatedUser = Depends(get_current_user)):
    from nexus.agents.findings import Finding, assert_finding as _assert
    from nexus.audit.logger    import log_finding_asserted

    if not user.is_agent and user.user_role not in ("admin", "data-steward"):
        raise HTTPException(status_code=403, detail="Only agents or admins may assert findings.")

    finding = Finding(agent_id=req.agent_id or user.agent_id or user.user_id,
                      label=req.label, severity=req.severity,
                      asset_uri=req.asset_uri, description=req.description)
    try:
        uri = _assert(finding)
        log_finding_asserted(finding.agent_id, uri, finding.severity)
        return {"status": "asserted", "finding_uri": uri, "finding_id": finding.finding_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to assert finding: {exc}")


@app.post("/v1/session", tags=["Session"])
async def create_or_update_session(req: SessionRequest, user: AuthenticatedUser = Depends(get_current_user)):
    from nexus.agents.session import create_session
    try:
        session_id = create_session(req.user_id or user.user_id, req.user_role or user.user_role)
        return {"session_id": session_id, "status": "created"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/v1/health/graph", tags=["Operations"])
async def graph_health(user: AuthenticatedUser = Depends(require_role("admin", "analyst", "data-steward"))):
    from nexus.core.stardog_client import get_stardog
    db      = get_stardog()
    metrics = {}
    checks  = {
        "total_triples":       "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }",
        "total_people":        "SELECT (COUNT(*) AS ?count) WHERE { ?s a hr:User }",
        "total_apps":          "SELECT (COUNT(*) AS ?count) WHERE { ?s a app:Application }",
        "total_data_assets":   "SELECT (COUNT(*) AS ?count) WHERE { ?s a data:DataAsset }",
        "total_agents":        "SELECT (COUNT(*) AS ?count) WHERE { ?s a ai:Agent }",
        "total_capabilities":  "SELECT (COUNT(*) AS ?count) WHERE { ?s a ea:BusinessCapabilityL3 }",
        "open_findings":       "SELECT (COUNT(*) AS ?count) WHERE { ?s a nexus:AgentFinding ; nexus:findingStatus 'Open' }",
        "orphaned_apps":       "SELECT (COUNT(*) AS ?count) WHERE { ?s a app:Application . FILTER NOT EXISTS { ?s app:techOwner ?o } }",
        "unclassified_assets": "SELECT (COUNT(*) AS ?count) WHERE { ?s a data:DataAsset . FILTER NOT EXISTS { ?s data:classification ?c } }",
        "capability_gaps":     "SELECT (COUNT(*) AS ?count) WHERE { ?s a ea:BusinessCapabilityL3 . FILTER NOT EXISTS { ?a ea:enablesBusinessCapabilityL3 ?s } }",
    }
    for key, q in checks.items():
        try:
            _, rows = db.to_rows(db.query(q, inject_prefixes=True))
            metrics[key] = int(rows[0].get("count", 0)) if rows else 0
        except Exception as exc:
            metrics[key] = f"error: {exc}"

    return {
        "status":  "healthy" if isinstance(metrics.get("total_triples"), int) else "degraded",
        "metrics": metrics,
    }


# ══════════════════════════════════════════════════════════════════════════════
# v2 — SA ADVISOR ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/v1/sa-advisor", tags=["SA Advisor"])
async def sa_advisor(
    req: SAAdvisorRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Run the Solutions Architect Advisor.
    Returns an architectural health score, capability coverage map,
    and prioritised SA recommendations.
    """
    from nexus.core.sa_advisor  import run_sa_advisor
    from nexus.audit.logger     import log_agent_action

    _safe_filter_param(req.focus_domain, "focus_domain")
    t0 = time.monotonic()
    result = run_sa_advisor(
        focus_domain=req.focus_domain,
        user_role=user.user_role,
    )

    log_agent_action(
        agent_id       = user.user_id,
        action         = "sa_advisor_run",
        entity_uri     = req.focus_domain or "all",
        permitted      = True,
        policy         = "sa-advisor-policy",
        classification = "Internal",
        domain         = req.focus_domain or "all",
    )

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    return {
        "executive_summary":         result.executive_summary,
        "architecture_health_score": result.architecture_health_score,
        "focus_domain":              result.focus_domain,
        "latency_ms":                int((time.monotonic() - t0) * 1000),
        "recommendations": [
            {
                "category":          r.category,
                "priority":          r.priority,
                "title":             r.title,
                "affected_entities": r.affected_entities,
                "detail":            r.detail,
                "action":            r.action,
                "effort":            r.effort,
                "impact":            r.impact,
                "quick_win":         r.quick_win,
            }
            for r in result.recommendations
        ],
        "summary": {
            "capability_gaps":        len(result.capability_gaps),
            "tech_debt_apps":         len(result.tech_debt_apps),
            "orphaned_apps":          len(result.orphaned_apps),
            "duplicate_capabilities": len(result.duplicate_capabilities),
            "data_risk_apps":         len(result.data_risk_apps),
        },
        "raw_data": {
            "capability_gaps":     result.capability_gaps[:20],
            "tech_debt_apps":      result.tech_debt_apps[:20],
            "orphaned_apps":       result.orphaned_apps[:20],
            "integration_hotspots":result.integration_hotspots[:10],
        },
    }


@app.post("/v1/sa-advisor/ask", tags=["SA Advisor"])
async def sa_advisor_ask(
    req: SAAdvisorAskRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Answer an ad-hoc SA question using the graph + LLM.
    Reuses the full guard → NL→SPARQL → execute → synthesise pipeline.
    """
    from nexus.agents.guard      import check_intent
    from nexus.core.sa_advisor   import ask_sa_question
    from nexus.audit.logger      import log_guard_event

    guard = check_intent(req.question, user.user_role)
    log_guard_event(user.user_id, req.question, guard.allowed, guard.risk_level.value, guard.flags)
    if not guard.allowed:
        raise HTTPException(status_code=403, detail=f"Blocked: {guard.reason}")

    try:
        answer = ask_sa_question(req.question, user.user_role)
        return {"question": req.question, "answer": answer}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# v2 — APM AGENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/v1/apm/analyze", tags=["APM Agent"])
async def apm_analyze(
    req: APMAnalyzeRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Run the Application Portfolio Management Agent.
    Returns TIME classifications, portfolio health score, and rationalization plan.
    """
    from nexus.core.apm_agent  import run_apm_agent
    from nexus.audit.logger    import log_agent_action

    if user.user_role not in ("admin", "analyst", "data-steward"):
        raise HTTPException(status_code=403, detail="APM analysis requires analyst or higher role.")

    _safe_filter_param(req.focus_domain, "focus_domain")
    t0     = time.monotonic()
    result = run_apm_agent(focus_domain=req.focus_domain, user_role=user.user_role)

    log_agent_action(
        agent_id="apm-agent", action="portfolio_analyze",
        entity_uri=req.focus_domain or "all", permitted=True,
        policy="apm-policy", classification="Internal",
        domain=req.focus_domain or "all",
    )

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    return {
        "executive_summary":  result.executive_summary,
        "portfolio_health":   result.portfolio_health,
        "total_apps":         result.total_apps,
        "focus_domain":       result.focus_domain,
        "latency_ms":         int((time.monotonic() - t0) * 1000),
        "time_summary":       result.time_summary,
        "investment_themes":  result.investment_themes,
        "quick_wins":         result.quick_wins,
        "app_scores": [
            {
                "app":             s.app_label,
                "owner":           s.owner,
                "lifecycle":       s.lifecycle,
                "platform":        s.platform,
                "domain":          s.domain,
                "time_class":      s.time_class.value,
                "portfolio_score": s.portfolio_score,
                "business_value":  s.business_value,
                "technical_fit":   s.technical_fit,
                "risk_score":      s.risk_score,
                "strategic_align": s.strategic_align,
                "capability_count":s.capability_count,
                "finding_count":   s.finding_count,
                "rationale":       s.rationale,
            }
            for s in result.app_scores
        ],
        "rationalisations": [
            {
                "app":          r.app_label,
                "time_class":   r.time_class.value,
                "action":       r.action,
                "timeline":     r.timeline,
                "saving_band":  r.saving_band,
                "risk":         r.risk,
                "dependencies": r.dependencies,
            }
            for r in result.rationalisations
        ],
    }


@app.get("/v1/apm/application/{app_name}", tags=["APM Agent"])
async def apm_application(
    app_name: str = Path(..., description="Application name or fragment"),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Get the TIME score, portfolio metrics, and context bundle for a single application.
    """
    from nexus.core.apm_agent import get_app_detail

    detail = get_app_detail(app_name, user.user_role)
    if "error" in detail:
        raise HTTPException(status_code=404, detail=detail["error"])
    return detail


# ══════════════════════════════════════════════════════════════════════════════
# v2 — ARTIFACT CREATOR ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/v1/artifact/diagram", tags=["Artifact Creator"])
async def generate_diagram(
    req: DiagramRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Generate an architecture diagram from the knowledge graph.
    Returns DOT (Graphviz) or Mermaid source code.

    Diagram types:
      dependency     — Application dependency map
      capability_map — Business capability map with supporting apps
      data_lineage   — Data lineage from source to consumption
      agent_ecosystem— AI agent ecosystem (agents, tools, data)
      c4_context     — C4 Context diagram for a single application
      org_ownership  — Ownership/accountability map
      integration    — Integration topology
    """
    from nexus.core.artifact_creator import generate_diagram, ENTITY_REQUIRED
    from nexus.audit.logger          import log_agent_action

    _safe_filter_param(req.entity, "entity")
    _safe_filter_param(req.domain_filter, "domain_filter")
    if req.diagram_type in ENTITY_REQUIRED and not req.entity:
        raise HTTPException(
            status_code=400,
            detail=f"Diagram type '{req.diagram_type}' requires an entity name.",
        )

    if req.fmt not in ("dot", "mermaid"):
        raise HTTPException(status_code=400, detail="fmt must be 'dot' or 'mermaid'")

    result = generate_diagram(
        diagram_type  = req.diagram_type,
        entity        = req.entity,
        depth         = req.depth,
        fmt           = req.fmt,
        domain_filter = req.domain_filter,
        max_nodes     = req.max_nodes,
    )

    log_agent_action(
        agent_id=user.user_id, action="diagram_generated",
        entity_uri=req.entity or req.domain_filter or "all",
        permitted=True, policy="artifact-policy",
        classification="Internal", domain=req.domain_filter or "all",
    )

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    return {
        "diagram_type": result.diagram_type,
        "entity":       result.entity,
        "fmt":          result.fmt,
        "title":        result.title,
        "node_count":   result.node_count,
        "edge_count":   result.edge_count,
        "content":      result.content,
    }


@app.get("/v1/artifact/diagram-types", tags=["Artifact Creator"])
async def diagram_types(user: AuthenticatedUser = Depends(get_current_user)):
    """List all available diagram types with descriptions."""
    from nexus.core.artifact_creator import DIAGRAM_TYPES, ENTITY_REQUIRED
    return {
        k: {"description": v, "entity_required": k in ENTITY_REQUIRED}
        for k, v in DIAGRAM_TYPES.items()
    }


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE IMPACT RADAR (D-1)
# ══════════════════════════════════════════════════════════════════════════════

class ImpactRequest(BaseModel):
    entity:      str = Field(..., description="Name of the app, capability, or data asset being changed")
    change_type: str = Field("Decommission", description=(
        "Proposed change: Decommission | Re-platform | Major version upgrade | "
        "Owner change | Data classification change | Integration removal"
    ))


@app.post("/v1/impact/analyze", tags=["Change Impact"])
async def analyze_impact(
    req: ImpactRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Compute the full blast radius of a proposed change to an application,
    capability, or data asset.

    Runs 6 parallel SPARQL traversals:
    - Direct dependent applications
    - Indirect (depth-2) dependent applications
    - Business capability gaps created
    - Restricted/Confidential data assets at risk
    - AI agents affected
    - Tech owners to notify

    Returns impact rings, risk level, narrative, and mitigation checklist.
    """
    _safe_filter_param(req.entity, "entity")
    from nexus.core.impact_analyzer import analyze_change_impact
    from nexus.audit.logger import log_agent_action

    result = analyze_change_impact(
        entity=req.entity,
        change_type=req.change_type,
        user_role=user.user_role,
    )
    log_agent_action(
        agent_id="impact-analyzer", action="change_impact",
        entity_uri=req.entity, permitted=True,
        policy="impact-policy", classification="Internal",
        domain=req.entity,
    )
    return {
        "entity":         result.entity,
        "change_type":    result.change_type,
        "risk_level":     result.risk_level,
        "total_affected": result.total_affected,
        "narrative":      result.narrative,
        "mitigations":    result.mitigations,
        "rings": [
            {
                "label":    r.label,
                "icon":     r.icon,
                "count":    r.count,
                "entities": r.entities,
            }
            for r in result.rings
        ],
        "error": result.error,
    }
