"""
core/apm_agent.py — Application Portfolio Management AI Agent

Performs structured portfolio analysis using the Gartner TIME model:
  T — Tolerate  : Keep running, no new investment. Acceptable but not strategic.
  I — Invest    : Strategic application. Increase capability, modernise, grow.
  M — Migrate   : Good business value, poor technical fit. Re-platform or re-architect.
  E — Eliminate : Low value, poor fit. Plan decommission and capability migration.

Pipeline:
  1. Fetch all applications with lifecycle, ownership, CMDB, and capability data
  2. Score each application across 4 dimensions (Business Value, Technical Fit,
     Risk, Strategic Alignment) — 0 to 10 each
  3. Assign TIME classification based on quadrant position
  4. LLM synthesises portfolio-level recommendations
  5. Return APMPortfolioResult

Scoring dimensions:
  Business Value (0-10):    capability mapping × user count × strategic intent
  Technical Fit  (0-10):    lifecycle status × platform support × CMDB coverage
  Risk           (0-10):    open findings × security gaps × no-owner penalty
  Strategic Align(0-10):    maps to strategic capability × data governance × EA alignment
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from openai import OpenAI
from nexus.config.settings import settings

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai.api_key)
    return _client


# ── TIME model ─────────────────────────────────────────────────────────────────

class TIMEClass(str, Enum):
    TOLERATE  = "Tolerate"
    INVEST    = "Invest"
    MIGRATE   = "Migrate"
    ELIMINATE = "Eliminate"


TIME_COLOURS = {
    TIMEClass.TOLERATE:  "#f59e0b",   # amber
    TIMEClass.INVEST:    "#10b981",   # emerald
    TIMEClass.MIGRATE:   "#3b82f6",   # blue
    TIMEClass.ELIMINATE: "#ef4444",   # red
}

TIME_DESCRIPTIONS = {
    TIMEClass.TOLERATE:  "Keep running, minimal investment. Acceptable technical fit, low strategic value.",
    TIMEClass.INVEST:    "Strategic priority. Increase capability, modernise, expand. High value + good fit.",
    TIMEClass.MIGRATE:   "Good business value but poor technical fit. Re-platform, re-architect, or replace.",
    TIMEClass.ELIMINATE: "Low value, poor fit. Plan decommission, migrate dependent capabilities.",
}


# ── Application scores ─────────────────────────────────────────────────────────

@dataclass
class AppScore:
    app_uri:          str
    app_label:        str
    owner:            str
    lifecycle:        str
    platform:         str
    domain:           str

    # Raw graph counts
    capability_count: int = 0
    dependency_count: int = 0
    consumer_count:   int = 0
    finding_count:    int = 0
    data_asset_count: int = 0

    # Dimension scores 0–10
    business_value:   float = 0.0
    technical_fit:    float = 0.0
    risk_score:       float = 0.0
    strategic_align:  float = 0.0

    # Derived
    portfolio_score:  float = 0.0     # weighted composite
    time_class:       TIMEClass = TIMEClass.TOLERATE
    rationale:        str = ""


@dataclass
class RationalisationAction:
    app_label:    str
    time_class:   TIMEClass
    action:       str
    timeline:     str           # Immediate | 3 months | 6 months | 12 months | 24 months
    saving_band:  str           # Low | Medium | High (cost saving potential)
    risk:         str           # Low | Medium | High (execution risk)
    dependencies: list[str] = field(default_factory=list)


@dataclass
class APMPortfolioResult:
    executive_summary:    str
    portfolio_health:     int                   # 0–100
    app_scores:           list[AppScore]
    time_summary:         dict[str, int]        # TIMEClass → count
    rationalisations:     list[RationalisationAction]
    investment_themes:    list[str]
    quick_wins:           list[str]
    total_apps:           int = 0
    focus_domain:         str = ""
    error:                str | None = None


# ── Scoring helpers ────────────────────────────────────────────────────────────

_LIFECYCLE_FIT: dict[str, float] = {
    "active":      10.0,
    "development": 9.0,
    "pilot":       8.0,
    "maintain":    6.0,
    "sunset":      3.0,
    "legacy":      2.0,
    "retire":      1.0,
    "eol":         0.5,
    "end-of-life": 0.5,
    "":            5.0,   # unknown = neutral
}


def _lifecycle_score(lifecycle: str) -> float:
    lc = lifecycle.lower().strip()
    for key, score in _LIFECYCLE_FIT.items():
        if key and key in lc:
            return score
    return _LIFECYCLE_FIT[""]


def _score_app(app: dict, findings: list[dict], assets: list[dict]) -> AppScore:
    """Score a single application across all 4 dimensions."""
    label    = app.get("appLabel", "Unknown")
    uri      = app.get("app", "")
    owner    = app.get("ownerLabel", "")
    lc       = app.get("lifecycle", "")
    platform = app.get("platform", "")
    domain   = app.get("domain", "")
    cap_cnt  = int(app.get("capCount",  0))
    dep_cnt  = int(app.get("depCount",  0))
    con_cnt  = int(app.get("conCount",  0))
    is_strat = bool(app.get("strategicIntent", ""))

    # Findings for this app
    app_findings = [f for f in findings if label in str(f.get("appLabel", ""))]
    n_findings   = len(app_findings)
    high_findings = sum(1 for f in app_findings if
                        str(f.get("severity", "")).lower() in ("high", "critical"))

    # Data assets for this app
    app_assets   = [a for a in assets if label in str(a.get("appLabel", ""))]
    n_assets     = len(app_assets)

    # ── Business Value (0–10) ──────────────────────────────────────────────────
    bv = min(10.0, (
        (min(cap_cnt,  5) / 5)  * 4.0 +   # capability coverage  (max 4)
        (min(con_cnt, 10) / 10) * 3.0 +   # how many consume it  (max 3)
        (min(n_assets, 5) / 5)  * 2.0 +   # data value           (max 2)
        (1.0 if is_strat else 0.0)         # strategic flag       (max 1)
    ))

    # ── Technical Fit (0–10) ──────────────────────────────────────────────────
    lc_score = _lifecycle_score(lc)
    has_owner  = 1.0 if owner else 0.0
    has_platform = 1.0 if platform else 0.0
    tf = min(10.0, (
        lc_score                * 0.5 +    # lifecycle   (max 5)
        has_owner               * 2.5 +    # ownership   (max 2.5)
        has_platform            * 1.5 +    # platform    (max 1.5)
        (1.0 if dep_cnt < 10 else 0.0)     # not overly coupled (max 1)
    ))

    # ── Risk (0–10 → inverted for health: lower finding → lower risk score) ────
    # We keep raw risk_score as risk LEVEL (high = bad) for display
    risk = min(10.0, (
        high_findings           * 2.0 +    # high/critical findings
        n_findings              * 0.5 +    # total findings
        (2.0 if not owner else 0.0) +      # no owner
        (1.5 if dep_cnt > 15 else 0.0) +   # integration hotspot
        (1.0 if "end-of-life" in lc.lower() or "eol" in lc.lower() else 0.0)
    ))

    # ── Strategic Alignment (0–10) ────────────────────────────────────────────
    sa = min(10.0, (
        (min(cap_cnt, 3) / 3)   * 5.0 +   # capability alignment (max 5)
        (1.0 if is_strat else 0.0) * 3.0 + # strategic intent     (max 3)
        (1.0 if n_assets > 0 else 0.0) * 2.0  # data governance  (max 2)
    ))

    # ── Portfolio score: weighted composite ───────────────────────────────────
    # Risk is inverted (low risk = high score contribution)
    risk_contrib = (10.0 - risk) * 0.2
    portfolio_score = round(
        bv   * 0.35 +
        tf   * 0.25 +
        sa   * 0.20 +
        risk_contrib,
        1
    )

    # ── TIME classification ────────────────────────────────────────────────────
    # Quadrant: high BV + high TF = Invest
    #           low  BV + high TF = Tolerate
    #           high BV + low  TF = Migrate
    #           low  BV + low  TF = Eliminate
    bv_threshold = 4.0
    tf_threshold = 5.0

    if bv >= bv_threshold and tf >= tf_threshold:
        tc = TIMEClass.INVEST
    elif bv < bv_threshold and tf >= tf_threshold:
        tc = TIMEClass.TOLERATE
    elif bv >= bv_threshold and tf < tf_threshold:
        tc = TIMEClass.MIGRATE
    else:
        tc = TIMEClass.ELIMINATE

    # Force Eliminate for severe EoL apps with no value
    if risk >= 7.0 and bv < 3.0:
        tc = TIMEClass.ELIMINATE

    # Rationale
    rationale_parts = []
    if tc == TIMEClass.INVEST:
        rationale_parts.append(f"Supports {cap_cnt} capabilities, strategic fit confirmed.")
    elif tc == TIMEClass.TOLERATE:
        rationale_parts.append(f"Technically sound but limited strategic coverage ({cap_cnt} capabilities).")
    elif tc == TIMEClass.MIGRATE:
        rationale_parts.append(f"Valuable ({cap_cnt} capabilities) but lifecycle '{lc}' signals poor technical fit.")
    elif tc == TIMEClass.ELIMINATE:
        rationale_parts.append(f"Low capability coverage ({cap_cnt}), lifecycle '{lc}'")
        if n_findings > 0:
            rationale_parts.append(f"{n_findings} open findings including {high_findings} high/critical.")

    return AppScore(
        app_uri          = uri,
        app_label        = label,
        owner            = owner,
        lifecycle        = lc,
        platform         = platform,
        domain           = domain,
        capability_count = cap_cnt,
        dependency_count = dep_cnt,
        consumer_count   = con_cnt,
        finding_count    = n_findings,
        data_asset_count = n_assets,
        business_value   = round(bv,  1),
        technical_fit    = round(tf,  1),
        risk_score       = round(risk, 1),
        strategic_align  = round(sa,  1),
        portfolio_score  = portfolio_score,
        time_class       = tc,
        rationale        = " ".join(rationale_parts),
    )


# ── LLM synthesis prompt ───────────────────────────────────────────────────────

_APM_SYSTEM = """You are an Application Portfolio Management expert synthesising a TIME model analysis.

