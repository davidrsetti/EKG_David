
"""
nexus.ui.guided_sa_tab — Streamlit UI component for the guided SA Advisor.

This is designed to be imported into the existing Streamlit app:
    from nexus.ui.guided_sa_tab import render_guided_sa_tab
    render_guided_sa_tab(st, user_role=user_role)

The module intentionally stays focused on the interview + recommendation flow.
Diagram generation can be chained by passing result.advisor_output.archimate_prompt
into the existing ArchiMate generator in app.py.
"""
from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from nexus.core.sa_advisor_v2 import (
    AVAILABILITY_TARGETS,
    CHANGE_TYPES,
    CLASSIFICATIONS,
    COST_SENSITIVITIES,
    LATENCY_TARGETS,
    OPERATING_MODELS,
    SCALE_PROFILES,
    SECURITY_LEVELS,
    BusinessContext,
    FunctionalRequirements,
    GuidedSAState,
    NonFunctionalRequirements,
    SourceContext,
    list_business_domains,
    list_solution_categories,
    run_guided_sa,
    search_agents,
    search_applications,
    search_capabilities,
    search_data_products,
    search_integrations,
    search_platforms,
)


def _ensure_state(st):
    if "guided_sa_state" not in st.session_state:
        st.session_state.guided_sa_state = GuidedSAState()
    if "guided_sa_result" not in st.session_state:
        st.session_state.guided_sa_result = None
    return st.session_state.guided_sa_state


def render_guided_sa_tab(st, user_role: str = "analyst"):
    state = _ensure_state(st)

    st.markdown(
        '<div style="font-size:.72rem;font-weight:700;letter-spacing:.10em;color:#F36633;'
        'text-transform:uppercase;margin-bottom:.35rem">Guided SA Advisor v2</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "A graph-grounded solution architecture interview. "
        "Use it to capture business need, source landscape, FR/NFR narratives, "
        "and enterprise constraints before generating target architecture."
    )

    if not getattr(st.session_state, "connected", True):
        st.info("Connect to NEXUS first to load graph-backed suggestions.")

    c1, c2, c3, c4 = st.columns(4)
    step = c1.radio("Step", ["1. Business", "2. Sources", "3. Requirements", "4. Recommend"], label_visibility="collapsed")

    if step == "1. Business":
        render_business_step(st, state)
    elif step == "2. Sources":
        render_source_step(st, state)
    elif step == "3. Requirements":
        render_requirements_step(st, state)
    else:
        render_recommendation_step(st, state, user_role)


