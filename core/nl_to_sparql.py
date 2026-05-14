"""
core/nl_to_sparql.py — Natural language → SPARQL pipeline.

This version fixes the next priority issues:
- removes stale DOMAIN_HINTS from generation
- uses ontology snapshot as the only schema source of truth
- handles o3/o1 token parameter differences cleanly
- avoids unsupported temperature for reasoning models
- injects missing PREFIX declarations when the model forgets them
- preserves full IRIs such as <urn:EA_AI_Intelligence:manages_user>
"""
from __future__ import annotations

import logging
import re
from openai import OpenAI

from nexus.config.settings import settings
from nexus.config.ontology_prefixes import PREFIXES, SPARQL_PREFIX_BLOCK
from nexus.core.ontology import get_ontology

logger = logging.getLogger(__name__)

_client: OpenAI | None = None

_REASONING_PREFIXES = ("o3", "o1")
_PREFIX_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_-]*):[A-Za-z_][A-Za-z0-9_-]*\b")


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai.api_key)
    return _client


def _content(msg) -> str:
    """Normalise OpenAI message content to string."""
    c = msg.content if hasattr(msg, "content") else msg.get("content", "")
    if isinstance(c, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return str(c)


def _is_reasoning_model(model: str) -> bool:
    model_l = (model or "").lower()
    return model_l.startswith(_REASONING_PREFIXES)


def _chat_completion(model: str, messages: list[dict], max_tokens: int):
    params = {
        "model": model,
        "messages": messages,
    }
    if _is_reasoning_model(model):
        params["max_completion_tokens"] = max_tokens
    else:
        params["max_tokens"] = max_tokens
        params["temperature"] = 0
    return _openai().chat.completions.create(**params)


def nl_to_sparql(
    question: str,
    clarification_context: str = "",
    user_role: str = "analyst",
    use_virtual_graph: bool = False,
    extra_filters: str = "",
) -> str:
    """
    Translate a natural language question to a SPARQL query.

    Args:
        question:               The user's question in plain English.
        clarification_context:  Optional confirmed context from the clarification step.
        user_role:              The authenticated user's role — used to inject scope guidance.
        use_virtual_graph:      Whether to include Denodo SERVICE guidance.
        extra_filters:          Additional SPARQL FILTER clauses injected by the security layer.

    Returns:
        A clean SPARQL string, ready to execute.
    """
    ont = get_ontology()

    vg_hint = (
        "\nFor live operational data, use Denodo virtual graph SERVICE blocks only when the ontology and question clearly require them.\n"
        if use_virtual_graph else ""
    )

    clarification_block = (
        f"\nConfirmed context from user:\n{clarification_context}\n"
        if clarification_context else ""
    )

    role_hint = (
        f"\nThe querying user has role '{user_role}'. Apply appropriate scope and avoid over-broad access patterns."
        if user_role != "admin" else ""
    )

    extra_filter_hint = (
        f"\nIf applicable, inject these additional FILTER clauses inside the WHERE clause exactly as given:\n{extra_filters}\n"
        if extra_filters else ""
    )

    system = f"""You are a SPARQL expert for NEXUS, an Enterprise Knowledge Graph.

Use ONLY the ontology snapshot below as the source of truth for classes, predicates, and directions.
Do NOT invent classes, predicates, inverse relationships, or substitute a prefixed name for a full IRI.
If the ontology shows a full IRI like <urn:EA_AI_Intelligence:manages_user>, preserve it exactly.

ONTOLOGY SNAPSHOT:
{ont.full_text}

AVAILABLE PREFIX DECLARATIONS:
{SPARQL_PREFIX_BLOCK}

{vg_hint}{clarification_block}{role_hint}{extra_filter_hint}

DOMAIN KNOWLEDGE — key concept mappings (use these instead of inventing patterns):

CRITICAL — HOW TO NAVIGATE TECHNOLOGY QUESTIONS:
When the user asks "what technologies / platforms / tools are used for X", the answer lives in the
capability graph. NEVER filter on technology labels (?techLabel). ALWAYS filter on capability labels.
The path is: ea:Technology --ea:enablesTechnologyCapabilityL3--> ea:TechnologyCapabilityL3
Capability hierarchy: L1 --ea:hasChildTechnologyCapability--> L2 --ea:hasChildTechnologyCapability--> L3

Pattern for ANY "technologies for <domain>" question:
  SELECT DISTINCT ?techLabel ?capLabel WHERE {{
    ?tech a ea:Technology ; rdfs:label ?techLabel ;
          ea:enablesTechnologyCapabilityL3 ?cap .
    ?cap rdfs:label ?capLabel .
    FILTER(CONTAINS(LCASE(?capLabel), "<key term from question>"))
  }} ORDER BY ?capLabel ?techLabel LIMIT 100

When the question spans multiple capability levels (e.g. "Data Platforms"), widen the search
across L1/L2/L3 labels using OPTIONAL traversal up the hierarchy:
  SELECT DISTINCT ?techLabel ?l3Label ?l2Label WHERE {{
    ?tech a ea:Technology ; rdfs:label ?techLabel ;
          ea:enablesTechnologyCapabilityL3 ?l3 .
    ?l3 rdfs:label ?l3Label .
    OPTIONAL {{ ?l2 ea:hasChildTechnologyCapability ?l3 ; rdfs:label ?l2Label }}
    FILTER(
      CONTAINS(LCASE(?l3Label), "<term>") ||
      CONTAINS(LCASE(COALESCE(?l2Label, "")), "<term>")
    )
  }} ORDER BY ?l3Label ?techLabel LIMIT 100

Examples:
- "EA Standards for Database" → FILTER on capLabel containing "database"
- "Data Platforms" → FILTER on l3Label or l2Label containing "platform" AND ("data" in l2Label or l1Label)
- "Streaming tools" → FILTER on capLabel containing "stream"

- "Applications" = app:Application; link to capabilities via ea:enablesBusinessCapabilityL3.
- "People" / "employees" = hr:User; linked to departments via hr:belongsToDepartment.
- "Business capabilities" = ea:BusinessCapabilityL3 (L1/L2 for higher levels).
- "CSO / security capabilities" = ea:CSOCapabilityL3 (L1/L2 for higher levels).
- NEVER search on rdfs:label alone to find typed entities — always assert the rdf:type first.
- NEVER filter on ?techLabel to infer what a technology does — use capability labels instead.

RULES:
1. Use rdfs:label for human-readable names and text filtering unless the ontology explicitly requires another predicate.
2. Never use ea:name for user-facing filtering when rdfs:label is available.
3. Declare every prefix that appears in the query.
4. If a property appears in the ontology as a full IRI, you may use the full IRI directly.
5. Do not invent old or similar-looking terms like hr:managedBy, hr:Person, or hr:Employee unless they are explicitly in the ontology snapshot.
6. Always resolve named resources through rdfs:label and use case-insensitive CONTAINS on the exact term from the question.
7. Use OPTIONAL {{ }} only for genuinely nullable properties.
8. Do not inject classification filters unless ?classification is actually bound in the query.
9. Default LIMIT 100 unless the question implies COUNT, aggregation, or complete enumeration.
10. Return ONLY the SPARQL query — no markdown, no commentary.
11. STARDOG VARIABLE SCOPING — critical: a variable name must appear in exactly ONE scope.
    BANNED patterns (cause "Variable used when already in scope" error):
    - SELECT ?x ... WHERE {{ SELECT ?x ... }} — ?x appears in both outer and inner SELECT
    - SELECT (COUNT(?x) AS ?x) — alias name collides with an existing projection variable
    - Binding ?x in a subquery then also joining on ?x in the outer WHERE clause
    CORRECT pattern for subquery aggregation:
      SELECT ?app ?appLabel ?capCount WHERE {{
        {{ SELECT ?app (COUNT(DISTINCT ?cap) AS ?capCount) WHERE {{
             ?app a app:Application ; ea:enablesBusinessCapabilityL3 ?cap .
           }} GROUP BY ?app }}
        ?app rdfs:label ?appLabel .
      }} ORDER BY DESC(?capCount) LIMIT 100
    — the outer query fetches ?appLabel directly; the subquery only returns ?app and ?capCount.
"""

    logger.debug("nl_to_sparql: question=%r model=%s", question, settings.openai.sparql_model)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Generate SPARQL for: {question}"},
    ]

    try:
        resp = _chat_completion(settings.openai.sparql_model, messages, settings.openai.max_tokens)
    except Exception as exc:
        logger.warning(
            "Primary model %s failed (%s), falling back to gpt-4o",
            settings.openai.sparql_model,
            exc,
        )
        resp = _chat_completion("gpt-4o", messages, settings.openai.max_tokens)

    raw = _content(resp.choices[0].message).strip()
    logger.debug("nl_to_sparql raw output: %r", raw[:500])

    clean = _sanitise(raw)
    clean = _inject_missing_prefixes(clean)
    return clean


def _sanitise(raw: str) -> str:
    """Strip markdown fences, unwrap list strings, extract from first SPARQL keyword."""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip().strip("'\"")
        raw = inner

    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    upper = raw.upper()
    for kw in ("PREFIX", "SELECT", "ASK", "CONSTRUCT", "DESCRIBE", "INSERT", "DELETE"):
        idx = upper.find(kw)
        if idx != -1:
            raw = raw[idx:]
            break

    return raw.strip()


def _inject_missing_prefixes(query: str) -> str:
    """Prepend any missing PREFIX declarations for used prefixed names."""
    lines = query.splitlines()
    existing: set[str] = set()

    for line in lines:
        m = re.match(r"^\s*PREFIX\s+([A-Za-z_][A-Za-z0-9_-]*):", line, flags=re.IGNORECASE)
        if m:
            existing.add(m.group(1))

    used = set(_PREFIX_RE.findall(query))
    used -= {"http", "https", "urn"}

    missing = [p for p in sorted(used) if p in PREFIXES and p not in existing]
    if not missing:
        return query

    prefix_block = "\n".join(f"PREFIX {p}: <{PREFIXES[p]}>" for p in missing)
    return f"{prefix_block}\n{query}"
