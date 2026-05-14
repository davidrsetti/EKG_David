"""
ui/app.py - NEXUS Enterprise Conversational AI
Full pipeline: guard -> clarify -> confirm -> query -> answer + reasoning
+ SA Advisor tab with ArchiMate diagram generation
"""
import os, time, json, logging, sys
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
logging.basicConfig(level=logging.WARNING)

st.set_page_config(page_title="NEXUS", page_icon="🔮", layout="wide", initial_sidebar_state="expanded")

# ── GSK Color Palette — Light / White / Gray ──────────────────────────
# Primary:    GSK Orange  #F36633
# Background: White       #FFFFFF / #F7F7F7
# Cards:      Light gray  #F2F2F2 / #EBEBEB
# Borders:    Mid gray    #D8D8D8
# Text:       Dark gray   #1A1A1A / #444444 / #777777
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

/* ── Force light color scheme — Mac fix ── */
html,body{color-scheme:light!important;background:#F7F7F7!important;color:#1A1A1A!important;}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
code,.stCode,pre{font-family:'DM Mono',monospace;}

/* ── App background & base text ── */
.stApp{background:#F7F7F7!important;color:#1A1A1A!important;}
[data-testid="stAppViewContainer"]{background:#F7F7F7!important;color:#1A1A1A!important;}
[data-testid="stMain"]{background:#F7F7F7!important;}
.block-container{background:#F7F7F7!important;color:#1A1A1A!important;}
section[data-testid="stSidebar"]{background:#FFFFFF!important;border-right:1px solid #D8D8D8!important;color:#1A1A1A!important;}
section[data-testid="stSidebar"] *{color:#1A1A1A!important;}
section[data-testid="stSidebar"] .stCaption,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#888888!important;}

/* ── All markdown / text elements ── */
.stMarkdown{color:#1A1A1A!important;}
[data-testid="stMarkdownContainer"]{color:#1A1A1A!important;}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4,
[data-testid="stMarkdownContainer"] strong,
[data-testid="stMarkdownContainer"] em{color:#1A1A1A!important;}
[data-testid="stText"]{color:#1A1A1A!important;}
p{color:#1A1A1A;}

/* ── Header ── */
.nexus-header{
  background:linear-gradient(135deg,#FFFFFF 0%,#F2F2F2 60%,#FFFFFF 100%);
  border:1px solid #D8D8D8;
  border-left:4px solid #F36633;
  border-radius:10px;
  padding:1.4rem 2rem;
  margin-bottom:1.2rem;
  position:relative;
  overflow:hidden;
}
.nexus-header::before{
  content:"";position:absolute;inset:0;
  background:radial-gradient(ellipse at 80% 50%,rgba(243,102,51,.05) 0%,transparent 65%);
  pointer-events:none;
}
.nexus-title{font-size:1.7rem;font-weight:700;color:#1A1A1A!important;margin:0;line-height:1.2;letter-spacing:-0.02em;}
.nexus-title span{color:#F36633!important;}
.nexus-sub{color:#555555!important;font-size:.82rem;margin:.3rem 0 0;font-weight:400;}

/* ── Plan card ── */
.plan-card{background:#FFFFFF;border:1px solid #D8D8D8;border-top:3px solid #F36633;border-radius:8px;padding:1rem 1.2rem;margin:.6rem 0;}
.plan-label{font-size:.72rem;font-weight:600;letter-spacing:.08em;color:#F36633!important;text-transform:uppercase;margin-bottom:.3rem;}
.plan-value{font-size:.85rem;color:#333333!important;}
.plan-tag{display:inline-block;background:#F2F2F2;border:1px solid #D8D8D8;border-radius:4px;padding:.15rem .5rem;font-size:.75rem;color:#444444!important;margin:.15rem .15rem 0 0;font-family:'DM Mono',monospace;}
.plan-warn{background:#FFF5F2;border:1px solid #F9B99E;border-radius:6px;padding:.6rem .8rem;margin-top:.5rem;font-size:.8rem;color:#C4501F!important;}

/* ── Risk badges ── */
.risk-low{background:#F0FDF4;color:#166534!important;border:1px solid #BBF7D0;border-radius:4px;padding:.1rem .5rem;font-size:.72rem;font-weight:600;}
.risk-medium{background:#FFFBEB;color:#92400E!important;border:1px solid #FDE68A;border-radius:4px;padding:.1rem .5rem;font-size:.72rem;font-weight:600;}
.risk-high{background:#FFF1F0;color:#991B1B!important;border:1px solid #FECACA;border-radius:4px;padding:.1rem .5rem;font-size:.72rem;font-weight:600;}
.risk-blocked{background:#FAF5FF;color:#6B21A8!important;border:1px solid #E9D5FF;border-radius:4px;padding:.1rem .5rem;font-size:.72rem;font-weight:600;}

/* ── Confidence bar ── */
.confidence-bar{height:4px;border-radius:2px;background:linear-gradient(90deg,#F36633,#FF8A5C);margin-top:4px;}

/* ── Expander ── */
details summary{color:#555555!important;font-size:.8rem!important;}
details[open] summary{color:#F36633!important;}
[data-testid="stExpander"]{background:#FFFFFF!important;border:1px solid #D8D8D8!important;}
[data-testid="stExpanderDetails"]{background:#FFFFFF!important;color:#1A1A1A!important;}
[data-testid="stExpanderDetails"] *{color:#1A1A1A;}

/* ── Chat input ── */
.stChatInput>div{background:#FFFFFF!important;border-color:#D8D8D8!important;}
.stChatInput textarea{color:#1A1A1A!important;background:#FFFFFF!important;}
.stChatInput textarea::placeholder{color:#999999!important;}
[data-testid="stChatMessage"]{background:#FFFFFF!important;border:1px solid #EBEBEB!important;border-radius:8px!important;}
[data-testid="stChatMessageContent"]{color:#1A1A1A!important;}
[data-testid="stChatMessageContent"] p{color:#1A1A1A!important;}
[data-testid="stChatMessageContent"] *{color:#1A1A1A;}

/* ── Alert / info / warning / error boxes ── */
[data-testid="stAlert"]{color:#1A1A1A!important;}
[data-testid="stAlert"] p{color:#1A1A1A!important;}
.stSuccess{background:#F0FDF4!important;}
.stWarning{background:#FFFBEB!important;}
.stError{background:#FFF1F0!important;}
.stInfo{background:#F0F7FF!important;}

/* ── Spinner ── */
[data-testid="stSpinner"] p{color:#555555!important;}
.stSpinner>div>div{border-top-color:#F36633!important;}

/* ── Buttons ── */
.stButton>button{background:#FFFFFF!important;border:1px solid #D8D8D8!important;color:#333333!important;border-radius:6px!important;font-size:.82rem!important;transition:all .15s!important;}
.stButton>button:hover{background:#F36633!important;border-color:#F36633!important;color:#FFFFFF!important;}

/* ── st.tabs override ── */
.stTabs [data-baseweb="tab-list"]{background:#FFFFFF!important;border-bottom:2px solid #D8D8D8!important;gap:0!important;}
.stTabs [data-baseweb="tab"]{background:#FFFFFF!important;color:#555555!important;border:none!important;border-bottom:2px solid transparent!important;border-radius:0!important;padding:.65rem 1.4rem!important;font-size:.82rem!important;font-weight:600!important;letter-spacing:.04em!important;text-transform:uppercase!important;transition:all .15s!important;margin-bottom:-2px!important;}
.stTabs [data-baseweb="tab"]:hover{color:#1A1A1A!important;background:#F2F2F2!important;}
.stTabs [aria-selected="true"]{color:#F36633!important;border-bottom:2px solid #F36633!important;background:#FFFFFF!important;}
.stTabs [data-baseweb="tab-highlight"]{background:transparent!important;}
.stTabs [data-baseweb="tab-border"]{background:#D8D8D8!important;}
[data-testid="stTabsContent"]{background:#F7F7F7!important;color:#1A1A1A!important;}

/* ── Metrics ── */
[data-testid="stMetricValue"]{color:#F36633!important;font-weight:700!important;}
[data-testid="stMetricLabel"]{color:#555555!important;}
[data-testid="stMetricDelta"]{color:#555555!important;}

/* ── Toggle / labels ── */
.stToggle>label{color:#444444!important;font-size:.82rem!important;}
.stToggle [data-testid="stWidgetLabel"]{color:#444444!important;}
.stSelectbox label,.stTextInput label,.stTextArea label{color:#444444!important;font-size:.8rem!important;}
[data-testid="stWidgetLabel"]{color:#444444!important;}
[data-testid="stWidgetLabel"] p{color:#444444!important;}
.stSelectbox>div>div{background:#FFFFFF!important;border-color:#D8D8D8!important;color:#1A1A1A!important;}
.stTextInput>div>div>input{background:#FFFFFF!important;border-color:#D8D8D8!important;color:#1A1A1A!important;}
.stTextArea>div>div>textarea{background:#FFFFFF!important;border-color:#D8D8D8!important;color:#1A1A1A!important;}
[data-baseweb="select"] [data-testid="stMarkdownContainer"] p{color:#1A1A1A!important;}
[data-baseweb="popover"] li{color:#1A1A1A!important;background:#FFFFFF!important;}
[data-baseweb="popover"] li:hover{background:#F2F2F2!important;}

/* ── Forms ── */
[data-testid="stForm"]{background:#FFFFFF!important;border:1px solid #D8D8D8!important;border-radius:8px!important;padding:1rem!important;}
[data-testid="stForm"] *{color:#1A1A1A;}
[data-testid="stFormSubmitButton"]>button{background:#F36633!important;border-color:#F36633!important;color:#FFFFFF!important;}
[data-testid="stFormSubmitButton"]>button:hover{background:#D4541F!important;border-color:#D4541F!important;}

/* ── Misc ── */
hr{border-color:#D8D8D8!important;}
[data-testid="stDataFrame"]{border:1px solid #D8D8D8!important;border-radius:6px!important;background:#FFFFFF!important;}
.stCode>div{background:#F2F2F2!important;border:1px solid #D8D8D8!important;color:#1A1A1A!important;}
.stCaption,[data-testid="stCaptionContainer"]{color:#888888!important;}
[data-testid="stCaptionContainer"] p{color:#888888!important;}
[data-testid="stDivider"]{border-color:#D8D8D8!important;}

/* ── Scrollbar ── */
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-track{background:#F7F7F7;}
::-webkit-scrollbar-thumb{background:#CCCCCC;border-radius:2px;}
::-webkit-scrollbar-thumb:hover{background:#F36633;}

/* ── SA Advisor ── */
.sa-input-box{background:#FFFFFF!important;border:1px solid #D8D8D8!important;border-radius:10px!important;padding:1rem 1.2rem!important;margin-bottom:1rem!important;}
.sa-section-label{font-size:.72rem!important;font-weight:700!important;letter-spacing:.1em!important;color:#F36633!important;text-transform:uppercase!important;margin-bottom:.5rem!important;}
.sa-detail-card{background:#FFFFFF!important;border:1px solid #D8D8D8!important;border-left:3px solid #F36633!important;border-radius:8px!important;padding:.8rem 1rem!important;margin-bottom:.6rem!important;}
.sa-layer-band-Motivation{border-left:4px solid #7C3AED!important;}
.sa-layer-band-Business{border-left:4px solid #D97706!important;}
.sa-layer-band-Application{border-left:4px solid #1D4ED8!important;}
.sa-layer-band-Technology{border-left:4px solid #059669!important;}
.sa-advisory-section{background:#FFFFFF!important;border:1px solid #D8D8D8!important;border-radius:8px!important;padding:1rem 1.2rem!important;margin-bottom:.8rem!important;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────
for k, v in {
    "messages": [], "connected": False, "session_id": "",
    "pending_plan": None, "pending_question": "", "pending_clarification": "",
    "turn_count": 0,
    "sa_result": None, "sa_loading": False, "sa_prompt": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


def make_client(endpoint, token, oai_key, db):
    """Set credentials, reset the StardogClient singleton, return a fresh client."""
    os.environ.update({
        "STARDOG_ENDPOINT": endpoint,
        "STARDOG_TOKEN":    token,
        "OPENAI_API_KEY":   oai_key,
        "STARDOG_DB":       db,
    })
    # Reset the module-level singleton so it picks up the new env vars
    import nexus.core.stardog_client as _sc
    _sc._client = None
    # Reset the frozen Settings singleton so it re-reads env vars
    import nexus.config.settings as _cfg
    _cfg.settings = _cfg.Settings()
    # Invalidate schema cache so the new endpoint's ontology is fetched fresh
    from nexus.core.sa_advisor_v2 import invalidate_schema_cache
    invalidate_schema_cache()
    from nexus.core.stardog_client import StardogClient
    client = StardogClient()
    _sc._client = client
    return client


# ── Sidebar ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div style="text-align:center;padding:.5rem 0 1rem">'
        '<div style="width:40px;height:40px;background:#F36633;border-radius:8px;'
        'display:flex;align-items:center;justify-content:center;margin:0 auto .6rem;font-size:1.2rem">🔮</div>'
        '<div style="color:#1A1A1A;font-weight:700;font-size:1rem;margin-top:.2rem">NEXUS</div>'
        '<div style="color:#777777;font-size:.7rem">Knowledge Graph Platform</div></div>',
        unsafe_allow_html=True
    )

    with st.expander("Stardog Connection", expanded=not st.session_state.connected):
        endpoint  = st.text_input("Endpoint", value=os.getenv("STARDOG_ENDPOINT", "http://localhost:5820/nexus/query"))
        token     = st.text_input("Token", type="password", value=os.getenv("STARDOG_TOKEN", ""))
        db_name   = st.text_input("Database", value=os.getenv("STARDOG_DB", "nexus"))

    with st.expander("OpenAI", expanded=not st.session_state.connected):
        openai_key   = st.text_input("API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
        sparql_model = st.selectbox("SPARQL Model", ["o3-mini", "gpt-4o", "gpt-4o-mini"])
        answer_model = st.selectbox("Answer Model", ["gpt-4o", "gpt-4o-mini", "o3-mini"])

    if st.button("Connect", use_container_width=True):
        if endpoint and openai_key:
            try:
                # Set model preferences before resetting the settings singleton
                os.environ.update({"SPARQL_MODEL": sparql_model, "ANSWER_MODEL": answer_model})
                client = make_client(endpoint, token, openai_key, db_name)
                # Ping Stardog to validate credentials before proceeding
                client.query("ASK { ?s ?p ?o } LIMIT 1", inject_prefixes=False)
                from nexus.agents.session import create_session
                st.session_state.session_id = create_session("ui-user", "analyst")
                st.session_state.connected = True
                st.success("Connected")
            except Exception as e:
                st.error(f"Connection failed: {e}")
                st.session_state.connected = False
        else:
            st.warning("Endpoint and API key required.")

    st.divider()
    st.markdown('<div style="color:#777777;font-size:.7rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;margin-bottom:.4rem">Query Options</div>', unsafe_allow_html=True)
    use_virtual  = st.toggle("Denodo Virtual Graph", value=False)
    show_sparql  = st.toggle("Show SPARQL", value=True)
    show_table   = st.toggle("Show Results Table", value=True)
    show_plan    = st.toggle("Show Query Plan", value=True)
    auto_confirm = st.toggle("Auto-confirm (skip HitL)", value=False)
    st.divider()
    st.markdown('<div style="color:#777777;font-size:.7rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;margin-bottom:.4rem">Identity</div>', unsafe_allow_html=True)
    user_role = st.selectbox("Role", ["analyst", "data-steward", "admin", "viewer", "agent"])
    st.session_state["user_role"] = user_role
    user_dept = st.text_input("Department", value="", placeholder="e.g. Finance")
    st.divider()

    if st.button("Refresh Graph Health", use_container_width=True):
        if st.session_state.connected:
            from nexus.core.stardog_client import get_stardog
            db = get_stardog()
            checks = {
                "People":       "SELECT (COUNT(*) AS ?c) WHERE { ?s a hr:Person }",
                "Apps":         "SELECT (COUNT(*) AS ?c) WHERE { ?s a app:Application }",
                "Data Assets":  "SELECT (COUNT(*) AS ?c) WHERE { ?s a data:DataAsset }",
                "AI Agents":    "SELECT (COUNT(*) AS ?c) WHERE { ?s a agent:AIAgent }",
                "Open Findings":"SELECT (COUNT(*) AS ?c) WHERE { ?s a agent:AgentFinding ; agent:status 'Open' }",
            }
            for lbl, q in checks.items():
                try:
                    _, rows = db.to_rows(db.query(q))
                    st.metric(lbl, rows[0].get("c", "?") if rows else "?")
                except:
                    st.metric(lbl, "err")

    if st.button("Clear Chat", use_container_width=True):
        st.session_state.update({"messages": [], "pending_plan": None, "pending_question": "", "turn_count": 0})
        st.rerun()
    st.caption("NEXUS v1.0 · Stardog + OpenAI · GSK")

# ── Header ────────────────────────────────────────────────────────────
dot       = '<span style="color:#22c55e">●</span>' if st.session_state.connected else '<span style="color:#ef4444">●</span>'
status_txt = "Connected" if st.session_state.connected else "Disconnected"
sid        = st.session_state.session_id[:12] if st.session_state.session_id else "none"

st.markdown(
    '<div class="nexus-header">'
    '<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:.5rem">'
    '<div>'
    '<div class="nexus-title">NEXUS <span>·</span> Enterprise Knowledge Graph</div>'
    '<div class="nexus-sub">Conversational AI · Agent Grounding · Orchestration Intelligence · Semantic Governance · SA Advisor</div>'
    '</div>'
    f'<div style="text-align:right;font-size:.78rem;color:#777777">{dot} {status_txt} &nbsp;·&nbsp; {user_role.title()} &nbsp;·&nbsp; Session {sid}</div>'
    '</div></div>',
    unsafe_allow_html=True
)

# ── Main tabs ─────────────────────────────────────────────────────────
tab_chat, tab_guided_sa, tab_sa, tab_data, tab_portfolio, tab_sa_health, tab_diagram, tab_impact, tab_audit = st.tabs([
    "💬  Knowledge Graph Chat",
    "🧭  Guided SA Advisor",
    "🏛  Freeform SA Diagram",
    "📊  Data Query",
    "📊  Portfolio Intelligence",
    "🏥  SA Health",
    "🗺️  Architecture Diagrams",
    "💥  Change Impact",
    "🔍  Audit",
])


# ═══════════════════════════════════════════════════════════════════════
# TAB 1 — KNOWLEDGE GRAPH CHAT
# ═══════════════════════════════════════════════════════════════════════
with tab_chat:

    EXAMPLES = [
        "Which applications directly support the Order-to-Cash business process?",
        "Which business capabilities have no application support in the current portfolio?",
        "What are all integration points between Finance and HR systems?",
        "Which data assets have no assigned data steward or owner?",
        "Which technology components are running end-of-life or unsupported software?",
        "Which business processes span more than one business domain with no shared data standard?",
    ]

    if not st.session_state.messages and not st.session_state.pending_plan:
        st.markdown(
            '<div style="color:#777777;font-size:.78rem;font-weight:600;letter-spacing:.05em;'
            'text-transform:uppercase;margin-bottom:.6rem">Example Questions</div>',
            unsafe_allow_html=True
        )
        cols = st.columns(3)
        for i, ex in enumerate(EXAMPLES):
            if cols[i % 3].button(ex[:58] + ("..." if len(ex) > 58 else ""), key=f"ex_{i}", use_container_width=True):
                st.session_state["prefill"] = ex
                st.rerun()

    # ── Chat history ───────────────────────────────────────────────
    for msg in st.session_state.messages:
        role   = msg["role"]
        avatar = "🔮" if role == "assistant" else "👤"
        with st.chat_message(role, avatar=avatar):
            st.markdown(msg["content"])
            if show_sparql and msg.get("sparql"):
                with st.expander("Generated SPARQL"):
                    st.code(msg["sparql"], language="sparql")
            if show_table and msg.get("rows"):
                st.dataframe(pd.DataFrame(msg["rows"]), use_container_width=True, hide_index=True)
            if msg.get("latency_ms"):
                st.caption(f"{msg['latency_ms']}ms · {msg.get('row_count', 0)} rows · {msg.get('model', '')}")

    # ── Render plan ────────────────────────────────────────────────
    def render_plan(plan):
        risk       = getattr(plan, "risk_level", "low")
        risk_class = {"low": "risk-low", "medium": "risk-medium", "high": "risk-high", "blocked": "risk-blocked"}.get(risk, "risk-low")
        conf       = int(getattr(plan, "confidence", 1.0) * 100)
        conf_col   = "#22c55e" if conf > 80 else "#fcd34d" if conf > 50 else "#ef4444"

        def tags(items):
            return "".join(f'<span class="plan-tag">{i}</span>' for i in items) or "<span style='color:#555'>none</span>"

        warn_html = ""
        if getattr(plan, "security_notes", []):
            notes     = "".join(f"<div>- {n}</div>" for n in plan.security_notes)
            warn_html = f'<div class="plan-warn">Security notes:<br>{notes}</div>'

        assump_html = ""
        if getattr(plan, "assumptions", []):
            items       = "".join(f"<div style='color:#666666;font-size:.8rem;margin-top:.2rem'>- {a}</div>" for a in plan.assumptions)
            assump_html = f'<div style="margin-top:.6rem"><div class="plan-label">Assumptions</div>{items}</div>'

        html = (
            '<div class="plan-card">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.8rem">'
            f'<span style="color:#F36633;font-weight:600;font-size:.9rem">Query Plan</span>'
            f'<span class="{risk_class}">RISK: {risk.upper()}</span></div>'
            f'<div class="plan-label">Interpreted Intent</div>'
            f'<div class="plan-value">{getattr(plan, "interpreted_intent", "")}</div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin-top:.6rem">'
            f'<div><div class="plan-label">Domains</div>{tags(getattr(plan, "domains_involved", []))}</div>'
            f'<div><div class="plan-label">Confidence</div>'
            f'<div style="color:{conf_col};font-weight:600;font-size:.85rem">{conf}%</div>'
            f'<div class="confidence-bar" style="width:{conf}%;background:{conf_col}88"></div></div></div>'
            f'<div style="margin-top:.6rem"><div class="plan-label">Entities</div>{tags(getattr(plan, "mapped_entities", []))}</div>'
            f'<div style="margin-top:.4rem"><div class="plan-label">Relationships</div>{tags(getattr(plan, "mapped_relationships", []))}</div>'
            f'{assump_html}{warn_html}'
            '</div>'
        )
        st.markdown(html, unsafe_allow_html=True)

    # ── Execute pipeline ───────────────────────────────────────────
    def execute_query(question, clarification_context=""):
        from nexus.agents.guard        import check_intent, build_security_filter
        from nexus.core.nl_to_sparql   import nl_to_sparql
        from nexus.core.stardog_client  import get_stardog
        from nexus.core.answer_engine   import synthesise
        from nexus.audit.logger         import log_query, log_guard_event
        from nexus.audit.pii_scanner    import scan_and_redact
        from nexus.config.settings      import settings as _s

        t0 = time.monotonic()
        with st.chat_message("assistant", avatar="🔮"):
            status = st.empty()

            status.markdown("Responsible AI check...")
            guard = check_intent(question, user_role)
            log_guard_event("ui-user", question, guard.allowed, guard.risk_level.value, guard.flags)
            if not guard.allowed:
                msg = f"Blocked: {guard.reason}"
                if guard.flags: msg += " | Flags: " + ", ".join(guard.flags)
                status.markdown(msg)
                st.session_state.messages.append({"role": "assistant", "content": msg})
                return
            if guard.risk_level.value in ("medium", "high"):
                st.warning(f"Risk {guard.risk_level.value.upper()}: {guard.reason}")

            sec = build_security_filter(user_role, user_dept)

            status.markdown("Generating SPARQL...")
            try:
                sparql = nl_to_sparql(
                    question, clarification_context=clarification_context,
                    user_role=user_role, use_virtual_graph=use_virtual,
                    extra_filters=sec.sparql_data_filter,
                )
            except Exception as exc:
                msg = f"SPARQL generation failed: {exc}"
                status.markdown(msg)
                st.session_state.messages.append({"role": "assistant", "content": msg})
                return

            db         = get_stardog()
            complexity = db.estimate_complexity(sparql)
            if complexity > _s.security.max_sparql_complexity:
                msg = f"Query complexity {complexity} exceeds limit {_s.security.max_sparql_complexity}. Simplify."
                status.markdown(msg)
                st.session_state.messages.append({"role": "assistant", "content": msg})
                return

            status.markdown("Querying knowledge graph...")
            try:
                raw     = db.query(sparql)
                columns, rows = db.to_rows(raw)
            except Exception as exc:
                msg = f"Query failed: {exc}"
                status.markdown(msg)
                st.session_state.messages.append({"role": "assistant", "content": msg})
                return

            total           = len(rows)
            rows            = rows[:sec.max_rows]
            scan            = scan_and_redact(rows, redact=True)
            classifications = list({r.get("classification", "") for r in rows if r.get("classification")})

            status.markdown("Synthesising answer...")
            answer  = synthesise(question, columns, scan.redacted_rows, sparql, total)
            latency = int((time.monotonic() - t0) * 1000)
            log_query("ui-user", user_role, st.session_state.session_id, question, sparql,
                      len(rows), columns, classifications, latency, _s.openai.answer_model,
                      pii_detected=scan.pii_found)

            status.empty()
            if scan.pii_found:
                det = ", ".join(f"{d['field']} ({d['type']})" for d in scan.detections)
                st.info(f"PII detected and redacted: {det}")

            st.markdown(answer)

            if show_sparql:
                with st.expander("Generated SPARQL"):
                    st.code(sparql, language="sparql")
            if show_table and scan.redacted_rows:
                label = f"Results — {total} rows"
                if total > sec.max_rows: label += f" (showing {sec.max_rows})"
                with st.expander(label):
                    st.dataframe(pd.DataFrame(scan.redacted_rows), use_container_width=True, hide_index=True)

            st.caption(
                f"{latency}ms · {total} rows"
                + (" · PII redacted" if scan.pii_found else "")
                + f" · complexity:{complexity} · {_s.openai.answer_model}"
            )

            st.session_state.messages.append({
                "role": "assistant", "content": answer,
                "sparql": sparql, "rows": scan.redacted_rows[:50],
                "row_count": total, "latency_ms": latency, "model": _s.openai.answer_model,
            })
            st.session_state.turn_count += 1

    # ── HitL plan confirmation ─────────────────────────────────────
    def handle_pending():
        plan     = st.session_state.pending_plan
        question = st.session_state.pending_question
        if show_plan:
            render_plan(plan)
        cqs = getattr(plan, "clarifying_questions", [])
        with st.chat_message("assistant", avatar="🔮"):
            if cqs and not getattr(plan, "ready_to_execute", True) and not auto_confirm:
                st.markdown("Please clarify before I run this query:")
                answers = []
                with st.form("clarify_form", clear_on_submit=True):
                    for i, cq in enumerate(cqs[:2]):
                        answers.append(st.text_input(f"Q{i+1}: {cq}", key=f"cq_ans_{i}"))
                    c1, c2 = st.columns(2)
                    submitted = c1.form_submit_button("Submit & Run", use_container_width=True)
                    skipped   = c2.form_submit_button("Skip & Run",   use_container_width=True)
                if submitted or skipped:
                    ctx = ""
                    if submitted and any(a.strip() for a in answers):
                        ctx = "\n\n".join(
                            f"Q: {cqs[i]}\nA: {answers[i]}"
                            for i in range(len(cqs)) if i < len(answers) and answers[i].strip()
                        )
                    st.session_state.pending_plan     = None
                    st.session_state.pending_question = ""
                    execute_query(question, ctx)
            else:
                if not auto_confirm:
                    st.markdown("Query plan confirmed. Ready to execute.")
                    c1, c2 = st.columns(2)
                    if c1.button("Run Query",     use_container_width=True, key="btn_run"):
                        st.session_state.pending_plan = None
                        execute_query(question, st.session_state.pending_clarification)
                    if c2.button("Edit Question", use_container_width=True, key="btn_edit"):
                        st.session_state.pending_plan     = None
                        st.session_state.pending_question = ""
                        st.rerun()
                else:
                    st.session_state.pending_plan = None
                    execute_query(question, st.session_state.pending_clarification)

    if st.session_state.pending_plan:
        handle_pending()

    # ── Chat input ─────────────────────────────────────────────────
    prefill  = st.session_state.pop("prefill", "")
    question = st.chat_input("Ask NEXUS anything about your enterprise...") or prefill

    if question and not st.session_state.pending_plan:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user", avatar="👤"):
            st.markdown(question)

        if not st.session_state.connected:
            with st.chat_message("assistant", avatar="🔮"):
                st.warning("Connect to NEXUS via the sidebar first.")
        else:
            with st.chat_message("assistant", avatar="🔮"):
                with st.spinner("Mapping to ontology..."):
                    try:
                        from nexus.core.clarifier import clarify
                        from nexus.agents.guard   import check_intent
                        guard = check_intent(question, user_role)
                        if not guard.allowed:
                            msg = f"Blocked: {guard.reason}"
                            st.markdown(msg)
                            st.session_state.messages.append({"role": "assistant", "content": msg})
                            st.stop()
                        if auto_confirm:
                            st.session_state.pending_plan = None
                            execute_query(question)
                        else:
                            plan = clarify(question, user_role)
                            plan.risk_level                    = guard.risk_level.value
                            st.session_state.pending_plan      = plan
                            st.session_state.pending_question  = question
                            st.session_state.pending_clarification = ""
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Clarification failed ({exc}). Running directly.")
                        execute_query(question)



# ═══════════════════════════════════════════════════════════════════════
# TAB 2 — GUIDED SA ADVISOR
# ═══════════════════════════════════════════════════════════════════════
with tab_guided_sa:
    try:
        from nexus.ui.guided_sa_tab import render_guided_sa_tab
        render_guided_sa_tab(st, user_role=user_role)
    except Exception as exc:
        st.error(f"Guided SA Advisor failed to load: {exc}")


# ═══════════════════════════════════════════════════════════════════════
# TAB 2 — SA ADVISOR (ArchiMate + Anthropic API)
# ═══════════════════════════════════════════════════════════════════════
with tab_sa:

    st.caption('Use Guided SA Advisor for capability-first architecture interviews. Use this tab for freeform ArchiMate generation.')

    # ── ArchiMate definitions ──────────────────────────────────────
    LAYER_ORDER = ["Motivation", "Business", "Application", "Technology"]

    LAYER_COLORS = {
        "Motivation":  {"band": "#1C1040", "border": "#7C3AED", "accent": "#A78BFA"},
        "Business":    {"band": "#261800", "border": "#B45309", "accent": "#F59E0B"},
        "Application": {"band": "#0C1830", "border": "#1D4ED8", "accent": "#3B82F6"},
        "Technology":  {"band": "#022010", "border": "#047857", "accent": "#10B981"},
    }

    ELEMENT_DEFS = {
        "BusinessActor":        {"layer": "Business",    "label": "Business Actor"},
        "BusinessRole":         {"layer": "Business",    "label": "Business Role"},
        "BusinessProcess":      {"layer": "Business",    "label": "Business Process"},
        "BusinessFunction":     {"layer": "Business",    "label": "Business Function"},
        "BusinessService":      {"layer": "Business",    "label": "Business Service"},
        "BusinessObject":       {"layer": "Business",    "label": "Business Object"},
        "ApplicationComponent": {"layer": "Application", "label": "App Component"},
        "ApplicationService":   {"layer": "Application", "label": "App Service"},
        "ApplicationInterface": {"layer": "Application", "label": "App Interface"},
        "DataObject":           {"layer": "Application", "label": "Data Object"},
        "Node":                 {"layer": "Technology",  "label": "Node"},
        "SystemSoftware":       {"layer": "Technology",  "label": "System Software"},
        "TechnologyService":    {"layer": "Technology",  "label": "Tech Service"},
        "Artifact":             {"layer": "Technology",  "label": "Artifact"},
        "Driver":               {"layer": "Motivation",  "label": "Driver"},
        "Goal":                 {"layer": "Motivation",  "label": "Goal"},
        "Principle":            {"layer": "Motivation",  "label": "Principle"},
        "Requirement":          {"layer": "Motivation",  "label": "Requirement"},
    }

    REL_STYLES = {
        "ServingRelationship":     {"dash": "none",  "color": "#3B82F6"},
        "RealizationRelationship": {"dash": "6,4",   "color": "#A78BFA"},
        "CompositionRelationship": {"dash": "none",  "color": "#F59E0B"},
        "AggregationRelationship": {"dash": "none",  "color": "#10B981"},
        "FlowRelationship":        {"dash": "4,4",   "color": "#F36633"},
        "TriggeringRelationship":  {"dash": "none",  "color": "#FB923C"},
        "AccessRelationship":      {"dash": "3,3",   "color": "#888888"},
        "AssociationRelationship": {"dash": "none",  "color": "#555555"},
        "InfluenceRelationship":   {"dash": "8,4",   "color": "#E879F9"},
    }

    SA_SYSTEM = """You are a senior Enterprise Architect expert in ArchiMate 3.1.

Generate an ArchiMate diagram and professional SA advisory. Return ONLY valid JSON, no markdown fences:
{
  "title": "Concise descriptive title",
  "advisory": "4 paragraphs separated by newlines: 1) Architecture overview 2) Key design decisions and rationale 3) Risks and mitigations 4) Strategic recommendations. Professional EA language. Specific and actionable.",
  "elements": [{"id":"e1","type":"ElementType","label":"Short Label","description":"One sentence.","layer":"LayerName"}],
  "relationships": [{"id":"r1","from":"e1","to":"e2","type":"RelationshipType","label":""}]
}

Valid element types:
- Business layer: BusinessActor, BusinessRole, BusinessProcess, BusinessFunction, BusinessService, BusinessObject
- Application layer: ApplicationComponent, ApplicationService, ApplicationInterface, DataObject
- Technology layer: Node, SystemSoftware, TechnologyService, Artifact
- Motivation layer: Driver, Goal, Principle, Requirement

Valid relationship types: ServingRelationship, RealizationRelationship, CompositionRelationship, FlowRelationship, TriggeringRelationship, AccessRelationship, AssociationRelationship, AggregationRelationship, InfluenceRelationship

Rules: 6-14 elements across 2-4 layers. 4-12 relationships. Labels max 4 words. Always populate the layer field using the layer name. Return ONLY JSON."""

    SA_EXAMPLES = [
        "NEXUS AI agent governance with data stewardship",
        "Enterprise data mesh with federated governance",
        "Cloud-native microservices with API gateway",
        "Zero trust security for hybrid cloud",
        "AI orchestration pipeline with responsible AI controls",
        "GSK clinical data platform with regulatory compliance",
    ]

    # ── SA call to Anthropic API via requests ──────────────────────
    def call_sa_api(prompt: str) -> dict:
        import requests as req
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not anthropic_key:
            # Fallback: try OpenAI key env var name (user might have set it)
            anthropic_key = os.getenv("CLAUDE_API_KEY", "")
        if not anthropic_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file: ANTHROPIC_API_KEY=sk-ant-..."
            )
        # SSL: set SSL_CERT_FILE=/path/to/ca-bundle.pem in .env for Zscaler/proxy.
        # Set SSL_CERT_FILE=false for local dev only.
        _ssl = os.getenv("SSL_CERT_FILE", "").strip()
        _verify: bool | str = False if _ssl.lower() == "false" else (_ssl or True)
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 3000,
                "system": SA_SYSTEM,
                "messages": [{"role": "user", "content": f"Architecture to diagram: {prompt}"}],
            },
            timeout=60,
            verify=_verify,
        )
        if not resp.ok:
            raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        raw  = data.get("content", [{}])[0].get("text", "")
        raw  = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)

    # ── draw.io XML export ─────────────────────────────────────────
    def build_drawio_xml(result: dict, pos: dict, W: int, H: int) -> str:
        xml = '<?xml version="1.0" encoding="UTF-8"?><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        for el_id, el in pos.items():
            lc = LAYER_COLORS.get(el.get("layer", "Application"), LAYER_COLORS["Application"])
            xml += (
                f'<mxCell id="{el_id}" value="{el["label"]}" '
                f'style="rounded=1;fillColor={lc["band"]};strokeColor={lc["border"]};'
                f'fontColor=#FFFFFF;fontSize=11;fontStyle=1;" '
                f'vertex="1" parent="1">'
                f'<mxGeometry x="{el["x"]}" y="{el["y"]}" width="{el["w"]}" height="{el["h"]}" as="geometry"/>'
                f'</mxCell>'
            )
        for rel in result.get("relationships", []):
            rs = REL_STYLES.get(rel["type"], REL_STYLES["AssociationRelationship"])
            xml += (
                f'<mxCell id="{rel["id"]}" value="{rel.get("label","")}" '
                f'style="edgeStyle=orthogonalEdgeStyle;strokeColor={rs["color"]};'
                f'dashed={1 if rs["dash"] != "none" else 0};fontColor={rs["color"]};fontSize=9;" '
                f'edge="1" source="{rel["from"]}" target="{rel["to"]}" parent="1">'
                f'<mxGeometry relative="1" as="geometry"/></mxCell>'
            )
        xml += "</root></mxGraphModel>"
        return xml

    # ── Layout engine ──────────────────────────────────────────────
    def layout_elements(elements: list) -> tuple[dict, dict, int, int]:
        EW, EH, GX, GY, COLS = 160, 64, 24, 16, 4
        BPAD_T, BPAD_B, BGAP, SPAD = 44, 20, 12, 24

        by_layer = {l: [] for l in LAYER_ORDER}
        for el in elements:
            layer = el.get("layer") or ELEMENT_DEFS.get(el["type"], {}).get("layer", "Application")
            el = dict(el, layer=layer)
            by_layer[layer].append(el)

        pos, bands = {}, {}
        y = 12
        for lyr in LAYER_ORDER:
            els = by_layer[lyr]
            if not els:
                continue
            band_y = y
            y += BPAD_T
            rows = max(1, (len(els) + COLS - 1) // COLS)
            for i, el in enumerate(els):
                pos[el["id"]] = {
                    **el,
                    "x": SPAD + (i % COLS) * (EW + GX),
                    "y": y + (i // COLS) * (EH + GY),
                    "w": EW, "h": EH,
                }
            band_h = BPAD_T + rows * EH + (rows - 1) * GY + BPAD_B
            bands[lyr] = {"y": band_y, "h": band_h}
            y += rows * EH + (rows - 1) * GY + BPAD_B + BGAP

        vals = list(pos.values())
        W = (max(v["x"] + v["w"] for v in vals) + SPAD) if vals else 600
        H = y + 12
        return pos, bands, W, H

    # ── SVG diagram renderer ───────────────────────────────────────
    def render_sa_diagram(result: dict) -> str:
        elements = result.get("elements", [])
        rels     = result.get("relationships", [])
        pos, bands, W, H = layout_elements(elements)

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'style="background:#F7F7F7;display:block;font-family:DM Sans,sans-serif;">'
        ]

        # Layer bands
        for lyr, b in bands.items():
            lc = LAYER_COLORS[lyr]
            svg_parts.append(
                f'<rect x="0" y="{b["y"]}" width="{W}" height="{b["h"]}" fill="{lc["band"]}" opacity="0.8"/>'
                f'<rect x="0" y="{b["y"]}" width="3" height="{b["h"]}" fill="{lc["border"]}"/>'
                f'<text x="10" y="{b["y"]+26}" font-family="DM Mono,monospace" font-size="9" '
                f'font-weight="600" fill="{lc["accent"]}" opacity="0.9" letter-spacing="0.1em">'
                f'{lyr.upper()} LAYER</text>'
            )

        # Relationships
        for rel in rels:
            frm = pos.get(rel.get("from"))
            to  = pos.get(rel.get("to"))
            if not frm or not to:
                continue
            rs = REL_STYLES.get(rel["type"], REL_STYLES["AssociationRelationship"])

            fi = LAYER_ORDER.index(frm.get("layer","Application")) if frm.get("layer") in LAYER_ORDER else 2
            ti = LAYER_ORDER.index(to.get("layer","Application"))  if to.get("layer") in LAYER_ORDER else 2

            if fi != ti:
                x1 = frm["x"] + frm["w"] // 2
                y1 = frm["y"] + frm["h"] if fi < ti else frm["y"]
                x2 = to["x"]  + to["w"]  // 2
                y2 = to["y"]  if fi < ti else to["y"] + to["h"]
            elif frm["x"] < to["x"]:
                x1, y1 = frm["x"] + frm["w"], frm["y"] + frm["h"] // 2
                x2, y2 = to["x"],             to["y"]  + to["h"]  // 2
            else:
                x1, y1 = frm["x"],            frm["y"] + frm["h"] // 2
                x2, y2 = to["x"] + to["w"],   to["y"]  + to["h"]  // 2

            cx1, cy1 = x1 + (x2 - x1) * 0.3, y1
            cx2, cy2 = x1 + (x2 - x1) * 0.7, y2
            dash_attr = f'stroke-dasharray="{rs["dash"]}"' if rs["dash"] != "none" else ""
            svg_parts.append(
                f'<path d="M{x1},{y1} C{cx1},{cy1} {cx2},{cy2} {x2},{y2}" '
                f'fill="none" stroke="{rs["color"]}" stroke-width="1.5" {dash_attr} opacity="0.7"/>'
            )
            # Arrowhead
            import math
            angle = math.atan2(y2 - cy2, x2 - cx2)
            L, W2 = 9, 4.5
            p1x = x2 - L * math.cos(angle - 0.5)
            p1y = y2 - L * math.sin(angle - 0.5)
            p2x = x2 - L * math.cos(angle + 0.5)
            p2y = y2 - L * math.sin(angle + 0.5)
            svg_parts.append(
                f'<polygon points="{x2},{y2} {p1x:.1f},{p1y:.1f} {p2x:.1f},{p2y:.1f}" '
                f'fill="{rs["color"]}" opacity="0.85"/>'
            )
            if rel.get("label"):
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 6
                svg_parts.append(
                    f'<text x="{mx:.0f}" y="{my:.0f}" text-anchor="middle" '
                    f'font-family="DM Mono,monospace" font-size="8" fill="{rs["color"]}" opacity="0.85">'
                    f'{rel["label"]}</text>'
                )

        # Elements
        for el_id, el in pos.items():
            lc   = LAYER_COLORS.get(el.get("layer", "Application"), LAYER_COLORS["Application"])
            edef = ELEMENT_DEFS.get(el["type"], {"label": el["type"]})
            cx   = el["x"] + el["w"] // 2
            cy   = el["y"] + el["h"] // 2 + 5
            svg_parts.append(
                f'<rect x="{el["x"]}" y="{el["y"]}" width="{el["w"]}" height="{el["h"]}" '
                f'rx="4" fill="#FFFFFF" stroke="{lc["border"]}" stroke-width="1"/>'
                f'<rect x="{el["x"]}" y="{el["y"]}" width="{el["w"]}" height="2" '
                f'rx="1" fill="{lc["accent"]}" opacity="0.5"/>'
                f'<text x="{el["x"]+6}" y="{el["y"]+14}" font-family="DM Mono,monospace" '
                f'font-size="8" fill="{lc["accent"]}" opacity="0.7">{edef["label"]}</text>'
                f'<text x="{cx}" y="{cy}" text-anchor="middle" font-family="DM Sans,sans-serif" '
                f'font-size="11" font-weight="600" fill="#1A1A1A">{el["label"]}</text>'
            )

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    # ─────────────────────────────────────────────────────────────
    # SA Advisor UI
    # ─────────────────────────────────────────────────────────────

    st.markdown(
        '<div style="color:#777777;font-size:.72rem;font-weight:700;letter-spacing:.1em;'
        'text-transform:uppercase;margin-bottom:.6rem">SA Advisor · ArchiMate 3.1 Generator</div>',
        unsafe_allow_html=True
    )

    # Prompt input
    sa_prompt = st.text_area(
        "Architecture description",
        value=st.session_state.sa_prompt,
        placeholder="Describe your architecture… e.g. 'NEXUS AI agent governance with data stewardship and audit controls'",
        height=80,
        key="sa_prompt_input",
        label_visibility="collapsed",
    )

    col_btn, col_hint = st.columns([1, 4])
    with col_btn:
        generate_btn = st.button("Generate Diagram →", use_container_width=True, key="sa_generate")
    with col_hint:
        st.markdown(
            '<div style="color:#777777;font-size:.78rem;padding-top:.5rem">'
            'Powered by Claude via Anthropic API · Requires <code>ANTHROPIC_API_KEY</code> in .env</div>',
            unsafe_allow_html=True
        )

    # Example chips
    st.markdown('<div style="margin:.3rem 0 .6rem;color:#777777;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;font-weight:600">Examples</div>', unsafe_allow_html=True)
    ex_cols = st.columns(3)
    for i, ex in enumerate(SA_EXAMPLES):
        if ex_cols[i % 3].button(ex, key=f"sa_ex_{i}", use_container_width=True):
            st.session_state.sa_prompt = ex
            st.rerun()

    st.divider()

    # ── Generate ───────────────────────────────────────────────────
    if generate_btn and sa_prompt.strip():
        with st.spinner("Generating ArchiMate diagram via Claude…"):
            try:
                st.session_state.sa_result = call_sa_api(sa_prompt.strip())
                st.session_state.sa_prompt = sa_prompt.strip()
            except Exception as exc:
                st.error(f"Generation failed: {exc}")

    result = st.session_state.sa_result

    if result:
        elements = result.get("elements", [])
        rels     = result.get("relationships", [])
        pos, bands, svgW, svgH = layout_elements(elements)

        # Title
        st.markdown(
            f'<div style="font-size:1.1rem;font-weight:700;color:#1A1A1A;margin-bottom:1rem;'
            f'letter-spacing:-.01em">{result.get("title","Untitled Architecture")}</div>',
            unsafe_allow_html=True
        )

        diagram_tab, advisory_tab, elements_tab, export_tab = st.tabs([
            "Diagram", "SA Advisory", "Elements & Relations", "Export"
        ])

        with diagram_tab:
            svg_html = render_sa_diagram(result)
            st.markdown(
                f'<div style="overflow-x:auto;background:#F7F7F7;border:1px solid #D8D8D8;'
                f'border-radius:8px;padding:12px">{svg_html}</div>',
                unsafe_allow_html=True
            )
            # Legend
            legend_items = "".join(
                f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:16px;">'
                f'<span style="width:10px;height:10px;border-radius:2px;background:{lc["accent"]};opacity:.8;display:inline-block"></span>'
                f'<span style="color:{lc["accent"]};font-size:10px;font-family:DM Mono,monospace">{lyr}</span>'
                f'</span>'
                for lyr, lc in LAYER_COLORS.items()
            )
            rel_items = "".join(
                f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px;">'
                f'<svg width="20" height="8"><line x1="0" y1="4" x2="20" y2="4" stroke="{rs["color"]}" '
                f'stroke-width="1.5" {"stroke-dasharray=" + repr(rs["dash"]) if rs["dash"] != "none" else ""}/></svg>'
                f'<span style="color:#777777;font-size:9px">{rtype.replace("Relationship","")}</span>'
                f'</span>'
                for rtype, rs in list(REL_STYLES.items())[:5]
            )
            st.markdown(
                f'<div style="margin-top:8px;padding:6px 0;border-top:1px solid #D8D8D8;display:flex;flex-wrap:wrap;gap:4px">'
                f'{legend_items}{rel_items}</div>',
                unsafe_allow_html=True
            )

        with advisory_tab:
            advisory = result.get("advisory", "")
            paragraphs = [p.strip() for p in advisory.split("\n") if p.strip()]
            section_labels = [
                "Architecture Overview",
                "Design Decisions & Rationale",
                "Risks & Mitigations",
                "Strategic Recommendations",
            ]
            for i, para in enumerate(paragraphs):
                label = section_labels[i] if i < len(section_labels) else f"Section {i+1}"
                st.markdown(
                    f'<div class="sa-advisory-section">'
                    f'<div class="sa-section-label">{label}</div>'
                    f'<div style="color:#444444;font-size:.88rem;line-height:1.75">{para}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

        with elements_tab:
            st.markdown('<div class="sa-section-label" style="margin-bottom:.5rem">Elements by Layer</div>', unsafe_allow_html=True)
            for lyr in LAYER_ORDER:
                els_in_layer = [e for e in elements if (e.get("layer") or ELEMENT_DEFS.get(e["type"], {}).get("layer")) == lyr]
                if not els_in_layer:
                    continue
                lc = LAYER_COLORS[lyr]
                st.markdown(
                    f'<div style="font-size:.72rem;font-weight:700;letter-spacing:.08em;color:{lc["accent"]};'
                    f'text-transform:uppercase;margin:.8rem 0 .3rem">{lyr} Layer</div>',
                    unsafe_allow_html=True
                )
                for el in els_in_layer:
                    edef = ELEMENT_DEFS.get(el["type"], {"label": el["type"]})
                    st.markdown(
                        f'<div class="sa-detail-card sa-layer-band-{lyr}">'
                        f'<div style="display:flex;justify-content:space-between;margin-bottom:.2rem">'
                        f'<span style="color:#1A1A1A;font-weight:600;font-size:.85rem">{el["label"]}</span>'
                        f'<span style="color:{lc["accent"]};font-size:.72rem;font-family:DM Mono,monospace">{edef["label"]}</span>'
                        f'</div>'
                        f'<div style="color:#666666;font-size:.8rem">{el.get("description","")}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

            st.markdown('<div class="sa-section-label" style="margin:.8rem 0 .4rem">Relationships</div>', unsafe_allow_html=True)
            for rel in rels:
                rs       = REL_STYLES.get(rel["type"], REL_STYLES["AssociationRelationship"])
                from_el  = next((e for e in elements if e["id"] == rel["from"]), {})
                to_el    = next((e for e in elements if e["id"] == rel["to"]),   {})
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;padding:.3rem 0;border-bottom:1px solid #EBEBEB;">'
                    f'<span style="color:#333333;font-size:.82rem;min-width:120px">{from_el.get("label","?")}</span>'
                    f'<span style="color:{rs["color"]};font-family:DM Mono,monospace;font-size:.72rem;flex:1">──{rel.get("label","")or rel["type"].replace("Relationship","")}──▶</span>'
                    f'<span style="color:#333333;font-size:.82rem;min-width:120px;text-align:right">{to_el.get("label","?")}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

        with export_tab:
            st.markdown('<div class="sa-section-label" style="margin-bottom:.8rem">Export Options</div>', unsafe_allow_html=True)

            col_dx, col_sx = st.columns(2)

            with col_dx:
                drawio_xml = build_drawio_xml(result, pos, svgW, svgH)
                st.download_button(
                    label="⬇ Download draw.io XML",
                    data=drawio_xml,
                    file_name=f"{result.get('title','nexus-arch').replace(' ','_')}.drawio",
                    mime="application/xml",
                    use_container_width=True,
                )
                st.caption("Open in diagrams.net or draw.io — full ArchiMate shape library")

            with col_sx:
                svg_data = render_sa_diagram(result)
                st.download_button(
                    label="⬇ Download SVG",
                    data=svg_data,
                    file_name=f"{result.get('title','nexus-arch').replace(' ','_')}.svg",
                    mime="image/svg+xml",
                    use_container_width=True,
                )
                st.caption("Scalable vector graphic for documentation or presentations")

            st.markdown('<div class="sa-section-label" style="margin:.8rem 0 .4rem">Raw JSON</div>', unsafe_allow_html=True)
            st.code(json.dumps(result, indent=2), language="json")

    else:
        st.markdown(
            '<div style="text-align:center;padding:3rem 1rem;color:#444444;">'
            '<div style="font-size:2.5rem;margin-bottom:.8rem">🏛</div>'
            '<div style="font-size:.95rem;font-weight:600;color:#555555;margin-bottom:.4rem">No diagram generated yet</div>'
            '<div style="font-size:.82rem">Enter an architecture description above and click <strong style="color:#F36633">Generate Diagram</strong></div>'
            '</div>',
            unsafe_allow_html=True
        )


# ═══════════════════════════════════════════════════════════════════════
# TAB 4 — DATA QUERY (Text2SQL over Unity Catalog metadata)
# ═══════════════════════════════════════════════════════════════════════
with tab_data:
    try:
        from nexus.core.databricks_client import get_databricks
        from nexus.core.stardog_client import get_stardog as _get_stardog
        from nexus.ui.data_query_tab import render_data_query_tab
        _connected = st.session_state.get("connected", False)
        _stardog   = _get_stardog() if _connected else None
        _dbx       = get_databricks() if _connected else None
        render_data_query_tab(stardog=_stardog, databricks=_dbx)
    except Exception as _exc:
        st.error(f"Data Query tab failed to load: {_exc}")


# ═══════════════════════════════════════════════════════════════════════
# TAB 5 — PORTFOLIO INTELLIGENCE (APM TIME model)
# ═══════════════════════════════════════════════════════════════════════
with tab_portfolio:
    try:
        from nexus.ui.portfolio_tab import render_portfolio_tab
        render_portfolio_tab(
            connected=st.session_state.get("connected", False),
            user_role=st.session_state.get("user_role", "analyst"),
        )
    except Exception as _exc:
        st.error(f"Portfolio Intelligence tab failed to load: {_exc}")


# ═══════════════════════════════════════════════════════════════════════
# TAB 6 — SA PORTFOLIO HEALTH
# ═══════════════════════════════════════════════════════════════════════
with tab_sa_health:
    try:
        from nexus.ui.sa_health_tab import render_sa_health_tab
        render_sa_health_tab(
            connected=st.session_state.get("connected", False),
            user_role=st.session_state.get("user_role", "analyst"),
        )
    except Exception as _exc:
        st.error(f"SA Health tab failed to load: {_exc}")


# ═══════════════════════════════════════════════════════════════════════
# TAB 7 — ARCHITECTURE DIAGRAM STUDIO
# ═══════════════════════════════════════════════════════════════════════
with tab_diagram:
    try:
        from nexus.ui.diagram_tab import render_diagram_tab
        render_diagram_tab(
            connected=st.session_state.get("connected", False),
            user_role=st.session_state.get("user_role", "analyst"),
        )
    except Exception as _exc:
        st.error(f"Architecture Diagrams tab failed to load: {_exc}")


# ═══════════════════════════════════════════════════════════════════════
# TAB 8 — CHANGE IMPACT RADAR
# ═══════════════════════════════════════════════════════════════════════
with tab_impact:
    try:
        from nexus.ui.impact_tab import render_impact_tab
        render_impact_tab(
            connected=st.session_state.get("connected", False),
            user_role=st.session_state.get("user_role", "analyst"),
        )
    except Exception as _exc:
        st.error(f"Change Impact tab failed to load: {_exc}")


# ═══════════════════════════════════════════════════════════════════════
# TAB 9 — AUDIT & OBSERVABILITY
# ═══════════════════════════════════════════════════════════════════════
with tab_audit:
    try:
        from nexus.ui.audit_tab import render_audit_tab
        render_audit_tab(user_role=st.session_state.get("user_role", "analyst"))
    except Exception as _exc:
        st.error(f"Audit tab failed to load: {_exc}")