def render_business_step(st, state: GuidedSAState):
    bc = state.business_context
    st.markdown("### 1. Business context")

    # ── Business Domain — graph only, no hardcoded fallback ──────────
    domains = list_business_domains()
    if not domains:
        st.warning(
            "No EA Business Domains found in the graph. "
            "Ensure Stardog is connected and `ea:EABusinessDomain` instances are loaded."
        )
        st.session_state.guided_sa_state.business_context = bc
        return

    # Stable session_state key so selected_domain is available in this same
    # render pass for capability filtering (avoids the one-rerun lag).
    _dom_key = "guided_sa_domain_select"
    prior = st.session_state.get(_dom_key, bc.domain)
    domain_idx = domains.index(prior) if prior in domains else 0
    selected_domain = st.selectbox(
        "Business domain", domains, index=domain_idx, key=_dom_key
    )
    bc.domain = selected_domain

    # Reset capability selections when the domain changes
    if st.session_state.get("_guided_sa_last_domain") != selected_domain:
        bc.capability_l1 = ""
        bc.capability_l2 = ""
        bc.capability_l3 = ""
        st.session_state["_guided_sa_last_domain"] = selected_domain

    bc.change_type = st.selectbox(
        "Change type", CHANGE_TYPES,
        index=CHANGE_TYPES.index(bc.change_type) if bc.change_type in CHANGE_TYPES else 0,
    )
    bc.business_goal = st.text_input(
        "Business goal / outcome", value=bc.business_goal,
        placeholder="e.g. Improve employee onboarding experience and cycle time",
    )

    # ── Capabilities — graph only, scoped to selected domain ─────────
    caps_l1 = search_capabilities("L1", domain=selected_domain)[:80]
    if caps_l1:
        bc.capability_l1 = st.selectbox(
            "Capability L1", [""] + caps_l1,
            index=([""] + caps_l1).index(bc.capability_l1) if bc.capability_l1 in caps_l1 else 0,
        )
    else:
        st.caption(f"No L1 capabilities found for '{selected_domain}' in the graph.")

    caps_l2 = search_capabilities("L2", domain=selected_domain)[:120]
    if caps_l2:
        bc.capability_l2 = st.selectbox(
            "Capability L2", [""] + caps_l2,
            index=([""] + caps_l2).index(bc.capability_l2) if bc.capability_l2 in caps_l2 else 0,
        )
    else:
        st.caption(f"No L2 capabilities found for '{selected_domain}' in the graph.")

    caps_l3 = search_capabilities("L3", domain=selected_domain)[:150]
    if caps_l3:
        bc.capability_l3 = st.selectbox(
            "Capability L3", [""] + caps_l3,
            index=([""] + caps_l3).index(bc.capability_l3) if bc.capability_l3 in caps_l3 else 0,
        )
    else:
        st.caption(f"No L3 capabilities found for '{selected_domain}' in the graph.")

    # ── Graph diagnostics — shows what's actually in Stardog for this domain
    with st.expander("🔍 Graph diagnostics (debug)", expanded=False):
        try:
            from nexus.core.sa_advisor_v2 import _resolve_domain_iri, _run_rows, EA_BUSINESS_DOMAIN_IRI, RDFS
            domain_iri = _resolve_domain_iri(selected_domain)
            st.markdown(f"**Domain IRI resolved:** `{domain_iri or 'NOT FOUND'}`")
            if domain_iri:
                # Show all triples where this domain node is subject or object
                probe = f"""
                SELECT ?p ?o WHERE {{
                  {{ <{domain_iri}> ?p ?o }}
                  UNION
                  {{ ?o ?p <{domain_iri}> . BIND(?o AS ?o) }}
                }} LIMIT 40
                """
                rows = _run_rows(probe)
                if rows:
                    import pandas as pd
                    st.markdown("**All triples touching this domain node:**")
                    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
                else:
                    st.warning("Domain node found but has no triples — data may not be loaded.")
            # Also probe raw capability count regardless of domain
            cap_probe = f"""
            SELECT (COUNT(?cap) AS ?n) WHERE {{
              ?cap a <https://ontology.ea.example.org/ea#BusinessCapabilityL1> .
            }}
            """
            cap_rows = _run_rows(cap_probe)
            st.markdown(f"**Total L1 capabilities in graph:** {cap_rows[0].get('n', 0) if cap_rows else 0}")
        except Exception as exc:
            st.error(f"Diagnostic error: {exc}")

    st.session_state.guided_sa_state.business_context = bc

    with st.expander("Current business context", expanded=True):
        st.json(asdict(bc))


def render_source_step(st, state: GuidedSAState):
    sc = state.source_context
    st.markdown("### 2. Source / landscape context")

    app_opts = search_applications()[:200]
    platform_opts = search_platforms()[:150]
    data_opts = search_data_products()[:120]
    agent_opts = search_agents()[:120]
    integration_opts = search_integrations()[:120]
    solution_opts = list_solution_categories()[:120]

    sc.source_apps = st.multiselect("Source applications", app_opts, default=[v for v in sc.source_apps if v in app_opts])
    sc.existing_platforms = st.multiselect("Existing platforms", platform_opts, default=[v for v in sc.existing_platforms if v in platform_opts])
    sc.source_data_products = st.multiselect("Source data products", data_opts, default=[v for v in sc.source_data_products if v in data_opts])
    sc.existing_agents = st.multiselect("Existing agents", agent_opts, default=[v for v in sc.existing_agents if v in agent_opts])
    sc.source_integrations = st.multiselect("In-scope integrations", integration_opts, default=[v for v in sc.source_integrations if v in integration_opts])
    sc.existing_solutions = st.multiselect("Existing / candidate solution categories", solution_opts, default=[v for v in sc.existing_solutions if v in solution_opts])
    sc.narrative = st.text_area(
        "Operational context narrative",
        value=sc.narrative,
        height=140,
        placeholder="Describe source systems, business context, dependencies, existing constraints, and what must be reused or avoided."
    )

    st.session_state.guided_sa_state.source_context = sc
    with st.expander("Current source context", expanded=True):
        st.json(asdict(sc))


