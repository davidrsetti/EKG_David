"""
ui/sa_health_tab.py — SA Portfolio Health Tab (QW-3)

Exposes the fully-built SA Advisor engine (core/sa_advisor.py) in the UI.
Shows a portfolio-wide architectural health view with capability gaps,
tech debt, orphaned apps, and prioritised recommendations.
"""
from __future__ import annotations
import streamlit as st


_PRIORITY_COLOUR = {
    "Critical": "#ef4444",
    "High":     "#f97316",
    "Medium":   "#f59e0b",
    "Low":      "#6b7280",
}
_PRIORITY_ICON = {
    "Critical": "🔴",
    "High":     "🟠",
    "Medium":   "🟡",
    "Low":      "⚪",
}
_CATEGORY_ICON = {
    "Gap":           "🕳",
    "TechDebt":      "⚙️",
    "Rationalise":   "🔀",
    "Integration":   "🔗",
    "Orphan":        "👻",
    "Strategic":     "🧭",
    "DataRisk":      "🛡",
}


def _health_colour(score: int) -> str:
    if score >= 75:
        return "#10b981"
    if score >= 50:
        return "#f59e0b"
    return "#ef4444"


def _health_label(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    if score >= 40:
        return "At Risk"
    return "Critical"


def render_sa_health_tab(connected: bool, user_role: str) -> None:
    """Render the SA Portfolio Health tab."""
    st.markdown(
        """
        <div style="border-left:4px solid #F36633;padding-left:1rem;margin-bottom:1.5rem">
          <h2 style="margin:0;font-size:1.4rem;color:#1A1A1A">🏥 Architecture Portfolio Health</h2>
          <p style="margin:.25rem 0 0;color:#777;font-size:.9rem">
            Six parallel SPARQL queries surface capability gaps, tech debt, orphaned apps,
            integration hotspots, duplicate capabilities, and data risks — synthesised by GPT-4o.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not connected:
        st.info("Connect to Stardog in the sidebar to run the SA health analysis.")
        return

    # ── Controls ──────────────────────────────────────────────────────────────
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 1, 1])
    with col_ctrl1:
        domain_filter = st.text_input(
            "Domain filter (optional)",
            value="",
            placeholder="e.g. finance, HR — leave blank for all domains",
            key="sa_health_domain",
        )
    with col_ctrl2:
        st.markdown("<br>", unsafe_allow_html=True)
        run_btn = st.button("⚡ Run SA Analysis", key="sa_health_run", type="primary")
    with col_ctrl3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Clear", key="sa_health_clear"):
            st.session_state.pop("sa_health_result", None)
            st.rerun()

    if run_btn or "sa_health_result" in st.session_state:
        if run_btn:
            with st.spinner("Running six parallel SPARQL queries + LLM synthesis…"):
                try:
                    from nexus.core.sa_advisor import run_sa_advisor
                    result = run_sa_advisor(
                        focus_domain=domain_filter.strip(),
                        user_role=user_role,
                    )
                    st.session_state["sa_health_result"] = result
                except Exception as exc:
                    st.error(f"SA analysis failed: {exc}")
                    return

        result = st.session_state.get("sa_health_result")
        if result is None:
            return

        if result.error:
            st.warning(f"Analysis completed with warnings: {result.error}")

        _render_metric_strip(result)
        st.markdown("---")
        _render_recommendations(result)
        st.markdown("---")
        _render_capability_coverage(result)
        _render_detail_expanders(result)


def _render_metric_strip(result) -> None:
    """Top five health metrics."""
    hc = _health_colour(result.architecture_health_score)
    hl = _health_label(result.architecture_health_score)

    col0, col1, col2, col3, col4, col5 = st.columns(6)
    with col0:
        st.markdown(
            f"""<div style="background:#fff;border:1px solid #D8D8D8;border-radius:8px;
                            padding:.75rem;text-align:center;border-top:4px solid {hc}">
              <div style="font-size:2rem;font-weight:700;color:{hc}">{result.architecture_health_score}</div>
              <div style="font-size:.7rem;color:#777;text-transform:uppercase">Health Score</div>
              <div style="font-size:.75rem;color:{hc};font-weight:600">{hl}</div>
            </div>""",
            unsafe_allow_html=True,
        )
    _metric_card(col1, len(result.capability_gaps),       "Capability Gaps",   "#ef4444")
    _metric_card(col2, len(result.tech_debt_apps),        "Tech Debt Apps",    "#f97316")
    _metric_card(col3, len(result.orphaned_apps),         "Orphaned Apps",     "#f59e0b")
    _metric_card(col4, len(result.integration_hotspots),  "Hotspots",          "#3b82f6")
    _metric_card(col5, len(result.data_risk_apps),        "Data Risk Apps",    "#8b5cf6")

    if result.executive_summary:
        with st.expander("Executive Summary", expanded=False):
            st.markdown(result.executive_summary)


def _metric_card(col, value: int, label: str, colour: str) -> None:
    with col:
        severity = "High" if value > 5 else ("Medium" if value > 0 else "Low")
        fill = colour if value > 0 else "#10b981"
        st.markdown(
            f"""<div style="background:#fff;border:1px solid #D8D8D8;border-radius:8px;
                            padding:.75rem;text-align:center;border-top:4px solid {fill}">
              <div style="font-size:2rem;font-weight:700;color:{fill}">{value}</div>
              <div style="font-size:.7rem;color:#777;text-transform:uppercase">{label}</div>
            </div>""",
            unsafe_allow_html=True,
        )


def _render_recommendations(result) -> None:
    """Filterable, expandable recommendation cards."""
    if not result.recommendations:
        st.info("No recommendations generated.")
        return

    st.markdown("### Recommendations")

    # Quick wins banner
    quick_wins = [r for r in result.recommendations if r.quick_win]
    if quick_wins:
        st.markdown(
            f"""<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                           padding:.75rem 1rem;margin-bottom:1rem">
              <strong style="color:#065f46">⚡ {len(quick_wins)} Quick Win{"s" if len(quick_wins)>1 else ""}:</strong>
              {" · ".join(qw.title for qw in quick_wins[:5])}
            </div>""",
            unsafe_allow_html=True,
        )

    # Filters
    fcol1, fcol2 = st.columns([2, 2])
    with fcol1:
        cat_filter = st.multiselect(
            "Category",
            options=["Gap", "TechDebt", "Rationalise", "Integration", "Orphan", "DataRisk", "Strategic"],
            default=[],
            key="sa_cat_filter",
        )
    with fcol2:
        pri_filter = st.multiselect(
            "Priority",
            options=["Critical", "High", "Medium", "Low"],
            default=[],
            key="sa_pri_filter",
        )

    recs = result.recommendations
    if cat_filter:
        recs = [r for r in recs if r.category in cat_filter]
    if pri_filter:
        recs = [r for r in recs if r.priority in pri_filter]

    for rec in recs:
        p_colour = _PRIORITY_COLOUR.get(rec.priority, "#888")
        p_icon   = _PRIORITY_ICON.get(rec.priority, "⚪")
        c_icon   = _CATEGORY_ICON.get(rec.category, "📌")
        qw_badge = " ⚡ Quick Win" if rec.quick_win else ""
        with st.expander(
            f"{p_icon} **{rec.title}**{qw_badge} · `{rec.category}` · {rec.priority}",
            expanded=(rec.priority == "Critical"),
        ):
            st.markdown(rec.detail)
            st.markdown(f"**Recommended Action:** {rec.action}")
            ec1, ec2 = st.columns(2)
            with ec1:
                st.markdown(f"**Effort:** {rec.effort}")
            with ec2:
                st.markdown(f"**Impact:** {rec.impact}")
            if rec.affected_entities:
                st.markdown("**Affected:** " + ", ".join(f"`{e}`" for e in rec.affected_entities[:8]))

    st.caption(f"{len(recs)} of {len(result.recommendations)} recommendations shown")


def _render_capability_coverage(result) -> None:
    """Capability coverage table with gap highlighting."""
    if not result.capability_coverage and not result.capability_gaps:
        return

    with st.expander(f"Capability Coverage Map ({len(result.capability_coverage)} capabilities)", expanded=False):
        import pandas as pd
        rows = []
        for cap, apps in result.capability_coverage.items():
            rows.append({
                "Capability":    cap,
                "Supporting Apps": len(apps),
                "Status":        "✅ Covered" if apps else "❌ Gap",
                "Apps":          ", ".join(apps[:5]) or "—",
            })
        for gap in result.capability_gaps:
            cap_label = gap.get("capLabel", gap.get("capability", "Unknown"))
            if cap_label not in {r["Capability"] for r in rows}:
                rows.append({
                    "Capability":    cap_label,
                    "Supporting Apps": 0,
                    "Status":        "❌ Gap",
                    "Apps":          "—",
                })
        if rows:
            df = pd.DataFrame(rows).sort_values("Supporting Apps")
            st.dataframe(df, use_container_width=True, hide_index=True)


def _render_detail_expanders(result) -> None:
    """Detailed lists for tech debt, orphans, hotspots, data risk."""
    tabs = st.tabs(["⚙️ Tech Debt", "👻 Orphaned", "🔗 Hotspots", "🛡 Data Risk"])

    with tabs[0]:
        if result.tech_debt_apps:
            for app in result.tech_debt_apps[:20]:
                label = app.get("appLabel", app.get("app", "Unknown"))
                lc = app.get("lifecycle", "")
                owner = app.get("ownerLabel", "—")
                st.markdown(f"- **{label}** · lifecycle: `{lc}` · owner: {owner}")
        else:
            st.success("No tech debt apps detected.")

    with tabs[1]:
        if result.orphaned_apps:
            for app in result.orphaned_apps[:20]:
                label = app.get("appLabel", app.get("app", "Unknown"))
                st.markdown(f"- **{label}** — no owner or capability mapping")
        else:
            st.success("No orphaned apps detected.")

    with tabs[2]:
        if result.integration_hotspots:
            for h in result.integration_hotspots[:20]:
                label = h.get("appLabel", h.get("app", "Unknown"))
                dep_cnt = h.get("depCount", "?")
                st.markdown(f"- **{label}** — {dep_cnt} dependencies")
        else:
            st.success("No integration hotspots detected.")

    with tabs[3]:
        if result.data_risk_apps:
            for app in result.data_risk_apps[:20]:
                label = app.get("appLabel", app.get("app", "Unknown"))
                classification = app.get("classification", "")
                findings = app.get("openFindings", "?")
                st.markdown(f"- **{label}** · classification: `{classification}` · open findings: {findings}")
        else:
            st.success("No data risk apps detected.")
