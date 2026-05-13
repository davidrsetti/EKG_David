"""
audit/logger.py — Immutable structured audit log for all NEXUS interactions.
Writes JSON-L records. Supports file, postgres, and azure_monitor sinks.
"""
from __future__ import annotations
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexus.config.settings import settings

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(event_type: str, payload: dict[str, Any]) -> dict:
    return {
        "event_id":    str(uuid.uuid4()),
        "event_type":  event_type,
        "timestamp":   _now(),
        "environment": settings.environment,
        **{k: v for k, v in payload.items() if _is_safe(k, v)},
    }


def _is_safe(key: str, value: Any) -> bool:
    """Scrub credentials from audit records before writing."""
    sensitive = {"token", "password", "secret", "api_key", "authorization"}
    return key.lower() not in sensitive


def _write(record: dict) -> None:
    if not settings.audit.enabled:
        return

    sink = settings.audit.sink
    try:
        if sink == "file":
            _write_file(record)
        elif sink == "postgres":
            _write_postgres(record)
        elif sink == "azure_monitor":
            _write_azure(record)
        else:
            _write_file(record)
    except Exception as exc:
        # Never let audit failure break the main flow
        logger.error("Audit write failed (%s): %s | record: %s", sink, exc, record.get("event_id"))


def _write_file(record: dict) -> None:
    path = Path(settings.audit.log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _write_postgres(record: dict) -> None:
    """Write to a Postgres audit table. Requires AUDIT_DB_URL."""
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(settings.audit.db_url)
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO nexus_audit (event_id, event_type, timestamp, payload) VALUES (%s,%s,%s,%s)",
                (record["event_id"], record["event_type"], record["timestamp"], json.dumps(record)),
            )
    except ImportError:
        logger.warning("psycopg2 not installed — falling back to file audit sink")
        _write_file(record)


def _write_azure(record: dict) -> None:
    """Write to Azure Monitor Log Analytics. Requires AZURE_LOG_WORKSPACE_ID and AZURE_LOG_KEY."""
    try:
        import base64, hashlib, hmac, requests as req
        workspace_id = os.getenv("AZURE_LOG_WORKSPACE_ID", "")
        shared_key   = os.getenv("AZURE_LOG_KEY", "")
        if not workspace_id or not shared_key:
            raise ValueError("Azure Monitor credentials not configured")

        body       = json.dumps([record])
        rfc_date   = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        content_len = len(body)
        string_to_hash = f"POST\n{content_len}\napplication/json\nx-ms-date:{rfc_date}\n/api/logs"
        hashed    = base64.b64encode(hmac.new(base64.b64decode(shared_key), string_to_hash.encode(), hashlib.sha256).digest()).decode()
        signature = f"SharedKey {workspace_id}:{hashed}"

        req.post(
            f"https://{workspace_id}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01",
            headers={"Content-Type": "application/json", "Log-Type": "NexusAudit",
                     "x-ms-date": rfc_date, "Authorization": signature},
            data=body, timeout=5,
        )
    except Exception as exc:
        logger.warning("Azure Monitor write failed (%s) — falling back to file", exc)
        _write_file(record)


# ── Public audit event functions ───────────────────────────────────────

def log_query(
    user_id: str, user_role: str, session_id: str,
    question: str, sparql: str,
    row_count: int, columns: list[str],
    classifications_touched: list[str],
    latency_ms: int, model: str, error: str | None = None,
    risk_level: str = "low", pii_detected: bool = False,
) -> None:
    _write(_event("query", {
        "user_id": user_id, "user_role": user_role, "session_id": session_id,
        "question": question, "sparql_hash": _hash(sparql),
        "row_count": row_count, "columns": columns,
        "classifications_touched": classifications_touched,
        "latency_ms": latency_ms, "llm_model": model,
        "error": error, "risk_level": risk_level, "pii_detected": pii_detected,
    }))


def log_agent_action(
    agent_id: str, action: str, entity_uri: str,
    permitted: bool, policy: str,
    classification: str, domain: str,
) -> None:
    _write(_event("agent_action", {
        "agent_id": agent_id, "action": action, "entity_uri": entity_uri,
        "permitted": permitted, "policy": policy,
        "classification": classification, "domain": domain,
    }))


def log_guard_event(
    user_id: str, question: str, allowed: bool,
    risk_level: str, flags: list[str],
) -> None:
    _write(_event("guard_check", {
        "user_id": user_id, "question_hash": _hash(question),
        "allowed": allowed, "risk_level": risk_level, "flags": flags,
    }))


def log_finding_asserted(agent_id: str, finding_uri: str, severity: str) -> None:
    _write(_event("finding_asserted", {
        "agent_id": agent_id, "finding_uri": finding_uri, "severity": severity,
    }))


def _hash(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()[:16]
