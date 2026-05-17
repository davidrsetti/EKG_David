"""
core/ai_governance.py — AI Agent Governance Console (D-3)

Runs 4 parallel SPARQL queries to build a complete picture of the AI agent
estate: registry, data access scope, open findings, and tool associations.
Computes an AI Governance Score (0–100) from four signals:
  - Proportion of agents with risk tiers assigned
  - Proportion of agents with designated owners
  - Proportion of agents with no open Critical/High findings
  - Proportion of agents not accessing Restricted data without a risk tier

No existing EA or data governance tool has an AI agent registry integrated
with the business capability model, data classification, and responsible AI
findings in a single queryable graph.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Result types ───────────────────────────────────────────────────────────────

@dataclass
class AgentProfile:
    uri:          str
    label:        str
    risk_tier:    str          # Low | Medium | High | Critical | ""
    platform:     str
    owner:        str
    tools:        list[str]    = field(default_factory=list)
    data_assets:  list[str]    = field(default_factory=list)
    classifications: list[str] = field(default_factory=list)
    open_findings: int         = 0
    critical_findings: int     = 0


@dataclass
class AgentFinding:
    agent_label:  str
    finding_uri:  str
    label:        str
    severity:     str
    status:       str
    asset_label:  str


@dataclass
class AIGovernanceResult:
    agents:            list[AgentProfile]
    findings:          list[AgentFinding]
    governance_score:  int           # 0–100
    score_breakdown:   dict          # signal → score
    total_agents:      int = 0
    agents_with_tiers: int = 0
    agents_with_owners: int = 0
    restricted_unrated: int = 0
    open_critical:      int = 0
    error:              str | None = None

    def __post_init__(self):
        self.total_agents = len(self.agents)


# ── Main entry point ───────────────────────────────────────────────────────────

def run_ai_governance(user_role: str = "analyst") -> AIGovernanceResult:
    """
    Build the full AI governance picture from the live knowledge graph.

    Returns:
        AIGovernanceResult with agent profiles, findings, and governance score.
    """
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    # ── Q1: Agent inventory ───────────────────────────────────────────────────
    q_agents = """
    SELECT DISTINCT ?agent ?agentLabel ?riskTier ?platform ?owner ?ownerLabel WHERE {
        ?agent a ai:Agent .
        OPTIONAL { ?agent rdfs:label    ?agentLabel  }
        OPTIONAL { ?agent ai:riskTier  ?riskTier    }
        OPTIONAL { ?agent ai:platform  ?platform    }
        OPTIONAL { ?agent ai:ownedByUser ?owner .
                   ?owner rdfs:label   ?ownerLabel  }
    } ORDER BY ?agentLabel LIMIT 200
    """

    # ── Q2: Agent → data access ───────────────────────────────────────────────
    q_data = """
    SELECT DISTINCT ?agent ?agentLabel ?asset ?assetLabel ?classification WHERE {
        ?agent a ai:Agent .
        OPTIONAL { ?agent rdfs:label ?agentLabel }
        ?agent (ai:reads | ai:writes | ai:accesses) ?asset .
        OPTIONAL { ?asset rdfs:label          ?assetLabel     }
        OPTIONAL { ?asset data:classification ?classification }
    } LIMIT 500
    """

    # ── Q3: Open findings linked to agents ────────────────────────────────────
    q_findings = """
    SELECT ?finding ?findingLabel ?agentLabel ?severity ?status ?assetLabel WHERE {
        ?finding a nexus:AgentFinding .
        OPTIONAL { ?finding rdfs:label         ?findingLabel }
        OPTIONAL { ?finding nexus:severity     ?severity     }
        OPTIONAL { ?finding nexus:findingStatus ?status      }
        OPTIONAL {
            ?finding nexus:affects ?agent .
            OPTIONAL { ?agent rdfs:label ?agentLabel }
        }
        OPTIONAL {
            ?finding nexus:affects ?asset .
            ?asset a data:Dataset .
            OPTIONAL { ?asset rdfs:label ?assetLabel }
        }
        FILTER(!BOUND(?status) || ?status != "Resolved")
    } ORDER BY ?severity LIMIT 200
    """

    # ── Q4: Agent → tool associations ─────────────────────────────────────────
    q_tools = """
    SELECT DISTINCT ?agent ?agentLabel ?tool ?toolLabel WHERE {
        ?agent a ai:Agent .
        OPTIONAL { ?agent rdfs:label ?agentLabel }
        ?agent ai:hasTool ?tool .
        OPTIONAL { ?tool rdfs:label ?toolLabel }
    } LIMIT 500
    """

    named_queries = [
        ("agents",   q_agents),
        ("data",     q_data),
        ("findings", q_findings),
        ("tools",    q_tools),
    ]
    raw: dict[str, list[dict]] = {}

    def _run(name: str, q: str) -> tuple[str, list[dict]]:
        try:
            _, rows = db.to_rows(db.query(q, inject_prefixes=True))
            logger.info("AI governance query '%s' returned %d rows", name, len(rows))
            return name, rows
        except Exception as exc:
            logger.warning("AI governance query '%s' failed: %s", name, exc)
            return name, []

    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, rows in pool.map(lambda nq: _run(*nq), named_queries):
            raw[name] = rows

    # ── Build agent profiles ───────────────────────────────────────────────────
    profiles: dict[str, AgentProfile] = {}
    for r in raw.get("agents", []):
        uri   = r.get("agent", "")
        label = r.get("agentLabel", uri)
        if not label:
            continue
        profiles[uri] = AgentProfile(
            uri=uri,
            label=label,
            risk_tier=r.get("riskTier", ""),
            platform=r.get("platform", ""),
            owner=r.get("ownerLabel") or r.get("owner", ""),
        )

    # Attach data assets
    for r in raw.get("data", []):
        uri = r.get("agent", "")
        if uri in profiles:
            asset_label = r.get("assetLabel") or r.get("asset", "")
            cls         = r.get("classification", "")
            if asset_label and asset_label not in profiles[uri].data_assets:
                profiles[uri].data_assets.append(asset_label)
            if cls and cls not in profiles[uri].classifications:
                profiles[uri].classifications.append(cls)

    # Attach tools
    for r in raw.get("tools", []):
        uri = r.get("agent", "")
        if uri in profiles:
            tool_label = r.get("toolLabel") or r.get("tool", "")
            if tool_label and tool_label not in profiles[uri].tools:
                profiles[uri].tools.append(tool_label)

    # Attach finding counts
    findings_list: list[AgentFinding] = []
    for r in raw.get("findings", []):
        sev = (r.get("severity") or "").lower()
        agent_label = r.get("agentLabel", "")

        # Link finding count to agent profile
        for p in profiles.values():
            if p.label == agent_label or agent_label in p.label:
                p.open_findings += 1
                if sev in ("critical", "high"):
                    p.critical_findings += 1
                break

        findings_list.append(AgentFinding(
            agent_label=agent_label,
            finding_uri=r.get("finding", ""),
            label=r.get("findingLabel", "Unnamed finding"),
            severity=r.get("severity", ""),
            status=r.get("status", "Open"),
            asset_label=r.get("assetLabel", ""),
        ))

    agents = list(profiles.values())

    # ── Compute governance score ───────────────────────────────────────────────
    score, breakdown = _compute_score(agents)

    restricted_unrated = sum(
        1 for a in agents
        if "Restricted" in a.classifications and not a.risk_tier
    )
    open_critical = sum(a.critical_findings for a in agents)

    return AIGovernanceResult(
        agents=agents,
        findings=findings_list,
        governance_score=score,
        score_breakdown=breakdown,
        agents_with_tiers=sum(1 for a in agents if a.risk_tier),
        agents_with_owners=sum(1 for a in agents if a.owner),
        restricted_unrated=restricted_unrated,
        open_critical=open_critical,
    )


def _compute_score(agents: list[AgentProfile]) -> tuple[int, dict]:
    """Compute AI governance score 0–100 from four signals."""
    n = len(agents)
    if n == 0:
        return 100, {"tier_coverage": 100, "owner_coverage": 100,
                     "finding_health": 100, "data_governance": 100}

    # Signal 1: risk tier coverage (25 pts)
    tier_pct = sum(1 for a in agents if a.risk_tier) / n
    tier_score = round(tier_pct * 25)

    # Signal 2: owner coverage (25 pts)
    owner_pct = sum(1 for a in agents if a.owner) / n
    owner_score = round(owner_pct * 25)

    # Signal 3: no critical/high open findings (25 pts)
    no_critical_pct = sum(1 for a in agents if a.critical_findings == 0) / n
    finding_score = round(no_critical_pct * 25)

    # Signal 4: agents accessing Restricted data have a risk tier (25 pts)
    restricted_agents = [a for a in agents if "Restricted" in a.classifications]
    if restricted_agents:
        governed = sum(1 for a in restricted_agents if a.risk_tier) / len(restricted_agents)
    else:
        governed = 1.0
    data_score = round(governed * 25)

    total = tier_score + owner_score + finding_score + data_score
    return total, {
        "tier_coverage":  tier_score,
        "owner_coverage": owner_score,
        "finding_health": finding_score,
        "data_governance": data_score,
    }
