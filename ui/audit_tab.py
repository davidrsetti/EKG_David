"""
ui/audit_tab.py — Audit & Observability Tab (QW-5)

Reads the structured JSONL audit log (audit/logger.py) and renders a filtered,
paginated view with aggregate metrics for compliance and observability.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import streamlit as st


def _load_audit_log(log_path: str, max_records: int = 5000) -> list[dict]:
    """Read JSONL audit log, most recent first."""
    p = Path(log_path)
    if not p.exists():
        # Try relative to project root
        project_root = Path(__file__).parent.parent
        p = project_root / log_path
    if not p.exists():
        return []
    records = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        return []
    return list(reversed(records[-max_records:]))


def render_audit_tab(user_role: str) -> None:
    """Render the Audit & Observability tab."""
    st.markdown(
        """
        <div style="border-left:4px solid #F36633;padding-left:1rem;margin-bottom:1.5rem">
          <h2 style="margin:0;font-size:1.4rem;color:#1A1A1A">🔍 Audit & Observability</h2>
          <p style="margin:.25rem 0 0;color:#777;font-size:.9rem">
            Live view of all NEXUS interactions — queries, guard events, agent actions, and findings.
            Filterable by event type, user, risk level, and date range.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if user_role not in ("admin", "data-steward"):
        st.warning("Audit log access requires `admin` or `data-steward` role.")
        return

    from nexus.config.settings import settings
    log_path = settings.audit.log_path

    records = _load_audit_log(log_path)

    if not records:
        st.info(f"No audit log entries found at `{log_path}`. "
                "Run some queries to populate the log.")
        return

    # ── Aggregate metrics ──────────────────────────────────────────────────────
    _render_metrics(records)
    st.markdown("---")

    # ── Filters ────────────────────────────────────────────────────────────────
    fcol1, fcol2, fcol3, fcol4 = st.columns([2, 2, 2, 2])
    with fcol1:
        all_event_types = sorted({r.get("event_type", "") for r in records if r.get("event_type")})
        event_filter = st.multiselect("Event type", options=all_event_types, default=[], key="audit_event")
    with fcol2:
        all_users = sorted({r.get("user_id", "") for r in records if r.get("user_id")})
        user_filter = st.multiselect("User", options=all_users, default=[], key="audit_user")
    with fcol3:
        risk_options = ["low", "medium", "high", "blocked"]
        risk_filter = st.multiselect("Risk level", options=risk_options, default=[], key="audit_risk")
    with fcol4:
        days_back = st.selectbox("Time window", options=[1, 7, 30, 90, 0], index=1,
                                  format_func=lambda d: f"Last {d} day{'s' if d!=1 else ''}" if d else "All time",
                                  key="audit_days")

    # ── Apply filters ──────────────────────────────────────────────────────────
    filtered = records
    if event_filter:
        filtered = [r for r in filtered if r.get("event_type") in event_filter]
    if user_filter:
        filtered = [r for r in filtered if r.get("user_id") in user_filter]
    if risk_filter:
        filtered = [r for r in filtered if r.get("risk_level", "").lower() in risk_filter]
    if days_back:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        filtered = [r for r in filtered if r.get("timestamp", "") >= cutoff]

    st.caption(f"Showing {len(filtered)} of {len(records)} events")

    if not filtered:
        st.info("No events match the current filters.")
        return

    # ── Table ──────────────────────────────────────────────────────────────────
    import pandas as pd

    display_cols = ["timestamp", "event_type", "user_id", "user_role", "question",
                    "status", "latency_ms", "pii_detected", "risk_level", "row_count"]
    rows = []
    for r in filtered[:500]:  # cap display at 500
        rows.append({c: r.get(c, "") for c in display_cols})

    df = pd.DataFrame(rows)

    # Format timestamp for readability
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "pii_detected": st.column_config.CheckboxColumn("PII?"),
            "latency_ms":   st.column_config.NumberColumn("Latency (ms)", format="%d ms"),
            "question":     st.column_config.TextColumn("Question", width="large"),
        },
    )

    # ── Export ────────────────────────────────────────────────────────────────
    export_data = "\n".join(json.dumps(r) for r in filtered)
    st.download_button(
        "⬇️ Export filtered JSONL",
        data=export_data,
        file_name="nexus_audit_export.jsonl",
        mime="application/jsonlines",
    )


def _render_metrics(records: list[dict]) -> None:
    """Aggregate metrics strip."""
    total = len(records)
    queries = [r for r in records if r.get("event_type") == "query"]
    guard_blocks = [r for r in records if r.get("event_type") == "guard_check" and not r.get("allowed", True)]
    pii_hits = [r for r in records if r.get("pii_detected") is True]
    errors = [r for r in records if r.get("status") == "error"]

    pii_rate = f"{len(pii_hits)/len(queries)*100:.1f}%" if queries else "—"
    block_rate = f"{len(guard_blocks)/max(len(records),1)*100:.1f}%"

    avg_latency = "—"
    latencies = [r.get("latency_ms") for r in queries if isinstance(r.get("latency_ms"), (int, float))]
    if latencies:
        avg_latency = f"{int(sum(latencies)/len(latencies))} ms"

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    for col, label, value, colour in [
        (c1, "Total Events", total,             "#6b7280"),
        (c2, "Queries",      len(queries),       "#3b82f6"),
        (c3, "Guard Blocks", len(guard_blocks),  "#ef4444" if guard_blocks else "#10b981"),
        (c4, "PII Detections", len(pii_hits),   "#f97316" if pii_hits else "#10b981"),
        (c5, "Errors",       len(errors),        "#ef4444" if errors else "#10b981"),
        (c6, "Avg Latency",  avg_latency,        "#6b7280"),
    ]:
        with col:
            col.metric(label, value)
