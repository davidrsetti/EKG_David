import os
import sys
import time
import logging
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv()

# Adjust path so local app can import nexus package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO)

st.set_page_config(page_title="NEXUS Validation App", layout="wide")

st.title("NEXUS Validation App")
st.caption("Shared pipeline: Guard → Clarifier → NL→SPARQL → Stardog → Answer")

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def make_client(endpoint: str, token: str, openai_key: str, db_name: str):
    """
    Update env vars, reset cached config/client, and return a fresh Stardog client.
    """
    os.environ.update({
        "STARDOG_ENDPOINT": endpoint,
        "STARDOG_TOKEN": token,
        "OPENAI_API_KEY": openai_key,
        "STARDOG_DB": db_name,
    })

    import nexus.core.stardog_client as _sc
    _sc._client = None

    import nexus.config.settings as _cfg
    _cfg.settings = _cfg.Settings()

    from nexus.core.stardog_client import StardogClient
    client = StardogClient()
    _sc._client = client
    return client


def run_pipeline(question: str, user_role: str, user_dept: str, use_virtual_graph: bool):
    """
    Execute full NEXUS KG query pipeline.
    Returns a dict with answer, sparql, rows, etc.
    """
    from nexus.agents.guard import check_intent, build_security_filter
    from nexus.core.clarifier import clarify
    from nexus.core.nl_to_sparql import nl_to_sparql
    from nexus.core.stardog_client import get_stardog
    from nexus.core.answer_engine import synthesise
    from nexus.config.settings import settings

    t0 = time.monotonic()

    # 1. Guard
    guard = check_intent(question, user_role)
    if not guard.allowed:
        return {
            "ok": False,
            "stage": "guard",
            "message": f"Blocked: {guard.reason}",
            "guard": guard,
        }

    # 2. Clarify
    plan = clarify(question, user_role)

    # 3. Security filter
    sec = build_security_filter(user_role, user_dept)

    # 4. NL -> SPARQL
    sparql = nl_to_sparql(
        question=question,
        clarification_context="\n".join(plan.assumptions) if plan.assumptions else "",
        user_role=user_role,
        use_virtual_graph=use_virtual_graph,
        extra_filters=sec.sparql_data_filter,
    )

    # 5. Complexity check
    db = get_stardog()
    complexity = db.estimate_complexity(sparql)
    if complexity > settings.security.max_sparql_complexity:
        return {
            "ok": False,
            "stage": "complexity",
            "message": f"Query complexity {complexity} exceeds limit {settings.security.max_sparql_complexity}.",
            "sparql": sparql,
            "plan": plan,
        }

    # 6. Execute query
    raw = db.query(sparql)
    columns, rows = db.to_rows(raw)

    # 7. Synthesis
    answer = synthesise(question, columns, rows[:sec.max_rows], sparql, len(rows))

    latency_ms = int((time.monotonic() - t0) * 1000)

    return {
        "ok": True,
        "question": question,
        "answer": answer,
        "sparql": sparql,
        "columns": columns,
        "rows": rows[:sec.max_rows],
        "row_count": len(rows),
        "latency_ms": latency_ms,
        "complexity": complexity,
        "guard": guard,
        "plan": plan,
    }


# -------------------------------------------------------------------
# Sidebar
# -------------------------------------------------------------------

with st.sidebar:
    st.header("Connection")

    endpoint = st.text_input(
        "Endpoint",
        value=os.getenv("STARDOG_ENDPOINT", "")
    )
    token = st.text_input(
        "Token",
        type="password",
        value=os.getenv("STARDOG_TOKEN", "")
    )
    db_name = st.text_input(
        "Database",
        value=os.getenv("STARDOG_DB", "nexus")
    )
    openai_key = st.text_input(
        "OpenAI API Key",
        type="password",
        value=os.getenv("OPENAI_API_KEY", "")
    )

    st.header("Options")
    user_role = st.selectbox("Role", ["analyst", "data-steward", "admin", "viewer", "agent"])
    user_dept = st.text_input("Department", value="", placeholder="e.g. Finance")
    use_virtual_graph = st.toggle("Use Denodo Virtual Graph", value=False)
    show_plan = st.toggle("Show Clarification Plan", value=True)
    show_sparql = st.toggle("Show SPARQL", value=True)
    show_table = st.toggle("Show Results Table", value=True)

    connected = False
    if st.button("Connect", use_container_width=True):
        try:
            client = make_client(endpoint, token, openai_key, db_name)
            client.query("ASK { ?s ?p ?o }", inject_prefixes=False)
            st.session_state["connected"] = True
            st.success("Connected")
        except Exception as exc:
            st.session_state["connected"] = False
            st.error(f"Connection failed: {exc}")

connected = st.session_state.get("connected", False)

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

question = st.text_area(
    "Ask a validation question",
    placeholder="Example: Which applications have no technical owner and no department owner?",
    height=100,
)

if st.button("Run Validation", type="primary", use_container_width=True):
    if not connected:
        st.warning("Connect first.")
    elif not question.strip():
        st.warning("Enter a question.")
    else:
        try:
            result = run_pipeline(
                question=question.strip(),
                user_role=user_role,
                user_dept=user_dept,
                use_virtual_graph=use_virtual_graph,
            )

            if not result["ok"]:
                st.error(result["message"])
                if result.get("sparql") and show_sparql:
                    st.code(result["sparql"], language="sparql")
            else:
                st.success(
                    f"Completed in {result['latency_ms']} ms · "
                    f"{result['row_count']} rows · "
                    f"complexity {result['complexity']}"
                )

                if result["guard"].risk_level.value in ("medium", "high"):
                    st.warning(f"Risk: {result['guard'].risk_level.value.upper()} — {result['guard'].reason}")

                st.markdown(result["answer"])

                if show_plan:
                    with st.expander("Clarification Plan"):
                        plan = result["plan"]
                        st.json({
                            "interpreted_intent": plan.interpreted_intent,
                            "domains_involved": plan.domains_involved,
                            "mapped_entities": plan.mapped_entities,
                            "mapped_relationships": plan.mapped_relationships,
                            "assumptions": plan.assumptions,
                            "clarifying_questions": plan.clarifying_questions,
                            "security_notes": plan.security_notes,
                            "ready_to_execute": plan.ready_to_execute,
                            "confidence": plan.confidence,
                        })

                if show_sparql:
                    with st.expander("Generated SPARQL"):
                        st.code(result["sparql"], language="sparql")

                if show_table and result["rows"]:
                    with st.expander(f"Results ({result['row_count']} rows)"):
                        st.dataframe(pd.DataFrame(result["rows"]), use_container_width=True, hide_index=True)

        except Exception as exc:
            st.exception(exc)