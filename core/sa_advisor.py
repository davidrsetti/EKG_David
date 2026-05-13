"""
core/sa_advisor.py — Solutions Architect Advisor

Analyses the enterprise knowledge graph to surface architectural patterns,
capability gaps, tech debt, integration risks, and strategic misalignments.
Produces prioritised, actionable SA recommendations via LLM synthesis.

Pipeline:
  1. Run 6 targeted SPARQL queries against the NEXUS graph
  2. Build a structured data payload
  3. LLM (gpt-4o) synthesises into an SA advisory report
  4. Return SAAdvisorResult with structured recommendations

Recommendation categories:
  Gap          — Business capability with no supporting application
  TechDebt     — Application on unsupported / legacy / EoL platform
  Rationalise  — Multiple apps covering same capability (duplication)
  Integration  — Highly coupled app, no API gateway, point-to-point risk
  Orphan       — Application with no owner, no CMDB record, no capability mapping
  Strategic    — Application not aligned to any strategic business capability
  DataRisk     — Application touching Restricted/Confidential data with open findings
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field

from openai import OpenAI
from nexus.config.settings import settings
from nexus.config.ontology_prefixes import LIFECYCLE_STATUSES, RISK_TIERS

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai.api_key)
    return _client


# ── Result types ───────────────────────────────────────────────────────────────

@dataclass
class SARecommendation:
    category:          str            # Gap | TechDebt | Rationalise | Integration | Orphan | Strategic | DataRisk
    priority:          str            # Critical | High | Medium | Low
    title:             str
    affected_entities: list[str]
    detail:            str
    action:            str
    effort:            str            # Low | Medium | High
    impact:            str            # Low | Medium | High
    quick_win:         bool = False   # True if High impact + Low effort


@dataclass
class SAAdvisorResult:
    executive_summary:        str
    architecture_health_score: int          # 0–100
    recommendations:          list[SARecommendation]
    capability_coverage:      dict[str, list[str]]   # capability → [supporting apps]
    capability_gaps:          list[dict]
    tech_debt_apps:           list[dict]
    orphaned_apps:            list[dict]
    integration_hotspots:     list[dict]
    duplicate_capabilities:   list[dict]
    data_risk_apps:           list[dict]
    focus_domain:             str = ""
    error:                    str | None = None


# ── LLM system prompt ──────────────────────────────────────────────────────────

_SA_SYSTEM = """You are a Principal Solutions Architect reviewing enterprise knowledge graph data.

Produce a structured SA advisory report as a JSON object with EXACTLY these keys:
{
  "executive_summary": "<3–5 sentence board-level summary. Be specific about counts and named entities.>",
  "architecture_health_score": <integer 0–100>,
  "recommendations": [
    {
      "category":          "Gap|TechDebt|Rationalise|Integration|Orphan|Strategic|DataRisk",
      "priority":          "Critical|High|Medium|Low",
      "title":             "<concise action-oriented title, max 10 words>",
      "affected_entities": ["<exact app/capability name from the data>"],
      "detail":            "<2–3 sentences: what the problem is, why it matters, quantified where possible>",
      "action":            "<specific, concrete recommendation — what to do, not just 'review'>",
      "effort":            "Low|Medium|High",
      "impact":            "Low|Medium|High",
      "quick_win":         true|false
    }
  ]
}

Scoring guide for architecture_health_score:
  90–100: Excellent — well-governed, no critical gaps
  75–89:  Good      — minor issues, actively managed
  60–74:  Fair      — several gaps, tech debt accumulating
  40–59:  At Risk   — significant gaps, orphaned apps, capability misalignment
  0–39:   Critical  — systemic issues requiring immediate architectural intervention

