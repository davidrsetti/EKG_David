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

_NEXUS_BASE = "https://nexus.platform/ops#"
_AGENT_BASE  = "https://nexus.platform/ops#"


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
        valid_severities = {"Low", "Medium", "High", "Critical"}
        if self.severity not in valid_severities:
            raise ValueError(f"severity must be one of {valid_severities}, got '{self.severity}'")


def assert_finding(finding: Finding) -> str:
    """
    Write an agent finding to the NEXUS graph.
    Returns the finding URI.
    """
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    now       = datetime.now(timezone.utc).isoformat()
    uri       = f"{_NEXUS_BASE}{finding.finding_id}"
    agent_uri = f"{_AGENT_BASE}{finding.agent_id.replace(' ', '_')}"

    sparql_update = f"""
PREFIX nexus: <{_NEXUS_BASE}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

INSERT DATA {{
    <{uri}> a nexus:AgentFinding ;
        rdfs:label          "{_esc(finding.label)}" ;
        nexus:foundBy       <{agent_uri}> ;
        nexus:foundAt       "{now}"^^xsd:dateTime ;
        nexus:affects       <{finding.asset_uri}> ;
        nexus:severity      "{finding.severity}" ;
        nexus:findingStatus "{finding.status}" ;
        nexus:description   "{_esc(finding.description)}" .
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
        f'<{finding_uri}> nexus:reviewedBy <{reviewer_uri}> .'
        if reviewer_uri else ""
    )

    sparql_update = f"""
PREFIX nexus: <{_NEXUS_BASE}>

DELETE {{ <{finding_uri}> nexus:findingStatus ?oldStatus }}
INSERT {{
    <{finding_uri}> nexus:findingStatus "{new_status}" .
    {reviewer_triple}
}}
WHERE {{ <{finding_uri}> nexus:findingStatus ?oldStatus }}
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