Given a portfolio of applications with TIME classifications and scores, produce:
{
  "executive_summary": "<3–5 sentences. Include counts by TIME class, key themes, top risks.>",
  "portfolio_health": <integer 0–100>,
  "rationalisations": [
    {
      "app_label":   "<exact app name>",
      "time_class":  "Tolerate|Invest|Migrate|Eliminate",
      "action":      "<specific action: e.g. 'Decommission by Q4 2025, migrate HR data to PeopleCore'>",
      "timeline":    "Immediate|3 months|6 months|12 months|24 months",
      "saving_band": "Low|Medium|High",
      "risk":        "Low|Medium|High",
      "dependencies": ["<app name>"]
    }
  ],
  "investment_themes": ["<theme>"],
  "quick_wins": ["<specific action that is high impact and low effort>"]
}

portfolio_health scoring:
  80–100: Healthy portfolio — mostly Invest/Tolerate, few Eliminate
  60–79:  Manageable — moderate tech debt, clear plan needed
  40–59:  Concerning — significant Eliminate/Migrate candidates
  0–39:   Critical — portfolio rationalization urgently required

Rules:
- Only include rationalisations for Migrate and Eliminate apps (highest priority)
- Include up to 3 Invest apps worth calling out for increased funding
- investment_themes: 2–5 strategic themes emerging from the portfolio analysis
- quick_wins: 3–5 actions achievable within 30 days
- Be specific about app names, timelines, and dependencies
- Return ONLY the JSON — no markdown, no preamble
"""


# ── Main entry point ───────────────────────────────────────────────────────────

def run_apm_agent(focus_domain: str = "", user_role: str = "analyst") -> APMPortfolioResult:
    """
    Run the full APM Agent pipeline.

    Args:
        focus_domain: Optional domain filter. Empty = full portfolio.
        user_role:    Requesting user's role.

    Returns:
        APMPortfolioResult with TIME scores, rationalisations, and recommendations.
    """
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    domain_filter = (
        f'FILTER(CONTAINS(LCASE(STR(?domain)), "{focus_domain.lower()}"))'
        if focus_domain else ""
    )

    # ── Q1: Full application inventory with aggregated metrics ─────────────────
    apps_q = f"""
    SELECT ?app ?appLabel ?owner ?ownerLabel ?lifecycle ?platform ?domain ?strategicIntent
           (COUNT(DISTINCT ?cap)      AS ?capCount)
           (COUNT(DISTINCT ?dep)      AS ?depCount)
           (COUNT(DISTINCT ?consumer) AS ?conCount)
    WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label       ?appLabel       }}
        OPTIONAL {{ ?app app:techOwner    ?owner .
                    ?owner rdfs:label     ?ownerLabel     }}
        OPTIONAL {{ ?app app:lifecycle    ?lifecycle      }}
        OPTIONAL {{ ?app app:platform     ?platform       }}
        OPTIONAL {{ ?app ea:domain        ?domain         }}
        OPTIONAL {{ ?app ea:strategicIntent          ?strategicIntent }}
        OPTIONAL {{ ?app ea:enablesBusinessCapability ?cap            }}
        OPTIONAL {{ ?app app:dependsOn               ?dep            }}
        OPTIONAL {{ ?consumer app:dependsOn ?app          }}
        {domain_filter}
    }} GROUP BY ?app ?appLabel ?owner ?ownerLabel ?lifecycle ?platform ?domain ?strategicIntent
    ORDER BY ?appLabel LIMIT 500
    """

    # ── Q2: Open findings per application ─────────────────────────────────────
    findings_q = f"""
    SELECT ?app ?appLabel ?finding ?severity ?status WHERE {{
        ?finding a nexus:AgentFinding ;
                 nexus:affects       ?app ;
                 nexus:findingStatus ?status .
        FILTER(?status != "Resolved")
        ?app a app:Application .
        OPTIONAL {{ ?app     rdfs:label      ?appLabel }}
        OPTIONAL {{ ?finding nexus:severity  ?severity }}
        {domain_filter}
    }} LIMIT 500
    """

    # ── Q3: Data assets per application ───────────────────────────────────────
    assets_q = f"""
    SELECT ?app ?appLabel ?asset ?classification WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label ?appLabel }}
        {{ ?app app:processes ?asset }} UNION
        {{ ?app app:stores    ?asset }} UNION
        {{ ?app app:accesses  ?asset }}
        OPTIONAL {{ ?asset data:classification ?classification }}
        {domain_filter}
    }} LIMIT 500
    """

    raw_apps: list[dict] = []
    raw_findings: list[dict] = []
    raw_assets: list[dict] = []

    try:
        _, raw_apps = db.to_rows(db.query(apps_q))
    except Exception as exc:
        logger.warning("APM apps query failed: %s", exc)

    try:
        _, raw_findings = db.to_rows(db.query(findings_q))
    except Exception as exc:
        logger.warning("APM findings query failed: %s", exc)

    try:
        _, raw_assets = db.to_rows(db.query(assets_q))
    except Exception as exc:
        logger.warning("APM assets query failed: %s", exc)

    # ── Score each application ─────────────────────────────────────────────────
    app_scores: list[AppScore] = [
        _score_app(app, raw_findings, raw_assets)
        for app in raw_apps
    ]

    # Sort by portfolio score descending
    app_scores.sort(key=lambda x: x.portfolio_score, reverse=True)

    # ── TIME summary ───────────────────────────────────────────────────────────
    time_summary = {tc.value: 0 for tc in TIMEClass}
    for s in app_scores:
        time_summary[s.time_class.value] += 1

    # ── Portfolio health: weight by TIME class ─────────────────────────────────
    total = len(app_scores) or 1
    health = max(0, min(100, int(
        100
        - (time_summary.get("Eliminate", 0) / total) * 50
        - (time_summary.get("Migrate",   0) / total) * 20
        + (time_summary.get("Invest",    0) / total) * 10
    )))

    # ── LLM synthesis ─────────────────────────────────────────────────────────
    # Send scored apps (compact for token efficiency)
    scored_compact = [
        {
            "app":         s.app_label,
            "owner":       s.owner,
            "lifecycle":   s.lifecycle,
            "platform":    s.platform,
            "domain":      s.domain,
            "TIME":        s.time_class.value,
            "score":       s.portfolio_score,
            "bv":          s.business_value,
            "tf":          s.technical_fit,
            "risk":        s.risk_score,
            "sa":          s.strategic_align,
            "caps":        s.capability_count,
            "findings":    s.finding_count,
            "rationale":   s.rationale,
        }
        for s in app_scores
    ]

    payload = {
        "focus_domain":  focus_domain or "All domains",
        "total_apps":    len(app_scores),
        "time_summary":  time_summary,
        "portfolio_health_estimate": health,
        "applications":  scored_compact[:80],   # cap for token budget
    }

    try:
        resp = _openai().chat.completions.create(
            model=settings.openai.answer_model,
            messages=[
                {"role": "system", "content": _APM_SYSTEM},
                {"role": "user",   "content": json.dumps(payload, indent=2)},
            ],
            temperature=0.2,
            max_tokens=3000,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",           "", raw).strip()
        data = json.loads(raw)

        rationalisations = []
        for r in data.get("rationalisations", []):
            rationalisations.append(RationalisationAction(
                app_label    = r.get("app_label",   ""),
                time_class   = TIMEClass(r.get("time_class", "Tolerate")),
                action       = r.get("action",      ""),
                timeline     = r.get("timeline",    "12 months"),
                saving_band  = r.get("saving_band", "Medium"),
                risk         = r.get("risk",        "Medium"),
                dependencies = r.get("dependencies", []),
            ))

        return APMPortfolioResult(
            executive_summary  = data.get("executive_summary",   ""),
            portfolio_health   = int(data.get("portfolio_health", health)),
            app_scores         = app_scores,
            time_summary       = time_summary,
            rationalisations   = rationalisations,
            investment_themes  = data.get("investment_themes", []),
            quick_wins         = data.get("quick_wins",        []),
            total_apps         = len(app_scores),
            focus_domain       = focus_domain,
        )

    except Exception as exc:
        logger.error("APM Agent LLM synthesis failed: %s", exc)
        return APMPortfolioResult(
            executive_summary  = "Portfolio synthesis unavailable — LLM call failed.",
            portfolio_health   = health,
            app_scores         = app_scores,
            time_summary       = time_summary,
            rationalisations   = [],
            investment_themes  = [],
            quick_wins         = [],
            total_apps         = len(app_scores),
            focus_domain       = focus_domain,
            error              = str(exc),
        )


def get_app_detail(app_name: str, user_role: str = "analyst") -> dict:
    """
    Fetch detailed portfolio profile for a single application.
    Called from GET /v1/apm/application/{app_name}.
    """
    from nexus.core.stardog_client import get_stardog
    from nexus.agents.context_provider import get_context

    db = get_stardog()

    detail_q = f"""
    SELECT ?app ?appLabel ?owner ?ownerLabel ?lifecycle ?platform ?vendor
           ?domain ?strategicIntent ?hostingEnv
           (COUNT(DISTINCT ?cap)      AS ?capCount)
           (COUNT(DISTINCT ?dep)      AS ?depCount)
           (COUNT(DISTINCT ?consumer) AS ?conCount)
           (COUNT(DISTINCT ?finding)  AS ?findingCount)
    WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label       ?appLabel       }}
        FILTER(CONTAINS(LCASE(STR(?appLabel)), "{app_name.lower()}"))
        OPTIONAL {{ ?app app:techOwner    ?owner .
                    ?owner rdfs:label     ?ownerLabel     }}
        OPTIONAL {{ ?app app:lifecycle    ?lifecycle      }}
        OPTIONAL {{ ?app app:platform     ?platform       }}
        OPTIONAL {{ ?app app:vendor       ?vendor         }}
        OPTIONAL {{ ?app ea:domain        ?domain         }}
        OPTIONAL {{ ?app ea:strategicIntent          ?strategicIntent }}
        OPTIONAL {{ ?app app:hostingEnv              ?hostingEnv     }}
        OPTIONAL {{ ?app ea:enablesBusinessCapability ?cap            }}
        OPTIONAL {{ ?app app:dependsOn               ?dep            }}
        OPTIONAL {{ ?consumer app:dependsOn ?app          }}
        OPTIONAL {{
            ?finding a nexus:AgentFinding ;
                     nexus:affects       ?app ;
                     nexus:findingStatus "Open"
        }}
    }} GROUP BY ?app ?appLabel ?owner ?ownerLabel ?lifecycle ?platform
               ?vendor ?domain ?strategicIntent ?hostingEnv
    LIMIT 1
    """

    try:
        _, rows = db.to_rows(db.query(detail_q))
        if not rows:
            return {"error": f"Application '{app_name}' not found"}

        app_data = rows[0]
        score    = _score_app(app_data, [], [])
        context  = get_context(app_name)

        return {
            "app":             app_data,
            "time_class":      score.time_class.value,
            "portfolio_score": score.portfolio_score,
            "business_value":  score.business_value,
            "technical_fit":   score.technical_fit,
            "risk_score":      score.risk_score,
            "strategic_align": score.strategic_align,
            "rationale":       score.rationale,
            "context":         context.to_dict(),
        }
    except Exception as exc:
        logger.error("get_app_detail(%s): %s", app_name, exc)
        return {"error": str(exc)}
