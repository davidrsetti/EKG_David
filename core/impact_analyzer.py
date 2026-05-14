"""
core/impact_analyzer.py — Graph-Native Change Impact Radar (D-1)

Given an application/capability/data asset and a proposed change type,
runs 6 parallel SPARQL traversals to compute the full blast radius across:
  1. Direct dependent applications
  2. Indirect (depth-2) dependent applications
  3. Business capabilities that would lose all supporting apps
  4. Restricted/Confidential data assets at risk
  5. AI agents with access to the target's data
  6. People (tech owners) of affected applications

Then synthesises a human-readable impact narrative via GPT-4o.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from openai import OpenAI

from nexus.config.settings import settings
from nexus.core.stardog_client import get_stardog

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai.api_key)
    return _client


# ── Result types ───────────────────────────────────────────────────────────────

@dataclass
class ImpactRing:
    """One concentric ring of the blast radius."""
    label:    str           # e.g. "Direct Dependents"
    icon:     str
    colour:   str
    entities: list[str]     # names of affected entities
    count:    int = 0

    def __post_init__(self):
        self.count = len(self.entities)


@dataclass
class ImpactResult:
    entity:         str
    change_type:    str
    rings:          list[ImpactRing]
    narrative:      str            # LLM synthesis
    mitigations:    list[str]      # concrete mitigation steps
    total_affected: int = 0
    risk_level:     str = "Medium" # Low | Medium | High | Critical
    error:          str | None = None

    def __post_init__(self):
        self.total_affected = sum(r.count for r in self.rings)


# ── Main entry point ───────────────────────────────────────────────────────────

def analyze_change_impact(
    entity: str,
    change_type: str,
    user_role: str = "analyst",
) -> ImpactResult:
    """
    Compute the full blast radius for a proposed change to an application,
    capability, or data asset named `entity`.

    Args:
        entity:      Name or label of the entity being changed.
        change_type: One of: Decommission | Re-platform | Version upgrade | Owner change
        user_role:   Requesting user role (for access control context).

    Returns:
        ImpactResult with six concentric impact rings + LLM narrative.
    """
    db = get_stardog()
    entity_safe = entity.replace('"', '\\"').replace("\\", "\\\\")

    # ── Q1: Direct dependents (apps depending on the target) ──────────────────
    q_direct = f"""
    SELECT DISTINCT ?dep ?depLabel ?depOwner ?depLifecycle WHERE {{
        ?target rdfs:label ?targetLabel .
        FILTER(LCASE(STR(?targetLabel)) = LCASE("{entity_safe}"))
        ?dep a app:Application ;
             app:dependsOn ?target .
        OPTIONAL {{ ?dep rdfs:label    ?depLabel    }}
        OPTIONAL {{ ?dep app:techOwner ?depOwner    }}
        OPTIONAL {{ ?dep app:lifecycle ?depLifecycle }}
    }} LIMIT 50
    """

    # ── Q2: Indirect dependents (depth-2: things that depend on direct deps) ──
    q_indirect = f"""
    SELECT DISTINCT ?app ?appLabel WHERE {{
        ?target rdfs:label ?targetLabel .
        FILTER(LCASE(STR(?targetLabel)) = LCASE("{entity_safe}"))
        ?direct a app:Application ; app:dependsOn ?target .
        ?app    a app:Application ; app:dependsOn ?direct .
        FILTER(?app != ?direct)
        OPTIONAL {{ ?app rdfs:label ?appLabel }}
    }} LIMIT 80
    """

    # ── Q3: Capability risk (capabilities where this app is the ONLY supporter) ─
    q_cap_risk = f"""
    SELECT ?cap ?capLabel (COUNT(?other) AS ?otherApps) WHERE {{
        ?target rdfs:label ?targetLabel .
        FILTER(LCASE(STR(?targetLabel)) = LCASE("{entity_safe}"))
        ?target ea:enablesBusinessCapabilityL3 ?cap .
        OPTIONAL {{ ?cap rdfs:label ?capLabel }}
        OPTIONAL {{
            ?other a app:Application ;
                   ea:enablesBusinessCapabilityL3 ?cap .
            FILTER(?other != ?target)
        }}
    }} GROUP BY ?cap ?capLabel
    HAVING(?otherApps = 0)
    LIMIT 30
    """

    # ── Q4: Data risk (Restricted/Confidential assets processed by target) ────
    q_data_risk = f"""
    SELECT DISTINCT ?asset ?assetLabel ?classification WHERE {{
        ?target rdfs:label ?targetLabel .
        FILTER(LCASE(STR(?targetLabel)) = LCASE("{entity_safe}"))
        ?target (app:processes | app:stores | app:accesses) ?asset .
        ?asset data:classification ?classification .
        FILTER(?classification IN ("Restricted", "Confidential"))
        OPTIONAL {{ ?asset rdfs:label ?assetLabel }}
    }} LIMIT 30
    """

    # ── Q5: Agent risk (AI agents that access the target's data) ─────────────
    q_agent_risk = f"""
    SELECT DISTINCT ?agent ?agentLabel ?riskTier WHERE {{
        ?target rdfs:label ?targetLabel .
        FILTER(LCASE(STR(?targetLabel)) = LCASE("{entity_safe}"))
        ?target (app:processes | app:stores | app:accesses) ?asset .
        ?agent a ai:Agent ;
               (ai:reads | ai:writes | ai:accesses) ?asset .
        OPTIONAL {{ ?agent rdfs:label ?agentLabel }}
        OPTIONAL {{ ?agent ai:riskTier ?riskTier   }}
    }} LIMIT 30
    """

    # ── Q6: People risk (tech owners of all affected apps) ────────────────────
    q_people = f"""
    SELECT DISTINCT ?person ?personLabel ?email WHERE {{
        ?target rdfs:label ?targetLabel .
        FILTER(LCASE(STR(?targetLabel)) = LCASE("{entity_safe}"))
        {{
            ?dep a app:Application ; app:dependsOn ?target .
            ?dep app:techOwner ?person .
        }} UNION {{
            ?dep a app:Application ; app:dependsOn ?target .
            ?app2 a app:Application ; app:dependsOn ?dep .
            ?app2 app:techOwner ?person .
        }}
        OPTIONAL {{ ?person rdfs:label ?personLabel }}
        OPTIONAL {{ ?person hr:mail    ?email        }}
    }} LIMIT 50
    """

    named_queries = [
        ("direct",    q_direct),
        ("indirect",  q_indirect),
        ("cap_risk",  q_cap_risk),
        ("data_risk", q_data_risk),
        ("agents",    q_agent_risk),
        ("people",    q_people),
    ]
    raw: dict[str, list[dict]] = {}

    def _run(name: str, q: str) -> tuple[str, list[dict]]:
        try:
            _, rows = db.to_rows(db.query(q))
            logger.info("Impact query '%s' returned %d rows", name, len(rows))
            return name, rows
        except Exception as exc:
            logger.warning("Impact query '%s' failed: %s", name, exc)
            return name, []

    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, rows in pool.map(lambda nq: _run(*nq), named_queries):
            raw[name] = rows

    # ── Build impact rings ─────────────────────────────────────────────────────
    def _labels(rows: list[dict], *keys: str) -> list[str]:
        out = []
        for r in rows:
            for k in keys:
                v = r.get(k, "")
                if v:
                    out.append(str(v))
                    break
        return list(dict.fromkeys(out))  # deduplicate preserving order

    rings = [
        ImpactRing(
            label="Direct Dependents",
            icon="⚠️",
            colour="#ef4444",
            entities=_labels(raw.get("direct", []), "depLabel", "dep"),
        ),
        ImpactRing(
            label="Indirect Dependents (depth 2)",
            icon="🔶",
            colour="#f97316",
            entities=_labels(raw.get("indirect", []), "appLabel", "app"),
        ),
        ImpactRing(
            label="Capability Gaps",
            icon="🕳",
            colour="#8b5cf6",
            entities=_labels(raw.get("cap_risk", []), "capLabel", "cap"),
        ),
        ImpactRing(
            label="Data Assets at Risk",
            icon="🛡",
            colour="#dc2626",
            entities=_labels(raw.get("data_risk", []), "assetLabel", "asset"),
        ),
        ImpactRing(
            label="AI Agents Affected",
            icon="🤖",
            colour="#7c3aed",
            entities=_labels(raw.get("agents", []), "agentLabel", "agent"),
        ),
        ImpactRing(
            label="People to Notify",
            icon="👤",
            colour="#0891b2",
            entities=_labels(raw.get("people", []), "personLabel", "person"),
        ),
    ]

    # ── Risk level ─────────────────────────────────────────────────────────────
    total = sum(r.count for r in rings)
    cap_gaps = rings[2].count
    data_risks = rings[3].count
    if change_type == "Decommission" and (cap_gaps > 0 or data_risks > 0 or total > 10):
        risk_level = "Critical"
    elif total > 15 or (cap_gaps > 2 and change_type in ("Decommission", "Re-platform")):
        risk_level = "High"
    elif total > 5:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    # ── LLM narrative ──────────────────────────────────────────────────────────
    narrative, mitigations = _synthesise_impact(entity, change_type, rings, risk_level)

    return ImpactResult(
        entity=entity,
        change_type=change_type,
        rings=rings,
        narrative=narrative,
        mitigations=mitigations,
        risk_level=risk_level,
    )


_IMPACT_SYSTEM = """You are an enterprise architect performing a change impact analysis.
Given impact data from a knowledge graph, produce a JSON object:
{
  "narrative": "<3-4 sentence plain-English impact summary. Name specific affected entities. State the risk level and why.>",
  "mitigations": [
    "<specific mitigation step 1>",
    "<specific mitigation step 2>",
    "<specific mitigation step 3>",
    "<specific mitigation step 4>"
  ]
}
Be direct and specific. Use the actual entity names from the data. Return ONLY the JSON object."""


def _synthesise_impact(
    entity: str,
    change_type: str,
    rings: list[ImpactRing],
    risk_level: str,
) -> tuple[str, list[str]]:
    """Call GPT-4o to synthesise a human-readable narrative and mitigation list."""
    ring_summary = "\n".join(
        f"  {r.icon} {r.label} ({r.count}): {', '.join(r.entities[:10]) or 'none'}"
        for r in rings
    )
    user_msg = (
        f"Entity: {entity}\n"
        f"Change type: {change_type}\n"
        f"Risk level: {risk_level}\n\n"
        f"Impact rings from the knowledge graph:\n{ring_summary}"
    )
    try:
        resp = _openai().chat.completions.create(
            model=settings.openai.answer_model,
            messages=[
                {"role": "system", "content": _IMPACT_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=800,
            temperature=0,
        )
        import json
        raw = resp.choices[0].message.content or "{}"
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        return data.get("narrative", ""), data.get("mitigations", [])
    except Exception as exc:
        logger.warning("Impact narrative synthesis failed: %s", exc)
        total = sum(r.count for r in rings)
        fallback = (
            f"Change impact analysis for '{entity}' ({change_type}): "
            f"{total} entities affected across {sum(1 for r in rings if r.count > 0)} impact categories. "
            f"Risk level: {risk_level}."
        )
        return fallback, ["Review all direct dependents before proceeding.",
                          "Notify tech owners of affected applications.",
                          "Validate capability coverage before decommission.",
                          "Assess data asset migration requirements."]