Rules:
- Name ACTUAL applications, capabilities, and owners from the data provided
- quick_win = true when impact=High AND effort=Low
- Sort recommendations: Critical first, then High, then Medium, then Low
- Maximum 12 recommendations
- architecture_health_score must reflect the COMBINED weight of all findings
- Return ONLY the JSON object — no markdown fences, no preamble, no commentary
"""


# ── Main entry point ───────────────────────────────────────────────────────────

def run_sa_advisor(focus_domain: str = "", user_role: str = "analyst") -> SAAdvisorResult:
    """
    Run the full SA Advisor pipeline for a given domain or all domains.

    Args:
        focus_domain: Optional domain filter (e.g. "finance", "hr"). Empty = all.
        user_role:    Requesting user's role — used for audit context.

    Returns:
        SAAdvisorResult with recommendations, coverage maps, and health score.
    """
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    domain_filter = (
        f'FILTER(CONTAINS(LCASE(STR(?domain)), "{focus_domain.lower()}"))'
        if focus_domain else ""
    )

    # ── Q1: Capability → Application coverage ─────────────────────────────────
    cap_q = f"""
    SELECT ?cap ?capLabel ?app ?appLabel ?lifecycle ?domain WHERE {{
        ?cap a ea:BusinessCapability .
        OPTIONAL {{ ?cap rdfs:label   ?capLabel }}
        OPTIONAL {{ ?cap ea:domain    ?domain   }}
        OPTIONAL {{
            ?app a app:Application ;
                 ea:realisedBy ?cap .
            OPTIONAL {{ ?app rdfs:label   ?appLabel   }}
            OPTIONAL {{ ?app app:lifecycle ?lifecycle  }}
        }}
        {domain_filter}
    }} ORDER BY ?capLabel LIMIT 300
    """

    # ── Q2: Orphaned applications (no owner, no capability, or no CMDB) ────────
    orphan_q = f"""
    SELECT DISTINCT ?app ?appLabel ?platform ?lifecycle ?domain WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label    ?appLabel  }}
        OPTIONAL {{ ?app app:platform  ?platform  }}
        OPTIONAL {{ ?app app:lifecycle ?lifecycle }}
        OPTIONAL {{ ?app ea:domain     ?domain    }}
        FILTER NOT EXISTS {{ ?app app:techOwner ?owner }}
        {domain_filter}
    }} LIMIT 100
    """

    # ── Q3: Integration hotspots (highest dependency count) ───────────────────
    hotspot_q = f"""
    SELECT ?app ?appLabel (COUNT(DISTINCT ?dep) AS ?depCount)
           (COUNT(DISTINCT ?consumer) AS ?consumerCount) WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label ?appLabel }}
        OPTIONAL {{ ?app app:dependsOn ?dep }}
        OPTIONAL {{ ?consumer app:dependsOn ?app }}
        {domain_filter}
    }} GROUP BY ?app ?appLabel
    ORDER BY DESC(?depCount) LIMIT 20
    """

    # ── Q4: Tech debt — legacy/EoL/sunset apps ────────────────────────────────
    techdebt_q = f"""
    SELECT ?app ?appLabel ?lifecycle ?platform ?owner ?ownerLabel ?domain WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label    ?appLabel   }}
        OPTIONAL {{ ?app app:lifecycle ?lifecycle  }}
        OPTIONAL {{ ?app app:platform  ?platform   }}
        OPTIONAL {{ ?app ea:domain     ?domain     }}
        OPTIONAL {{ ?app app:techOwner ?owner .
                    ?owner rdfs:label  ?ownerLabel }}
        FILTER(
            CONTAINS(LCASE(STR(?lifecycle)), "retire")    ||
            CONTAINS(LCASE(STR(?lifecycle)), "legacy")    ||
            CONTAINS(LCASE(STR(?lifecycle)), "end-of-life") ||
            CONTAINS(LCASE(STR(?lifecycle)), "eol")       ||
            CONTAINS(LCASE(STR(?lifecycle)), "sunset")
        )
        {domain_filter}
    }} LIMIT 100
    """

    # ── Q5: Capability gaps — capabilities with NO supporting app ─────────────
    gap_q = f"""
    SELECT ?cap ?capLabel ?domain ?strategicIntent WHERE {{
        ?cap a ea:BusinessCapability .
        OPTIONAL {{ ?cap rdfs:label        ?capLabel       }}
        OPTIONAL {{ ?cap ea:domain         ?domain         }}
        OPTIONAL {{ ?cap ea:strategicIntent ?strategicIntent }}
        FILTER NOT EXISTS {{ ?app ea:realisedBy ?cap }}
        {domain_filter}
    }} LIMIT 100
    """

    # ── Q6: Data risk — Restricted data apps with open findings ───────────────
    datarisk_q = f"""
    SELECT DISTINCT ?app ?appLabel ?classification ?findingLabel ?severity WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label ?appLabel }}
        ?app (app:processes | app:stores | app:accesses) ?asset .
        ?asset data:classification ?classification .
        FILTER(?classification IN ("Restricted", "Confidential"))
        OPTIONAL {{
            ?finding a agent:AgentFinding ;
                     agent:affects ?app ;
                     agent:status  ?status .
            FILTER(?status != "Resolved")
            OPTIONAL {{ ?finding rdfs:label     ?findingLabel }}
            OPTIONAL {{ ?finding agent:severity ?severity     }}
        }}
        {domain_filter}
    }} LIMIT 50
    """

    # ── Execute all queries ────────────────────────────────────────────────────
    results: dict[str, list[dict]] = {}
    for name, q in [
        ("capability", cap_q),
        ("orphans",    orphan_q),
        ("hotspots",   hotspot_q),
        ("techdebt",   techdebt_q),
        ("gaps",       gap_q),
        ("datarisk",   datarisk_q),
    ]:
        try:
            _, rows = db.to_rows(db.query(q))
            results[name] = rows
            logger.info("SA query '%s' returned %d rows", name, len(rows))
        except Exception as exc:
            logger.warning("SA Advisor query '%s' failed: %s", name, exc)
            results[name] = []

    # ── Build capability coverage map ──────────────────────────────────────────
    cap_coverage: dict[str, list[str]] = {}
    for r in results["capability"]:
        cap = r.get("capLabel") or r.get("cap", "Unknown Capability")
        app = r.get("appLabel", "").strip()
        if cap not in cap_coverage:
            cap_coverage[cap] = []
        if app and app not in cap_coverage[cap]:
            cap_coverage[cap].append(app)

    # Identify capabilities with 2+ apps (rationalisation candidates)
    duplicate_caps = [
        {"capability": cap, "apps": apps, "count": len(apps)}
        for cap, apps in cap_coverage.items()
        if len(apps) >= 2
    ]
    duplicate_caps.sort(key=lambda x: x["count"], reverse=True)

    # ── Synthesise with LLM ────────────────────────────────────────────────────
    payload = {
        "focus_domain":            focus_domain or "All domains",
        "capability_coverage_map": {
            k: v for k, v in list(cap_coverage.items())[:40]
        },
        "capability_gaps":         results["gaps"][:30],
        "orphaned_apps":           results["orphans"][:30],
        "integration_hotspots":    results["hotspots"][:15],
        "tech_debt_applications":  results["techdebt"][:30],
        "duplicate_capabilities":  duplicate_caps[:15],
        "data_risk_applications":  results["datarisk"][:20],
        "summary_counts": {
            "total_capabilities":     len(cap_coverage),
            "capability_gaps":        len(results["gaps"]),
            "orphaned_apps":          len(results["orphans"]),
            "tech_debt_apps":         len(results["techdebt"]),
            "duplicate_capabilities": len(duplicate_caps),
            "data_risk_apps":         len(results["datarisk"]),
        },
    }

    try:
        resp = _openai().chat.completions.create(
            model=settings.openai.answer_model,
            messages=[
                {"role": "system", "content": _SA_SYSTEM},
                {"role": "user",   "content": json.dumps(payload, indent=2)},
            ],
            temperature=0.2,
            max_tokens=4000,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",          "", raw).strip()
        data = json.loads(raw)

        recs = []
        for r in data.get("recommendations", []):
            recs.append(SARecommendation(
                category          = r.get("category",          "Strategic"),
                priority          = r.get("priority",          "Medium"),
                title             = r.get("title",             ""),
                affected_entities = r.get("affected_entities", []),
                detail            = r.get("detail",            ""),
                action            = r.get("action",            ""),
                effort            = r.get("effort",            "Medium"),
                impact            = r.get("impact",            "Medium"),
                quick_win         = bool(r.get("quick_win",    False)),
            ))

        return SAAdvisorResult(
            executive_summary         = data.get("executive_summary", ""),
            architecture_health_score = int(data.get("architecture_health_score", 50)),
            recommendations           = recs,
            capability_coverage       = cap_coverage,
            capability_gaps           = results["gaps"],
            tech_debt_apps            = results["techdebt"],
            orphaned_apps             = results["orphans"],
            integration_hotspots      = results["hotspots"],
            duplicate_capabilities    = duplicate_caps,
            data_risk_apps            = results["datarisk"],
            focus_domain              = focus_domain,
        )

    except Exception as exc:
        logger.error("SA Advisor LLM synthesis failed: %s", exc)
        return SAAdvisorResult(
            executive_summary         = "Advisory synthesis unavailable — LLM call failed.",
            architecture_health_score = 0,
            recommendations           = [],
            capability_coverage       = cap_coverage,
            capability_gaps           = results["gaps"],
            tech_debt_apps            = results["techdebt"],
            orphaned_apps             = results["orphans"],
            integration_hotspots      = results["hotspots"],
            duplicate_capabilities    = duplicate_caps,
            data_risk_apps            = results["datarisk"],
            focus_domain              = focus_domain,
            error                     = str(exc),
        )


# ── Ask-a-question mode (uses existing NL pipeline) ───────────────────────────

def ask_sa_question(question: str, user_role: str = "analyst") -> str:
    """
    Answer an ad-hoc SA question using the graph + LLM.
    Reuses nl_to_sparql → execute → synthesise pipeline.
    """
    from nexus.core.nl_to_sparql   import nl_to_sparql
    from nexus.core.stardog_client  import get_stardog
    from nexus.core.answer_engine   import synthesise
    from nexus.agents.guard         import build_security_filter

    sec    = build_security_filter(user_role)
    sparql = nl_to_sparql(
        question,
        user_role=user_role,
        extra_filters=sec.sparql_data_filter,
    )
    db = get_stardog()
    _, rows = db.to_rows(db.query(sparql))
    columns = list(rows[0].keys()) if rows else []
    return synthesise(question, columns, rows[:50], sparql, len(rows))
