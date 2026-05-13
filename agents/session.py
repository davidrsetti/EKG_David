"""
agents/session.py — Conversation session state stored in the NEXUS graph.
Enables multi-turn contextual queries — coreference resolution, entity focus tracking.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BASE    = "http://nexus.enterprise.com/"
SESSION = f"{BASE}session#"


def create_session(user_id: str, user_role: str) -> str:
    """Create a new conversation session in the graph. Returns session_id."""
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    session_id  = f"session_{uuid.uuid4().hex[:16]}"
    session_uri = f"{SESSION}{session_id}"
    now         = datetime.now(timezone.utc).isoformat()
    user_uri    = f"{BASE}hr#{user_id.replace(' ', '_')}"

    sparql = f"""
PREFIX session: <{SESSION}>
PREFIX nexus:   <{BASE}nexus#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:     <http://www.w3.org/2001/XMLSchema#>

INSERT DATA {{
    <{session_uri}> a session:ConversationSession ;
        rdfs:label       "Session {session_id}" ;
        session:userId   "{user_id}" ;
        session:userRole "{user_role}" ;
        session:userRef  <{user_uri}> ;
        session:startedAt "{now}"^^xsd:dateTime ;
        session:turnCount 0 ;
        session:status   "Active" .
}}
"""
    try:
        db.update(sparql)
    except Exception as exc:
        # 401/403 means the Stardog token is read-only or the named graph is
        # write-protected. Session persistence is non-critical — the UI still
        # works fully; multi-turn context just won't be stored in the graph.
        logger.warning("create_session() failed (non-critical, session won't persist): %s", exc)
    return session_id  # always return the ID so the UI can proceed


def update_session(
    session_id: str,
    intent: str,
    entity_focus: list[str],
    turn_count: int,
) -> None:
    """Update session with latest turn context for coreference resolution."""
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    session_uri = f"{SESSION}{session_id}"
    now         = datetime.now(timezone.utc).isoformat()
    focus_triples = "\n    ".join(
        f'<{session_uri}> session:entityFocus <{e}> .' for e in entity_focus
    ) if entity_focus else ""

    sparql = f"""
PREFIX session: <{SESSION}>
PREFIX xsd:     <http://www.w3.org/2001/XMLSchema#>

DELETE {{ <{session_uri}> session:lastIntent  ?i ;
                          session:turnCount   ?t ;
                          session:lastActive  ?a ;
                          session:entityFocus ?f }}
INSERT {{
    <{session_uri}> session:lastIntent  "{_esc(intent)}" ;
                    session:turnCount   {turn_count} ;
                    session:lastActive  "{now}"^^xsd:dateTime .
    {focus_triples}
}}
WHERE {{
    OPTIONAL {{ <{session_uri}> session:lastIntent  ?i }}
    OPTIONAL {{ <{session_uri}> session:turnCount   ?t }}
    OPTIONAL {{ <{session_uri}> session:lastActive  ?a }}
    OPTIONAL {{ <{session_uri}> session:entityFocus ?f }}
}}
"""
    try:
        db.update(sparql)
    except Exception as exc:
        logger.warning("update_session() failed (non-critical): %s", exc)


def get_session_context(session_id: str) -> dict:
    """Retrieve session context for coreference resolution in multi-turn queries."""
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    session_uri = f"{SESSION}{session_id}"
    q = f"""
    SELECT ?lastIntent ?turnCount ?entityFocus ?focusLabel WHERE {{
        <{session_uri}> session:userId ?userId .
        OPTIONAL {{ <{session_uri}> session:lastIntent  ?lastIntent  }}
        OPTIONAL {{ <{session_uri}> session:turnCount   ?turnCount   }}
        OPTIONAL {{ <{session_uri}> session:entityFocus ?entityFocus .
                    ?entityFocus rdfs:label ?focusLabel }}
    }}
    """
    try:
        _, rows = db.to_rows(db.query(q))
        if not rows:
            return {}
        r = rows[0]
        entities = [(row.get("entityFocus",""), row.get("focusLabel","")) for row in rows if row.get("entityFocus")]
        return {
            "last_intent": r.get("lastIntent", ""),
            "turn_count":  int(r.get("turnCount", 0)),
            "entity_focus": entities,
        }
    except Exception:
        return {}


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')