def render_requirements_step(st, state: GuidedSAState):
    fr = state.functional_requirements
    nfr = state.non_functional_requirements
    st.markdown("### 3. Functional and non-functional requirements")

    left, right = st.columns(2)

    with left:
        fr.narrative = st.text_area(
            "Functional requirements narrative",
            value=fr.narrative,
            height=220,
            placeholder="Describe user journeys, process steps, inputs/outputs, approvals, exceptions, integrations, and end-to-end flow."
        )
        actors_text = st.text_input("Actors (comma-separated)", value=", ".join(fr.actors))
        process_text = st.text_input("Business processes (comma-separated)", value=", ".join(fr.business_processes))
        app_caps_text = st.text_input("Application capabilities (comma-separated)", value=", ".join(fr.app_capabilities))
        outputs_text = st.text_input("Outputs (comma-separated)", value=", ".join(fr.outputs))
        integrations_text = st.text_input("Integrations needed (comma-separated)", value=", ".join(fr.integrations_needed))
        fr.actors = [x.strip() for x in actors_text.split(",") if x.strip()]
        fr.business_processes = [x.strip() for x in process_text.split(",") if x.strip()]
        fr.app_capabilities = [x.strip() for x in app_caps_text.split(",") if x.strip()]
        fr.outputs = [x.strip() for x in outputs_text.split(",") if x.strip()]
        fr.integrations_needed = [x.strip() for x in integrations_text.split(",") if x.strip()]

    with right:
        nfr.narrative = st.text_area(
            "Non-functional requirements narrative",
            value=nfr.narrative,
            height=220,
            placeholder="Describe security, resilience, latency, availability, compliance, data classification, operations, support, lifecycle, and cost constraints."
        )
        nfr.security_level = st.selectbox("Security level", SECURITY_LEVELS, index=SECURITY_LEVELS.index(nfr.security_level) if nfr.security_level in SECURITY_LEVELS else 1)
        nfr.data_classification = st.selectbox("Data classification", CLASSIFICATIONS, index=CLASSIFICATIONS.index(nfr.data_classification) if nfr.data_classification in CLASSIFICATIONS else 1)
        nfr.availability_target = st.selectbox("Availability target", [""] + AVAILABILITY_TARGETS, index=([""] + AVAILABILITY_TARGETS).index(nfr.availability_target) if nfr.availability_target in AVAILABILITY_TARGETS else 0)
        nfr.latency_target = st.selectbox("Latency target", [""] + LATENCY_TARGETS, index=([""] + LATENCY_TARGETS).index(nfr.latency_target) if nfr.latency_target in LATENCY_TARGETS else 0)
        nfr.scale_profile = st.selectbox("Scale profile", [""] + SCALE_PROFILES, index=([""] + SCALE_PROFILES).index(nfr.scale_profile) if nfr.scale_profile in SCALE_PROFILES else 0)
        nfr.cost_sensitivity = st.selectbox("Cost sensitivity", [""] + COST_SENSITIVITIES, index=([""] + COST_SENSITIVITIES).index(nfr.cost_sensitivity) if nfr.cost_sensitivity in COST_SENSITIVITIES else 0)
        nfr.operating_model = st.selectbox("Operating model", [""] + OPERATING_MODELS, index=([""] + OPERATING_MODELS).index(nfr.operating_model) if nfr.operating_model in OPERATING_MODELS else 0)
        compliance_text = st.text_input("Compliance tags (comma-separated)", value=", ".join(nfr.compliance_tags))
        nfr.compliance_tags = [x.strip() for x in compliance_text.split(",") if x.strip()]
        nfr.lifecycle_constraints = st.text_input("Lifecycle constraints", value=nfr.lifecycle_constraints)

    st.session_state.guided_sa_state.functional_requirements = fr
    st.session_state.guided_sa_state.non_functional_requirements = nfr

    with st.expander("Current requirements state", expanded=False):
        st.json({
            "functional": asdict(fr),
            "non_functional": asdict(nfr),
        })


