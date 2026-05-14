"""
core/artifact_creator.py — Architecture Diagram Generator

Queries the NEXUS knowledge graph and produces architecture diagrams.
Supports both Graphviz DOT format (for Streamlit's st.graphviz_chart)
and Mermaid syntax (rendered via HTML component).

Supported diagram types:
  dependency     — Application dependency map (who depends on whom)
  capability_map — Business capability map with supporting applications
  data_lineage   — Data lineage from source to consumption
  agent_ecosystem— AI agent ecosystem: agents, tools, data access
  c4_context     — C4 Context diagram for a single application
  org_ownership  — Ownership/accountability map by person/team
  integration    — Integration topology: APIs, messaging, DB connections

Output formats:
  dot            — Graphviz DOT (st.graphviz_chart)
  mermaid        — Mermaid syntax (HTML component with mermaid.js)

Usage:
    result = generate_diagram("dependency", entity="PaymentService", fmt="dot")
    st.graphviz_chart(result.content)
"""
from __future__ import annotations
import logging
import textwrap
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class DiagramResult:
    diagram_type: str
    entity:       str
    fmt:          str          # dot | mermaid
    content:      str          # the diagram source code
    title:        str
    node_count:   int
    edge_count:   int
    error:        str | None = None


# ── Diagram dispatcher ─────────────────────────────────────────────────────────

_GENERATORS = {}

def diagram_type(name: str):
    """Decorator to register a diagram generator function."""
    def decorator(fn):
        _GENERATORS[name] = fn
        return fn
    return decorator


def generate_diagram(
    diagram_type:  str,
    entity:        str = "",
    depth:         int = 2,
    fmt:           str = "dot",
    domain_filter: str = "",
    max_nodes:     int = 60,
) -> DiagramResult:
    """
    Main entry point. Dispatch to the appropriate generator.

    Args:
        diagram_type:  One of: dependency | capability_map | data_lineage |
                       agent_ecosystem | c4_context | org_ownership | integration
        entity:        Entity name or fragment to centre the diagram on.
        depth:         Traversal depth (1–4). Higher = more complex diagram.
        fmt:           Output format: dot | mermaid
        domain_filter: Optional domain to scope the diagram.
        max_nodes:     Cap on number of nodes to keep diagrams legible.

    Returns:
        DiagramResult with source code and metadata.
    """
    generator = _GENERATORS.get(diagram_type)
    if generator is None:
        return DiagramResult(
            diagram_type=diagram_type, entity=entity, fmt=fmt,
            content="", title="", node_count=0, edge_count=0,
            error=f"Unknown diagram type '{diagram_type}'. "
                  f"Available: {', '.join(_GENERATORS.keys())}",
        )

    try:
        return generator(entity=entity, depth=depth, fmt=fmt,
                        domain_filter=domain_filter, max_nodes=max_nodes)
    except Exception as exc:
        logger.error("generate_diagram(%s, %s): %s", diagram_type, entity, exc)
        return DiagramResult(
            diagram_type=diagram_type, entity=entity, fmt=fmt,
            content="", title="", node_count=0, edge_count=0,
            error=str(exc),
        )


# ── Shared graph query helpers ─────────────────────────────────────────────────

def _db():
    from nexus.core.stardog_client import get_stardog
    return get_stardog()


def _safe_id(s: str) -> str:
    """Convert a label to a safe DOT/Mermaid node ID (alphanumeric + underscore only)."""
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in str(s))
    # Ensure it starts with a letter or underscore (required by DOT/Mermaid)
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned[:40] or "_unknown"


def _trunc(s: str, n: int = 25) -> str:
    """Truncate a label for display."""
    return s[:n] + "…" if len(s) > n else s


# ── DOT helpers ────────────────────────────────────────────────────────────────

