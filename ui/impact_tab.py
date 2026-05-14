"""
ui/impact_tab.py — Graph-Native Change Impact Radar (D-1)

The flagship differentiator: given any application, capability, or data asset
and a proposed change type, computes the full blast radius across 6 dimensions
using live graph traversal. No competitor can replicate this because none have
the semantic capability layer + data classification + AI agent registry
all in the same queryable knowledge graph.
"""
from __future__ import annotations
import streamlit as st


_CHANGE_TYPES = [
    "Decommission",
    "Re-platform",
    "Major version upgrade",
    "Owner change",
    "Data classification change",
    "Integration removal",
]

_RISK_COLOURS = {
    "Critical": "#ef4444",
    "High":     "#f97316",
    "Medium":   "#f59e0b",
    "Low":      "#10b981",
}

_RING_EXAMPLE = [
    ("⚠️",  "Direct Dependents",              "#ef4444"),
    ("🔶",  "Indirect Dependents (depth 2)",   "#f97316"),
    ("🕳",  "Capability Gaps",                 "#8b5cf6"),
    ("🛡",  "Data Assets at Risk",             "#dc2626"),
    ("🤖",  "AI Agents Affected",              "#7c3aed"),
    ("👤",  "People to Notify",                "#0891b2"),
]


def render_impact_tab(connected: bool, user_role: str) -> None:
    """Render the Change Impact Radar tab."""
    st.markdown(
        """
        <div style="border-left:4px solid #F36633;padding-left:1rem;margin-bottom:1.5rem">
          <h2 style="margin:0;font-size:1.4rem;color:#1A1A1A">💥 Change Impact Radar</h2>
          <p style="margin:.25rem 0 0;color:#777;font-size:.9rem">
            Full blast radius analysis: 6 parallel graph traversals compute the impact of any
            proposed change across dependents, capabilities, data assets, AI agents, and people.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not connected:
        st.info("Connect to Stardog in the sidebar to run impact analysis.")
        _render_legend()
        return

    # ── Controls ──────────────────────────────────────────────────────────────
    ctrl1, ctrl2, ctrl3 = st.columns([3, 2, 1])
    with ctrl1:
        entity = st.text_input(
            "Application, capability, or data asset",
            placeholder="e.g. SAP ERP, Order-to-Cash, Customer Data Platform",
            key="impact_entity",
        )
    with ctrl2:
        change_type = st.selectbox(
            "Proposed change",
            options=_CHANGE_TYPES,
            key="impact_change_type",
        )
    with ctrl3:
        st.markdown("<br>", unsafe_allow_html=True)
        analyse_btn = st.button(
            "🔍 Analyse Impact",
            key="impact_run",
            type="primary",
            disabled=not entity,
        )

    if analyse_btn or "impact_result" in st.session_state:
        if analyse_btn:
            if not entity:
                st.warning("Enter an application, capability, or data asset name.")
                return
            with st.spinner(f"Running 6 parallel graph traversals for '{entity}'…"):
                try:
                    from nexus.core.impact_analyzer import analyze_change_impact
                    result = analyze_change_impact(
                        entity=entity.strip(),
                        change_type=change_type,
                        user_role=user_role,
                    )
                    st.session_state["impact_result"] = result
                    st.session_state["impact_entity_label"] = entity.strip()
                except Exception as exc:
                    st.error(f"Impact analysis failed: {exc}")
                    return

        result = st.session_state.get("impact_result")
        if result is None:
            return

        _render_risk_banner(result)
        st.markdown("---")
        _render_impact_rings(result)
        st.markdown("---")
        _render_narrative(result)
        _render_mitigations(result)

    else:
        _render_legend()


def _render_risk_banner(result) -> None:
    """Headline risk level and total affected count."""
    rc = _RISK_COLOURS.get(result.risk_level, "#888")
    st.markdown(
        f"""
        <div style="background:#fff;border:1px solid #D8D8D8;border-radius:12px;
                    border-left:6px solid {rc};padding:1rem 1.5rem;
                    display:flex;justify-content:space-between;align-items:center">
          <div>
            <div style="font-size:1.1rem;font-weight:700;color:#1A1A1A">
              {result.change_type}: <em>{result.entity}</em>
            </div>
            <div style="font-size:.85rem;color:#777;margin-top:.2rem">
              {result.total_affected} entities affected across {sum(1 for r in result.rings if r.count>0)} impact categories
            </div>
          </div>
          <div style="text-align:right">
            <div style="font-size:1.4rem;font-weight:700;color:{rc}">{result.risk_level}</div>
            <div style="font-size:.7rem;color:#777;text-transform:uppercase">Risk Level</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_impact_rings(result) -> None:
    """Six impact ring cards, one per traversal dimension."""
    st.markdown("### Impact Rings")

    cols = st.columns(3)
    for i, ring in enumerate(result.rings):
        with cols[i % 3]:
            empty = ring.count == 0
            bg = "#f0fdf4" if empty else "#fff"
            border = ring.colour if not empty else "#10b981"
            count_colour = ring.colour if not empty else "#10b981"
            entity_list = ""
            if ring.entities:
                items = ring.entities[:8]
                entity_list = "".join(
                    f"<div style='font-size:.78rem;color:#444;padding:.1rem 0;"
                    f"border-bottom:1px solid #f0f0f0'>{e}</div>"
                    for e in items
                )
                if ring.count > 8:
                    entity_list += (
                        f"<div style='font-size:.75rem;color:#999;padding:.2rem 0'>"
                        f"+{ring.count - 8} more…</div>"
                    )

            st.markdown(
                f"""
                <div style="background:{bg};border:1px solid {border};border-radius:8px;
                            border-top:4px solid {border};padding:1rem;
                            margin-bottom:.75rem;min-height:140px">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem">
                    <div style="font-size:.8rem;font-weight:600;color:#444">{ring.icon} {ring.label}</div>
                    <div style="font-size:1.4rem;font-weight:700;color:{count_colour}">{ring.count}</div>
                  </div>
                  {"<em style='font-size:.78rem;color:#10b981'>No impact detected</em>" if empty else entity_list}
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_narrative(result) -> None:
    """LLM-synthesised impact narrative."""
    if not result.narrative:
        return
    st.markdown("### Impact Summary")
    st.markdown(
        f"""<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;
                       padding:1rem 1.25rem;font-size:.9rem;line-height:1.6;color:#1A1A1A">
          {result.narrative}
        </div>""",
        unsafe_allow_html=True,
    )


def _render_mitigations(result) -> None:
    """Mitigation checklist."""
    if not result.mitigations:
        return
    st.markdown("### Mitigation Checklist")
    for i, step in enumerate(result.mitigations, 1):
        st.markdown(
            f"""<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;
                           padding:.6rem 1rem;margin-bottom:.4rem;
                           display:flex;align-items:flex-start;gap:.75rem;font-size:.875rem">
              <span style="color:#F36633;font-weight:700;min-width:1.5rem">{i}.</span>
              <span>{step}</span>
            </div>""",
            unsafe_allow_html=True,
        )


def _render_legend() -> None:
    """Show the 6 impact ring types when no analysis has been run."""
    st.markdown("### How it works")
    st.markdown(
        "Enter any application, capability, or data asset name above and choose a change type. "
        "NEXUS runs **6 parallel SPARQL traversals** across the live knowledge graph to compute "
        "the full blast radius:"
    )
    cols = st.columns(3)
    for i, (icon, label, colour) in enumerate(_RING_EXAMPLE):
        with cols[i % 3]:
            st.markdown(
                f"""<div style="background:#fff;border:1px solid {colour};border-radius:8px;
                               border-left:4px solid {colour};padding:.6rem 1rem;
                               margin-bottom:.5rem;font-size:.85rem">
                  <strong>{icon} {label}</strong>
                </div>""",
                unsafe_allow_html=True,
            )
    st.markdown(
        "---\n"
        "**Why no competitor can replicate this:** LeanIX shows direct CMDB relationships. "
        "ServiceNow Impact shows CI dependencies. Neither has the semantic capability layer, "
        "data classification layer, and AI agent registry all in the same queryable graph."
    )