def render_recommendation_step(st, state: GuidedSAState, user_role: str):
    st.markdown("### 4. Graph enrichment and recommendation")
    st.markdown("Run the graph-backed enrichment and generate a recommendation package.")
    go = st.button("Run guided SA advisor", type="primary", width='stretch')

    if go:
        with st.spinner("Pulling graph context and generating recommendations..."):
            st.session_state.guided_sa_result = run_guided_sa(state)

    result = st.session_state.guided_sa_result
    if not result:
        st.info("Complete steps 1-3, then run the advisor.")
        return

    if result.error:
        st.error(result.error)
        return

    out = result.advisor_output
    rec = result.graph_recommendations

    top1, top2, top3 = st.columns(3)
    top1.metric("Supporting apps", len(rec.existing_supporting_apps))
    top2.metric("Candidate platforms", len(rec.candidate_platforms))
    top3.metric("Risks detected", len(out.risks))

    st.markdown("#### Recommendation narrative")
    st.markdown(out.recommendation_narrative)

    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.markdown("#### Problem statement")
        st.write(out.problem_statement)
        st.markdown("#### Capability context")
        st.write(out.capability_context)
        st.markdown("#### Existing landscape")
        st.write(out.existing_landscape)
        st.markdown("#### Rationale")
        st.write(out.rationale)
    with c2:
        st.markdown("#### Risks")
        if out.risks:
            for risk in out.risks:
                st.markdown(f"- {risk}")
        else:
            st.write("No major risks detected.")
        st.markdown("#### Roadmap")
        for step in out.roadmap:
            st.markdown(f"- {step}")

    st.markdown("#### Option analysis")
    if out.options:
        for i, option in enumerate(out.options, start=1):
            with st.expander(f"Option {i} — {option.get('name','Option')}"):
                st.write(option.get("summary", ""))
                st.markdown(f"**Fit:** {option.get('fit', '')}")
                st.markdown(f"**Complexity:** {option.get('estimated_complexity', '')}")
                st.markdown("**Recommended platforms:** " + ", ".join(option.get("recommended_platforms", [])))
                st.markdown("**Recommended patterns:** " + ", ".join(option.get("recommended_patterns", [])))
                st.markdown("**Recommended technologies:** " + ", ".join(option.get("recommended_technologies", [])))
                risks = option.get("risks", [])
                if risks:
                    st.markdown("**Option risks:**")
                    for risk in risks:
                        st.markdown(f"- {risk}")
    else:
        st.caption("No options returned by the model; use the narrative and graph tables below.")

    st.markdown("#### Graph signals")
    tabs = st.tabs(["Supporting apps", "Platforms / technologies", "Gaps / tech debt", "Hotspots / data risk", "Prompt / ADR"])
    with tabs[0]:
        if rec.existing_supporting_apps:
            st.dataframe(pd.DataFrame(rec.existing_supporting_apps), width='stretch', hide_index=True)
        else:
            st.caption("No supporting applications found for the selected capability.")
    with tabs[1]:
        st.write("**Candidate platforms:** " + ", ".join(rec.candidate_platforms[:12]) if rec.candidate_platforms else "No platforms found")
        st.write("**Candidate patterns:** " + ", ".join(rec.candidate_patterns[:12]) if rec.candidate_patterns else "No patterns found")
        st.write("**Candidate archetypes:** " + ", ".join(rec.candidate_archetypes[:12]) if rec.candidate_archetypes else "No archetypes found")
        st.write("**Candidate technologies:** " + ", ".join(rec.candidate_technologies[:12]) if rec.candidate_technologies else "No technologies found")
    with tabs[2]:
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Capability gaps**")
            st.dataframe(pd.DataFrame(rec.capability_gaps), width='stretch', hide_index=True) if rec.capability_gaps else st.caption("No gaps found")
        with g2:
            st.markdown("**Tech debt warnings**")
            st.dataframe(pd.DataFrame(rec.tech_debt_warnings), width='stretch', hide_index=True) if rec.tech_debt_warnings else st.caption("No tech debt warnings found")
    with tabs[3]:
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Integration hotspots**")
            st.dataframe(pd.DataFrame(rec.integration_hotspots), width='stretch', hide_index=True) if rec.integration_hotspots else st.caption("No hotspots found")
        with g2:
            st.markdown("**Data risks**")
            st.dataframe(pd.DataFrame(rec.data_risks), width='stretch', hide_index=True) if rec.data_risks else st.caption("No data risks found")
    with tabs[4]:
        st.markdown("**ArchiMate prompt**")
        st.code(out.archimate_prompt, language="text")
        st.markdown("**Architecture Decision Record starter**")
        st.code(out.architecture_decision_record, language="text")
