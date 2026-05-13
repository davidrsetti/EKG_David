"""
agents/registry.py — Agent catalogue & capability lookup.
Queries the NEXUS graph for registered AI agents and their profiles.
"""
from __future__ import annotations
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


def get_agent_profile(agent_id: str) -> dict | None:
    """
    Fetch a registered AI agent's profile from the NEXUS graph.
    Returns None if the agent is not registered.
    """
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    q = f"""
    SELECT ?label ?platform ?vendor ?riskTier ?clearanceLevel ?policy ?ownedBy ?reviewDue WHERE {{
        ?agent a agent:AIAgent ;
               rdfs:label ?label .
        FILTER(CONTAINS(LCASE(STR(?agent)), "{agent_id.lower()}") ||
               CONTAINS(LCASE(STR(?label)), "{agent_id.lower()}"))
        OPTIONAL {{ ?agent agent:platform   ?platform   }}
        OPTIONAL {{ ?agent agent:vendor     ?vendor     }}
        OPTIONAL {{ ?agent agent:riskTier   ?riskTier   }}
        OPTIONAL {{ ?agent sec:clearance    ?clearanceLevel }}
        OPTIONAL {{ ?agent agent:policy     ?policy     }}
        OPTIONAL {{ ?agent agent:ownedBy    ?owner .
                    ?owner rdfs:label       ?ownedBy    }}
        OPTIONAL {{ ?agent agent:reviewDue  ?reviewDue  }}
    }} LIMIT 1
    """
    try:
        _, rows = db.to_rows(db.query(q))
        if not rows:
            return None
        r = rows[0]
        return {
            "agentId":       agent_id,
            "label":         r.get("label", agent_id),
            "platform":      r.get("platform", ""),
            "vendor":        r.get("vendor", ""),
            "riskTier":      r.get("riskTier", "Medium"),
            "clearanceLevel":r.get("clearanceLevel", "Internal"),
            "policy":        r.get("policy", "default-agent-policy"),
            "ownedBy":       r.get("ownedBy", ""),
            "reviewDue":     r.get("reviewDue", ""),
        }
    except Exception as exc:
        logger.error("get_agent_profile(%s): %s", agent_id, exc)
        return None


def list_agents(domain: str = "", risk_tier: str = "") -> list[dict]:
    """List all registered agents, optionally filtered by domain or risk tier."""
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    filters = []
    if domain:
        filters.append(f'FILTER(CONTAINS(LCASE(STR(?domain)), "{domain.lower()}"))')
    if risk_tier:
        filters.append(f'FILTER(LCASE(STR(?riskTier)) = "{risk_tier.lower()}")')
    filter_block = "\n        ".join(filters)

    q = f"""
    SELECT ?agent ?label ?platform ?riskTier ?ownedBy ?reviewDue WHERE {{
        ?agent a agent:AIAgent ;
               rdfs:label ?label .
        OPTIONAL {{ ?agent agent:platform  ?platform  }}
        OPTIONAL {{ ?agent agent:riskTier  ?riskTier  }}
        OPTIONAL {{ ?agent agent:scopedTo  ?domain    }}
        OPTIONAL {{ ?agent agent:ownedBy   ?owner .
                    ?owner rdfs:label      ?ownedBy   }}
        OPTIONAL {{ ?agent agent:reviewDue ?reviewDue }}
        {filter_block}
    }} ORDER BY ?label LIMIT 100
    """
    try:
        _, rows = db.to_rows(db.query(q))
        return rows
    except Exception as exc:
        logger.error("list_agents(): %s", exc)
        return []


def get_agent_tools(agent_id: str) -> list[dict]:
    """Fetch the tools registered for an agent."""
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    q = f"""
    SELECT ?tool ?toolLabel ?endpoint ?rateLimit ?requiredRole WHERE {{
        ?agent a agent:AIAgent ;
               rdfs:label ?agentLabel .
        FILTER(CONTAINS(LCASE(STR(?agentLabel)), "{agent_id.lower()}"))
        ?agent agent:hasTool ?tool .
        OPTIONAL {{ ?tool rdfs:label          ?toolLabel    }}
        OPTIONAL {{ ?tool agent:endpoint      ?endpoint     }}
        OPTIONAL {{ ?tool agent:rateLimit     ?rateLimit    }}
        OPTIONAL {{ ?tool agent:requiresRole  ?requiredRole }}
    }} ORDER BY ?toolLabel
    """
    try:
        _, rows = db.to_rows(db.query(q))
        return rows
    except Exception as exc:
        logger.error("get_agent_tools(%s): %s", agent_id, exc)
        return []