DOT_STYLES = {
    "Application":         'shape=box,     style=filled, fillcolor="#1e3a6e", fontcolor="#e2e8f0", color="#2e75b6"',
    "BusinessCapability":  'shape=hexagon, style=filled, fillcolor="#052e16", fontcolor="#86efac", color="#166534"',
    "DataAsset":           'shape=cylinder,style=filled, fillcolor="#1c1206", fontcolor="#fcd34d", color="#78350f"',
    "Person":              'shape=ellipse, style=filled, fillcolor="#1a0a08", fontcolor="#fca5a5", color="#7c2d12"',
    "AIAgent":             'shape=diamond, style=filled, fillcolor="#1a1033", fontcolor="#c4b5fd", color="#7c3aed"',
    "Infrastructure":      'shape=rect,    style=filled, fillcolor="#0f172a", fontcolor="#94a3b8", color="#334155"',
    "default":             'shape=rect,    style=filled, fillcolor="#0a1628", fontcolor="#cbd5e1", color="#1e3a6e"',
}

DOT_EDGE_STYLE = 'color="#2e75b6" fontcolor="#64748b" fontsize=9'

DOT_GRAPH_ATTRS = textwrap.dedent("""
    graph [
        bgcolor="#060d1a"
        fontcolor="#94a3b8"
        fontname="sans-serif"
        rankdir=LR
        pad=0.4
        nodesep=0.5
        ranksep=0.8
        splines=curved
    ]
    node [fontname="sans-serif" fontsize=10]
    edge [fontname="sans-serif" fontsize=9 arrowsize=0.7]
""").strip()


def _dot_graph(title: str, nodes: list[tuple], edges: list[tuple]) -> str:
    """
    Build a DOT digraph string.
    nodes: [(id, label, type), ...]
    edges: [(from_id, to_id, label), ...]
    """
    lines = [f'digraph "{title}" {{', DOT_GRAPH_ATTRS, ""]

    for node_id, label, ntype in nodes:
        style = DOT_STYLES.get(ntype, DOT_STYLES["default"])
        lines.append(f'  {node_id} [label="{_trunc(label)}", {style}]')

    lines.append("")
    for src, dst, lbl in edges:
        edge_lbl = f' [label="{_trunc(lbl, 15)}" {DOT_EDGE_STYLE}]' if lbl else f" [{DOT_EDGE_STYLE}]"
        lines.append(f"  {src} -> {dst}{edge_lbl}")

    lines.append("}")
    return "\n".join(lines)


# ── Mermaid helpers ────────────────────────────────────────────────────────────

