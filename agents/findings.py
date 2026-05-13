"""
agents/findings.py — Agent finding write-back to the NEXUS graph.
Agents call /v1/assert to record discoveries as permanent graph facts.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BASE = "http://nexus.enterprise.com/"


@dataclass
class Finding:
    agent_id:    str
    label:       str
    severity:    str          # Low | Medium | High | Critical
    asset_uri:   str          # The affected entity URI
    description: str
    status:      str = "Open"
    finding_id:  str = ""

    def __post_init__(self):
        if not self.finding_id:
            self.finding_id = f"finding_{uuid.uuid4().hex[:12]}"


def assert_finding(finding: Finding) -> str:
    """
    Write an agent finding to the NEXUS graph.
    Returns the finding URI.
    """
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    now       = datetime.now(timezone.utc).isoformat()
    uri       = f"{BASE}agent#{finding.finding_id}"
    agent_uri = f"{BASE}agent#{finding.agent_id.replace(' ', '_')}"

    sparql_update = f"""
PREFIX agent: <{BASE}agent#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

INSERT DATA {{
    <{uri}> a agent:AgentFinding ;
        rdfs:label      "{_esc(finding.label)}" ;
        agent:foundBy   <{agent_uri}> ;
        agent:foundAt   "{now}"^^xsd:dateTime ;
        agent:affects   <{finding.asset_uri}> ;
        agent:severity  "{finding.severity}" ;
        agent:status    "{finding.status}" ;
        agent:description "{_esc(finding.description)}" .
}}
"""
    try:
        db.update(sparql_update)
        logger.info("Finding asserted: %s", uri)
        return uri
    except Exception as exc:
        logger.error("assert_finding() failed: %s", exc)
        raise


def update_finding_status(finding_uri: str, new_status: str, reviewer_uri: str = "") -> bool:
    """Update the status of an existing finding."""
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    reviewer_triple = (
        f'<{finding_uri}> agent:reviewedBy <{reviewer_uri}> .'
        if reviewer_uri else ""
    )

    sparql_update = f"""
PREFIX agent: <{BASE}agent#>

DELETE {{ <{finding_uri}> agent:status ?oldStatus }}
INSERT {{
    <{finding_uri}> agent:status "{new_status}" .
    {reviewer_triple}
}}
WHERE {{ <{finding_uri}> agent:status ?oldStatus }}
"""
    try:
        db.update(sparql_update)
        return True
    except Exception as exc:
        logger.error("update_finding_status() failed: %s", exc)
        return False


def _esc(s: str) -> str:
    """Escape double quotes and backslashes for SPARQL string literals."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
