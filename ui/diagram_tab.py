"""
ui/diagram_tab.py — Architecture Diagram Tab (QW-2)

Exposes the fully-built Artifact Creator engine (core/artifact_creator.py) in the UI.
Renders 7 diagram types from the live knowledge graph as Graphviz DOT or Mermaid,
with SVG download support.
"""
from __future__ import annotations
import streamlit as st

_DIAGRAM_LABELS = {
    "dependency":      "Application Dependency Map",
    "capability_map":  "Business Capability Map",
    "data_lineage":    "Data Lineage Diagram",
    "agent_ecosystem": "AI Agent Ecosystem",
    "c4_context":      "C4 Context Diagram",
    "org_ownership":   "Ownership & Accountability Map",
    "integration":     "Integration Topology",
}

_ENTITY_REQUIRED = {"c4_context", "data_lineage"}

_MERMAID_INIT = """
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad:true, theme:'neutral'}});</script>
"""


def render_diagram_tab(connected: bool, user_role: str) -> None:
    """Render the Architecture Diagram tab."""
    st.markdown(
        """
        <div style="border-left:4px solid #F36633;padding-left:1rem;margin-bottom:1.5rem">
          <h2 style="margin:0;font-size:1.4rem;color:#1A1A1A">🗺️ Architecture Diagram Studio</h2>
          <p style="margin:.25rem 0 0;color:#777;font-size:.9rem">
            Generate 7 types of architecture diagram directly from the live knowledge graph.
            Export as SVG or draw.io XML.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not connected:
        st.info("Connect to Stardog in the sidebar to generate diagrams.")
        return

    # ── Controls ──────────────────────────────────────────────────────────────
    ctrl1, ctrl2 = st.columns([2, 3])

    with ctrl1:
        diagram_type = st.selectbox(
            "Diagram type",
            options=list(_DIAGRAM_LABELS.keys()),
            format_func=lambda k: f"{'⚠️' if k in _ENTITY_REQUIRED else '📊'} {_DIAGRAM_LABELS[k]}",
            key="diag_type",
        )
        fmt = st.radio(
            "Format",
            options=["dot", "mermaid"],
            format_func=lambda f: "Graphviz (DOT)" if f == "dot" else "Mermaid",
            horizontal=True,
            key="diag_fmt",
        )
        depth = st.slider("Traversal depth", min_value=1, max_value=4, value=2, key="diag_depth")
        max_nodes = st.slider("Max nodes", min_value=10, max_value=150, value=60, key="diag_max_nodes")

    with ctrl2:
        entity = ""
        if diagram_type in _ENTITY_REQUIRED:
            entity = st.text_input(
                "Entity name (required)",
                placeholder="e.g. SAP ERP, Customer Data, payments-api",
                key="diag_entity",
            )
        else:
            entity = st.text_input(
                "Entity filter (optional — leave blank for full graph)",
                placeholder="e.g. SAP ERP",
                key="diag_entity_opt",
            )
        domain_filter = st.text_input(
            "Domain filter (optional)",
            placeholder="e.g. finance, HR",
            key="diag_domain",
        )
        st.markdown("<br>", unsafe_allow_html=True)
        generate_btn = st.button(
            "🖼️ Generate Diagram",
            key="diag_generate",
            type="primary",
            disabled=(diagram_type in _ENTITY_REQUIRED and not entity),
        )

    if diagram_type in _ENTITY_REQUIRED and not entity and not generate_btn:
        st.info(f"This diagram type requires an entity name. Enter one above.")

    # ── Generate ──────────────────────────────────────────────────────────────
    if generate_btn or "diag_result" in st.session_state:
        if generate_btn:
            if diagram_type in _ENTITY_REQUIRED and not entity:
                st.warning("Please enter an entity name.")
                return
            with st.spinner(f"Generating {_DIAGRAM_LABELS[diagram_type]}…"):
                try:
                    from nexus.core.artifact_creator import generate_diagram
                    result = generate_diagram(
                        diagram_type=diagram_type,
                        entity=entity,
                        depth=depth,
                        fmt=fmt,
                        domain_filter=domain_filter,
                        max_nodes=max_nodes,
                    )
                    st.session_state["diag_result"] = result
                    st.session_state["diag_type_label"] = _DIAGRAM_LABELS[diagram_type]
                except Exception as exc:
                    st.error(f"Diagram generation failed: {exc}")
                    return

        result = st.session_state.get("diag_result")
        if result is None:
            return

        # ── Stats strip ───────────────────────────────────────────────────────
        m1, m2, m3 = st.columns(3)
        m1.metric("Nodes", result.node_count)
        m2.metric("Edges", result.edge_count)
        m3.metric("Format", result.fmt.upper())

        if result.error:
            st.warning(f"Partial result: {result.error}")

        # ── Render ────────────────────────────────────────────────────────────
        tab_diagram, tab_export = st.tabs(["🖼️ Diagram", "📥 Export"])

        with tab_diagram:
            if not result.content:
                st.info("No diagram content generated — the graph may have no data for this query.")
            elif result.fmt == "dot":
                try:
                    st.graphviz_chart(result.content, use_container_width=True)
                except Exception:
                    st.code(result.content, language="dot")
            else:
                # Mermaid via HTML component
                mermaid_html = f"""
                {_MERMAID_INIT}
                <div class="mermaid" style="background:white;padding:1rem;border-radius:8px">
                {result.content}
                </div>
                """
                st.components.v1.html(mermaid_html, height=600, scrolling=True)

        with tab_export:
            if result.content:
                dl1, dl2, dl3 = st.columns(3)
                with dl1:
                    st.download_button(
                        "⬇️ Download DOT/Mermaid source",
                        data=result.content,
                        file_name=f"nexus_{result.diagram_type}.{'dot' if result.fmt == 'dot' else 'md'}",
                        mime="text/plain",
                    )
                with dl2:
                    drawio = _to_drawio_xml(result)
                    if drawio:
                        st.download_button(
                            "⬇️ Download draw.io XML",
                            data=drawio,
                            file_name=f"nexus_{result.diagram_type}.drawio",
                            mime="application/xml",
                        )
                with dl3:
                    st.download_button(
                        "⬇️ Download raw content",
                        data=result.content,
                        file_name=f"nexus_{result.diagram_type}.txt",
                        mime="text/plain",
                    )

                with st.expander("Source code", expanded=False):
                    lang = "dot" if result.fmt == "dot" else "markdown"
                    st.code(result.content, language=lang)


def _to_drawio_xml(result) -> str | None:
    """Build minimal draw.io XML wrapping the diagram content as a text node."""
    if not result.content:
        return None
    import html as _html
    escaped = _html.escape(result.content)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="NEXUS">
  <diagram name="{result.title or result.diagram_type}">
    <mxGraphModel><root>
      <mxCell id="0"/>
      <mxCell id="1" parent="0"/>
      <mxCell id="2" value="{escaped}" style="text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;" vertex="1" parent="1">
        <mxGeometry x="10" y="10" width="800" height="600" as="geometry"/>
      </mxCell>
    </root></mxGraphModel>
  </diagram>
</mxfile>"""