def _mermaid_flowchart(title: str, nodes: list[tuple], edges: list[tuple],
                        direction: str = "LR") -> str:
    """
    Build Mermaid flowchart syntax.
    nodes: [(id, label, shape_char), ...]  shape_char: [] box, () rounded, {} rhombus, (()) circle
    edges: [(from_id, to_id, label), ...]
    """
    lines = [f"---", f"title: {title}", f"---", f"flowchart {direction}", ""]

    for node_id, label, shape in nodes:
        l, r = {
            "box":    ("[", "]"),
            "round":  ("(", ")"),
            "rhombus":("{", "}"),
            "circle": ("((", "))"),
            "hex":    ("{{", "}}"),
            "cyl":    ("[(", ")]"),
        }.get(shape, ("[", "]"))
        lines.append(f"  {node_id}{l}{_trunc(label)}{r}")

    lines.append("")
    for src, dst, lbl in edges:
        arrow = f"-->|{_trunc(lbl, 20)}|" if lbl else "-->"
        lines.append(f"  {src} {arrow} {dst}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# DIAGRAM GENERATORS
# ══════════════════════════════════════════════════════════════════════════════

@diagram_type("dependency")
def _dependency_map(entity: str = "", depth: int = 2, fmt: str = "dot",
                    domain_filter: str = "", max_nodes: int = 60) -> DiagramResult:
    """Application dependency map centred on an entity (or full portfolio)."""
    db = _db()

    if entity:
        q = f"""
        SELECT DISTINCT ?app ?appLabel ?dep ?depLabel WHERE {{
            ?app a app:Application ;
                 rdfs:label ?appLabel .
            FILTER(CONTAINS(LCASE(STR(?appLabel)), "{entity.lower()}"))
            ?app (app:dependsOn){{1,{depth}}} ?dep .
            ?dep a app:Application .
            OPTIONAL {{ ?dep rdfs:label ?depLabel }}
        }} LIMIT {max_nodes}
        """
        title = f"Dependency Map: {entity}"
    else:
        q = f"""
        SELECT DISTINCT ?app ?appLabel ?dep ?depLabel WHERE {{
            ?app a app:Application ;
                 rdfs:label ?appLabel .
            ?dep a app:Application .
            OPTIONAL {{ ?dep rdfs:label ?depLabel }}
            {{ ?app app:dependsOn ?dep }} UNION {{ ?dep app:dependsOn ?app }}
            {'FILTER(CONTAINS(LCASE(STR(?appLabel)), "' + domain_filter.lower() + '"))' if domain_filter else ''}
        }} LIMIT {max_nodes}
        """
        title = f"Application Dependency Map{f' — {domain_filter}' if domain_filter else ''}"

    _, rows = db.to_rows(db.query(q))

    nodes_seen: dict[str, str] = {}
    edges: list[tuple] = []

    for r in rows:
        for k, lbl_k in [("app", "appLabel"), ("dep", "depLabel")]:
            uri = r.get(k, "")
            lbl = r.get(lbl_k) or uri.split("#")[-1].split("/")[-1]
            nid = _safe_id(lbl)
            nodes_seen[nid] = lbl

        src = _safe_id(r.get("appLabel") or r.get("app", ""))
        dst = _safe_id(r.get("depLabel") or r.get("dep", ""))
        if src and dst and src != dst:
            edges.append((src, dst, "depends on"))

    nodes = [(nid, lbl, "Application") for nid, lbl in nodes_seen.items()]
    content = _dot_graph(title, nodes, edges) if fmt == "dot" else \
              _mermaid_flowchart(title, [(n, l, "box") for n, l, _ in nodes], edges)

    return DiagramResult(
        diagram_type="dependency", entity=entity, fmt=fmt,
        content=content, title=title,
        node_count=len(nodes), edge_count=len(edges),
    )


@diagram_type("capability_map")
def _capability_map(entity: str = "", depth: int = 2, fmt: str = "mermaid",
                    domain_filter: str = "", max_nodes: int = 80) -> DiagramResult:
    """Business capability map showing capabilities and their supporting applications."""
    db = _db()

    domain_clause = (
        f'FILTER(CONTAINS(LCASE(STR(?domain)), "{domain_filter.lower()}"))'
        if domain_filter else ""
    )
    entity_clause = (
        f'FILTER(CONTAINS(LCASE(STR(?capLabel)), "{entity.lower()}"))'
        if entity else ""
    )

    q = f"""
    SELECT ?cap ?capLabel ?app ?appLabel ?lifecycle ?domain WHERE {{
        ?cap a ea:BusinessCapability .
        OPTIONAL {{ ?cap rdfs:label  ?capLabel }}
        OPTIONAL {{ ?cap ea:domain   ?domain   }}
        OPTIONAL {{
            ?app a app:Application ;
                 ea:enablesBusinessCapability ?cap .
            OPTIONAL {{ ?app rdfs:label   ?appLabel   }}
            OPTIONAL {{ ?app app:lifecycle ?lifecycle  }}
        }}
        {entity_clause}
        {domain_clause}
    }} LIMIT {max_nodes}
    """

    _, rows = db.to_rows(db.query(q))

    # Group by domain → capability → [apps]
    structure: dict[str, dict[str, list[tuple]]] = {}
    for r in rows:
        domain = (r.get("domain") or "Ungrouped").split("#")[-1].split("/")[-1]
        cap    = r.get("capLabel") or r.get("cap", "?")
        app    = r.get("appLabel", "")
        lc     = r.get("lifecycle", "")
        if domain not in structure:
            structure[domain] = {}
        if cap not in structure[domain]:
            structure[domain][cap] = []
        if app:
            structure[domain][cap].append((app, lc))

    title = f"Business Capability Map{f' — {domain_filter or entity}' if (domain_filter or entity) else ''}"

    if fmt == "mermaid":
        lines = ["---", f"title: {title}", "---", "flowchart TB", ""]
        edge_lines = []

        for domain, caps in structure.items():
            did = _safe_id(domain)
            lines.append(f"  subgraph {did}[\"{_trunc(domain, 30)}\"]")
            for cap, apps in caps.items():
                cid = _safe_id(cap)
                lines.append(f"    {cid}{{{{\"{_trunc(cap, 22)}\"}}}}")
                for app_label, lc in apps:
                    aid = _safe_id(app_label)
                    lc_icon = "⚠️" if lc in ("retire", "legacy", "eol", "sunset") else "✅" if lc == "active" else "🔵"
                    lines.append(f"    {aid}[\"{lc_icon} {_trunc(app_label, 20)}\"]")
                    edge_lines.append(f"  {cid} --> {aid}")
            lines.append("  end")
            lines.append("")

        lines.extend(edge_lines)
        content = "\n".join(lines)

    else:  # dot
        dot_nodes = []
        dot_edges = []
        for domain, caps in structure.items():
            for cap, apps in caps.items():
                cid = _safe_id(cap)
                dot_nodes.append((cid, cap, "BusinessCapability"))
                for app_label, _ in apps:
                    aid = _safe_id(app_label)
                    dot_nodes.append((aid, app_label, "Application"))
                    dot_edges.append((cid, aid, "realised by"))
        content = _dot_graph(title, dot_nodes, dot_edges)

    all_apps = sum(len(apps) for caps in structure.values() for apps in caps.values())
    return DiagramResult(
        diagram_type="capability_map", entity=entity or domain_filter, fmt=fmt,
        content=content, title=title,
        node_count=sum(len(caps) for caps in structure.values()) + all_apps,
        edge_count=all_apps,
    )


@diagram_type("data_lineage")
def _data_lineage(entity: str = "", depth: int = 3, fmt: str = "dot",
                  domain_filter: str = "", max_nodes: int = 50) -> DiagramResult:
    """Data lineage diagram showing upstream and downstream data flows."""
    db = _db()

    anchor = f'FILTER(CONTAINS(LCASE(STR(?assetLabel)), "{entity.lower()}"))' if entity else ""

    up_q = f"""
    SELECT ?asset ?assetLabel ?upstream ?upstreamLabel ?classification WHERE {{
        ?asset a data:DataAsset .
        OPTIONAL {{ ?asset rdfs:label          ?assetLabel     }}
        OPTIONAL {{ ?asset data:classification ?classification }}
        {anchor}
        ?asset (data:lineageFrom){{1,{depth}}} ?upstream .
        OPTIONAL {{ ?upstream rdfs:label ?upstreamLabel }}
    }} LIMIT {max_nodes // 2}
    """
    down_q = f"""
    SELECT ?asset ?assetLabel ?downstream ?downstreamLabel WHERE {{
        ?asset a data:DataAsset .
        OPTIONAL {{ ?asset rdfs:label ?assetLabel }}
        {anchor}
        ?downstream (data:lineageFrom){{1,{depth}}} ?asset .
        OPTIONAL {{ ?downstream rdfs:label ?downstreamLabel }}
    }} LIMIT {max_nodes // 2}
    """

    upstream_rows, downstream_rows = [], []
    try:
        _, upstream_rows   = db.to_rows(db.query(up_q))
    except Exception:
        pass
    try:
        _, downstream_rows = db.to_rows(db.query(down_q))
    except Exception:
        pass

    nodes_seen: dict[str, tuple[str, str]] = {}
    edges: list[tuple] = []

    def add_asset(uri, label, classification=""):
        nid = _safe_id(label or uri)
        nodes_seen[nid] = (label or nid, classification)
        return nid

    for r in upstream_rows:
        a  = add_asset(r.get("asset", ""), r.get("assetLabel", ""), r.get("classification", ""))
        up = add_asset(r.get("upstream", ""), r.get("upstreamLabel", ""))
        edges.append((up, a, "feeds"))

    for r in downstream_rows:
        a  = add_asset(r.get("asset", ""), r.get("assetLabel", ""))
        dn = add_asset(r.get("downstream", ""), r.get("downstreamLabel", ""))
        edges.append((a, dn, "feeds"))

    title = f"Data Lineage{f': {entity}' if entity else ''}"

    if fmt == "dot":
        dot_nodes = []
        for nid, (lbl, cls) in nodes_seen.items():
            colour = "#7c2d12" if cls == "Restricted" else "#78350f" if cls == "Confidential" else "#1c1206"
            dot_nodes.append((nid, f"{lbl}\\n[{cls}]" if cls else lbl, "DataAsset"))
        content = _dot_graph(title, dot_nodes, edges)
    else:
        mermaid_nodes = [
            (nid, f"{lbl} [{cls}]" if cls else lbl, "cyl")
            for nid, (lbl, cls) in nodes_seen.items()
        ]
        content = _mermaid_flowchart(title, mermaid_nodes, edges, direction="LR")

    return DiagramResult(
        diagram_type="data_lineage", entity=entity, fmt=fmt,
        content=content, title=title,
        node_count=len(nodes_seen), edge_count=len(edges),
    )


@diagram_type("agent_ecosystem")
def _agent_ecosystem(entity: str = "", depth: int = 1, fmt: str = "mermaid",
                     domain_filter: str = "", max_nodes: int = 50) -> DiagramResult:
    """AI agent ecosystem: agents, their tools, data access, and risk tiers."""
    db = _db()

    q = f"""
    SELECT ?agent ?agentLabel ?riskTier ?platform ?tool ?toolLabel ?asset ?assetLabel ?classification WHERE {{
        ?agent a ai:Agent .
        OPTIONAL {{ ?agent rdfs:label    ?agentLabel }}
        OPTIONAL {{ ?agent ai:riskTier  ?riskTier   }}
        OPTIONAL {{ ?agent ai:platform  ?platform   }}
        OPTIONAL {{ ?agent ai:hasTool   ?tool .
                    ?tool  rdfs:label   ?toolLabel  }}
        OPTIONAL {{
            ?agent (ai:reads | ai:writes | ai:accesses) ?asset .
            OPTIONAL {{ ?asset rdfs:label          ?assetLabel     }}
            OPTIONAL {{ ?asset data:classification ?classification }}
        }}
        {'FILTER(CONTAINS(LCASE(STR(?agentLabel)), "' + entity.lower() + '"))' if entity else ''}
    }} LIMIT {max_nodes}
    """

    _, rows = db.to_rows(db.query(q))

    agents:  dict[str, str] = {}   # id → label
    tools:   dict[str, str] = {}
    assets:  dict[str, tuple] = {}
    edges:   list[tuple] = []

    for r in rows:
        albl  = r.get("agentLabel", "?")
        aid   = _safe_id(albl)
        risk  = r.get("riskTier", "")
        agents[aid] = f"{albl}\\n[{risk}]" if risk else albl

        if r.get("toolLabel"):
            tlbl = r.get("toolLabel", "")
            tid  = _safe_id(tlbl)
            tools[tid] = tlbl
            edges.append((aid, tid, "uses"))

        if r.get("assetLabel"):
            aslbl = r.get("assetLabel", "")
            cls   = r.get("classification", "")
            asid  = _safe_id(aslbl)
            assets[asid] = (aslbl, cls)
            edges.append((aid, asid, "accesses"))

    title = f"AI Agent Ecosystem{f': {entity}' if entity else ''}"

    if fmt == "mermaid":
        lines = ["---", f"title: {title}", "---", "flowchart LR", ""]
        lines.append("  subgraph AGENTS[AI Agents]")
        for aid, albl in agents.items():
            lines.append(f"    {aid}((\"{_trunc(albl, 20)}\"))")
        lines.append("  end\n")

        if tools:
            lines.append("  subgraph TOOLS[Agent Tools]")
            for tid, tlbl in tools.items():
                lines.append(f"    {tid}[\"{_trunc(tlbl, 22)}\"]")
            lines.append("  end\n")

        if assets:
            lines.append("  subgraph DATA[Data Assets]")
            for asid, (aslbl, cls) in assets.items():
                icon = "🔴" if cls == "Restricted" else "🟡" if cls == "Confidential" else "🟢"
                lines.append(f"    {asid}[(\"{icon} {_trunc(aslbl, 20)}\")]")
            lines.append("  end\n")

        for src, dst, lbl in edges:
            lines.append(f"  {src} -->|\"{lbl}\"| {dst}")

        content = "\n".join(lines)

    else:  # dot
        nodes = (
            [(aid, lbl, "AIAgent")        for aid, lbl in agents.items()] +
            [(tid, lbl, "default")        for tid, lbl in tools.items()] +
            [(asid, lbl, "DataAsset")     for asid, (lbl, _) in assets.items()]
        )
        content = _dot_graph(title, nodes, edges)

    return DiagramResult(
        diagram_type="agent_ecosystem", entity=entity, fmt=fmt,
        content=content, title=title,
        node_count=len(agents) + len(tools) + len(assets),
        edge_count=len(edges),
    )


@diagram_type("c4_context")
def _c4_context(entity: str = "", depth: int = 1, fmt: str = "mermaid",
                domain_filter: str = "", max_nodes: int = 40) -> DiagramResult:
    """C4 Context diagram for an application — shows users, systems, and integrations."""
    db = _db()

    q = f"""
    SELECT ?app ?appLabel ?owner ?ownerLabel ?dep ?depLabel
           ?capability ?capLabel ?user ?userLabel WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label ?appLabel }}
        FILTER(CONTAINS(LCASE(STR(?appLabel)), "{entity.lower()}"))
        OPTIONAL {{ ?app app:techOwner              ?owner .     ?owner rdfs:label ?ownerLabel }}
        OPTIONAL {{ ?app app:dependsOn              ?dep   .     ?dep   rdfs:label ?depLabel   }}
        OPTIONAL {{ ?app ea:enablesBusinessCapability ?capability . ?capability rdfs:label ?capLabel }}
        OPTIONAL {{
            ?user a hr:User ;
                  sec:hasAccess ?app .
            OPTIONAL {{ ?user rdfs:label ?userLabel }}
        }}
    }} LIMIT {max_nodes}
    """

    _, rows = db.to_rows(db.query(q))

    if not rows:
        return DiagramResult(
            diagram_type="c4_context", entity=entity, fmt=fmt,
            content="", title=f"C4 Context: {entity}",
            node_count=0, edge_count=0,
            error=f"Application '{entity}' not found in graph.",
        )

    anchor_lbl = rows[0].get("appLabel") or entity
    anchor_id  = _safe_id(anchor_lbl)

    deps:  dict[str, str] = {}
    caps:  dict[str, str] = {}
    users: dict[str, str] = {}
    edges: list[tuple]    = []

    for r in rows:
        if r.get("depLabel"):
            did = _safe_id(r["depLabel"])
            deps[did] = r["depLabel"]
            edges.append((anchor_id, did, "depends on"))
        if r.get("capLabel"):
            cid = _safe_id(r["capLabel"])
            caps[cid] = r["capLabel"]
            edges.append((cid, anchor_id, "realised by"))
        if r.get("userLabel"):
            uid = _safe_id(r["userLabel"])
            users[uid] = r["userLabel"]
            edges.append((uid, anchor_id, "uses"))

    title = f"C4 Context: {anchor_lbl}"

    if fmt == "mermaid":
        owner_lbl = rows[0].get("ownerLabel", "")
        lines = [
            "---", f"title: {title}", "---", "C4Context", "",
            f'  Person({_safe_id(owner_lbl or "owner")}, "{owner_lbl or "Owner"}", "Technical Owner")'
            if owner_lbl else "",
        ]
        for uid, ulbl in users.items():
            lines.append(f'  Person({uid}, "{_trunc(ulbl, 20)}", "Enterprise User")')
        lines.append(f'  System({anchor_id}, "{_trunc(anchor_lbl, 25)}", "Target System")')
        for did, dlbl in deps.items():
            lines.append(f'  System_Ext({did}, "{_trunc(dlbl, 20)}", "Dependency")')
        lines.append("")
        for src, dst, lbl in edges:
            lines.append(f'  Rel({src}, {dst}, "{lbl}")')
        content = "\n".join(l for l in lines if l)

    else:  # dot
        nodes = (
            [(anchor_id, anchor_lbl,  "Application")] +
            [(did, dlbl, "Application") for did, dlbl in deps.items()] +
            [(cid, clbl, "BusinessCapability") for cid, clbl in caps.items()] +
            [(uid, ulbl, "Person")       for uid, ulbl in users.items()]
        )
        content = _dot_graph(title, nodes, edges)

    return DiagramResult(
        diagram_type="c4_context", entity=entity, fmt=fmt,
        content=content, title=title,
        node_count=1 + len(deps) + len(caps) + len(users),
        edge_count=len(edges),
    )


@diagram_type("org_ownership")
def _org_ownership(entity: str = "", depth: int = 2, fmt: str = "dot",
                   domain_filter: str = "", max_nodes: int = 60) -> DiagramResult:
    """Ownership and accountability map — who owns what applications and data."""
    db = _db()

    person_filter = (
        f'FILTER(CONTAINS(LCASE(STR(?ownerLabel)), "{entity.lower()}"))'
        if entity else ""
    )
    domain_clause = (
        f'FILTER(CONTAINS(LCASE(STR(?domain)), "{domain_filter.lower()}"))'
        if domain_filter else ""
    )

    q = f"""
    SELECT ?owner ?ownerLabel ?dept ?deptLabel ?app ?appLabel ?asset ?assetLabel WHERE {{
        ?owner a hr:User .
        OPTIONAL {{ ?owner rdfs:label    ?ownerLabel }}
        OPTIONAL {{ ?owner hr:department ?dept .
                    ?dept  rdfs:label    ?deptLabel  }}
        OPTIONAL {{ ?app a app:Application ;
                         app:techOwner ?owner .
                    OPTIONAL {{ ?app rdfs:label ?appLabel }}
                    OPTIONAL {{ ?app ea:domain  ?domain   }}
                    {domain_clause} }}
        OPTIONAL {{ ?asset a data:DataAsset ;
                           data:owner ?owner .
                    OPTIONAL {{ ?asset rdfs:label ?assetLabel }} }}
        {person_filter}
    }} LIMIT {max_nodes}
    """

    _, rows = db.to_rows(db.query(q))

    owners: dict[str, str] = {}
    depts:  dict[str, str] = {}
    apps:   dict[str, str] = {}
    assets: dict[str, str] = {}
    edges:  list[tuple] = []

    for r in rows:
        olbl = r.get("ownerLabel", "")
        if olbl:
            oid = _safe_id(olbl)
            owners[oid] = olbl
            if r.get("deptLabel"):
                did = _safe_id(r["deptLabel"])
                depts[did] = r["deptLabel"]
                edges.append((did, oid, "member"))
            if r.get("appLabel"):
                aid = _safe_id(r["appLabel"])
                apps[aid] = r["appLabel"]
                edges.append((oid, aid, "owns"))
            if r.get("assetLabel"):
                asid = _safe_id(r["assetLabel"])
                assets[asid] = r["assetLabel"]
                edges.append((oid, asid, "stewards"))

    title = f"Ownership Map{f': {entity or domain_filter}' if (entity or domain_filter) else ''}"
    nodes = (
        [(did,  dlbl, "default")     for did,  dlbl  in depts.items()] +
        [(oid,  olbl, "Person")      for oid,  olbl  in owners.items()] +
        [(aid,  albl, "Application") for aid,  albl  in apps.items()] +
        [(asid, aslbl,"DataAsset")   for asid, aslbl in assets.items()]
    )
    content = _dot_graph(title, nodes, edges) if fmt == "dot" else \
              _mermaid_flowchart(title, [(n, l, "box") for n, l, _ in nodes], edges)

    return DiagramResult(
        diagram_type="org_ownership", entity=entity, fmt=fmt,
        content=content, title=title,
        node_count=len(nodes), edge_count=len(edges),
    )


@diagram_type("integration")
def _integration_map(entity: str = "", depth: int = 2, fmt: str = "dot",
                     domain_filter: str = "", max_nodes: int = 50) -> DiagramResult:
    """
    Integration topology map — shows APIs, messaging, DB connections between apps.
    Highlights hotspot integrators (high fan-in/fan-out).
    """
    db = _db()

    anchor_clause = (
        f'FILTER(CONTAINS(LCASE(STR(?appLabel)), "{entity.lower()}"))'
        if entity else ""
    )
    domain_clause = (
        f'FILTER(CONTAINS(LCASE(STR(?domain)), "{domain_filter.lower()}"))'
        if domain_filter else ""
    )

    q = f"""
    SELECT DISTINCT ?app ?appLabel ?dep ?depLabel ?intType ?domain WHERE {{
        ?app a app:Application .
        OPTIONAL {{ ?app rdfs:label  ?appLabel }}
        OPTIONAL {{ ?app ea:domain   ?domain   }}
        {anchor_clause}
        {domain_clause}
        {{ ?app app:dependsOn ?dep . BIND("dependsOn" AS ?intType) }}
        UNION
        {{ ?app cmdb:connectsTo ?dep . BIND("API" AS ?intType) }}
        UNION
        {{ ?app cmdb:subscribesTo ?dep . BIND("Event" AS ?intType) }}
        ?dep a app:Application .
        OPTIONAL {{ ?dep rdfs:label ?depLabel }}
    }} LIMIT {max_nodes}
    """

    _, rows = db.to_rows(db.query(q))

    nodes: dict[str, str] = {}
    edges: list[tuple] = []

    for r in rows:
        for k, lk in [("app", "appLabel"), ("dep", "depLabel")]:
            lbl = r.get(lk) or r.get(k, "?")
            nodes[_safe_id(lbl)] = lbl

        src = _safe_id(r.get("appLabel") or "")
        dst = _safe_id(r.get("depLabel") or "")
        if src and dst and src != dst:
            edges.append((src, dst, r.get("intType", "")))

    title = f"Integration Topology{f': {entity or domain_filter}' if (entity or domain_filter) else ''}"
    dot_nodes = [(nid, lbl, "Application") for nid, lbl in nodes.items()]
    content = _dot_graph(title, dot_nodes, edges) if fmt == "dot" else \
              _mermaid_flowchart(title, [(n, l, "box") for n, l in nodes.items()], edges)

    return DiagramResult(
        diagram_type="integration", entity=entity, fmt=fmt,
        content=content, title=title,
        node_count=len(nodes), edge_count=len(edges),
    )


# ── Available diagram types (for UI) ──────────────────────────────────────────

DIAGRAM_TYPES = {
    "dependency":     "Application Dependency Map",
    "capability_map": "Business Capability Map",
    "data_lineage":   "Data Lineage Diagram",
    "agent_ecosystem":"AI Agent Ecosystem",
    "c4_context":     "C4 Context Diagram",
    "org_ownership":  "Ownership & Accountability Map",
    "integration":    "Integration Topology",
}

ENTITY_REQUIRED = {"c4_context", "data_lineage"}
