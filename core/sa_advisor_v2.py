from __future__ import annotations

"""
nexus.core.sa_advisor_v2 — Guided, ontology-driven Solutions Architecture Advisor

Key changes vs the original:
- Removes hardcoded ea:/app:/data:/intg:/ai:/adv: prefixed schema assumptions.
- Resolves classes and properties from the live ontology at runtime.
- Uses full IRIs in generated SPARQL to avoid undefined-prefix failures.
- Understands both rdfs:domain/range and schema.org domainIncludes/rangeIncludes.
- Fails soft when ontology terms are missing instead of inventing vocabulary.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from openai import OpenAI

from nexus.config.settings import settings

logger = logging.getLogger(__name__)
_client: OpenAI | None = None

RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SCHEMA = "http://schema.org/"

# Known ontology IRIs — used directly so list_business_domains never depends
# on _resolve_class successfully finding ea:EABusinessDomain at runtime.
EA_BASE                = "https://ontology.ea.example.org/ea#"
EA_BUSINESS_DOMAIN_IRI = f"{EA_BASE}EABusinessDomain"
EA_DOMAIN_PROP_IRI     = f"{EA_BASE}belongsToBusinessDomain"  # primary
EA_DOMAIN_PROP_ALT     = f"{EA_BASE}domain"                   # fallback

PREFIX_BLOCK = f"""PREFIX rdfs: <{RDFS}>
PREFIX owl:  <{OWL}>
PREFIX rdf:  <{RDF}>
PREFIX so:   <{SCHEMA}>
"""


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai.api_key)
    return _client


def _safe(v: Any) -> str:
    return str(v or "").replace("\\", "\\\\").replace('"', '\\"')



def _content(msg) -> str:
    c = msg.content if hasattr(msg, "content") else msg.get("content", "")
    if isinstance(c, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return str(c)



def _db():
    from nexus.core.stardog_client import get_stardog
    return get_stardog()


@dataclass
class BusinessContext:
    domain: str = ""
    capability_l1: str = ""
    capability_l2: str = ""
    capability_l3: str = ""
    business_goal: str = ""
    change_type: str = "Net-new"


@dataclass
class SourceContext:
    source_apps: list[str] = field(default_factory=list)
    source_data_products: list[str] = field(default_factory=list)
    source_integrations: list[str] = field(default_factory=list)
    existing_solutions: list[str] = field(default_factory=list)
    existing_platforms: list[str] = field(default_factory=list)
    existing_agents: list[str] = field(default_factory=list)
    narrative: str = ""


@dataclass
class FunctionalRequirements:
    narrative: str = ""
    actors: list[str] = field(default_factory=list)
    business_processes: list[str] = field(default_factory=list)
    app_capabilities: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    integrations_needed: list[str] = field(default_factory=list)


@dataclass
class NonFunctionalRequirements:
    narrative: str = ""
    security_level: str = "Internal"
    data_classification: str = "Internal"
    availability_target: str = ""
    latency_target: str = ""
    scale_profile: str = ""
    compliance_tags: list[str] = field(default_factory=list)
    cost_sensitivity: str = ""
    lifecycle_constraints: str = ""
    operating_model: str = ""


@dataclass
class GraphRecommendations:
    candidate_solution_categories: list[str] = field(default_factory=list)
    candidate_patterns: list[str] = field(default_factory=list)
    candidate_archetypes: list[str] = field(default_factory=list)
    candidate_platforms: list[str] = field(default_factory=list)
    candidate_technologies: list[str] = field(default_factory=list)
    related_architecture_rules: list[str] = field(default_factory=list)
    duplicate_risks: list[dict] = field(default_factory=list)
    capability_gaps: list[dict] = field(default_factory=list)
    tech_debt_warnings: list[dict] = field(default_factory=list)
    integration_hotspots: list[dict] = field(default_factory=list)
    data_risks: list[dict] = field(default_factory=list)
    existing_supporting_apps: list[dict] = field(default_factory=list)
    source_context_summary: list[dict] = field(default_factory=list)
    schema_summary: list[dict] = field(default_factory=list)


@dataclass
class AdvisorOutput:
    problem_statement: str = ""
    capability_context: str = ""
    existing_landscape: str = ""
    recommendation_narrative: str = ""
    options: list[dict] = field(default_factory=list)
    rationale: str = ""
    risks: list[str] = field(default_factory=list)
    roadmap: list[str] = field(default_factory=list)
    archimate_prompt: str = ""
    architecture_decision_record: str = ""


@dataclass
class GuidedSAState:
    business_context: BusinessContext = field(default_factory=BusinessContext)
    source_context: SourceContext = field(default_factory=SourceContext)
    functional_requirements: FunctionalRequirements = field(default_factory=FunctionalRequirements)
    non_functional_requirements: NonFunctionalRequirements = field(default_factory=NonFunctionalRequirements)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GuidedSAResult:
    state: GuidedSAState
    graph_recommendations: GraphRecommendations
    advisor_output: AdvisorOutput
    error: str | None = None


CHANGE_TYPES = ["Net-new", "Enhancement", "Replacement", "Rationalization", "Compliance"]
SECURITY_LEVELS = ["Public", "Internal", "Confidential", "Restricted"]
CLASSIFICATIONS = ["Public", "Internal", "Confidential", "Restricted"]
COST_SENSITIVITIES = ["Low", "Medium", "High"]
SCALE_PROFILES = ["Departmental", "Enterprise", "Global", "Burst / Campaign"]
AVAILABILITY_TARGETS = ["Best effort", "99.5%", "99.9%", "99.95%", "99.99%"]
LATENCY_TARGETS = ["Batch", "< 5 min", "< 30 sec", "< 5 sec", "Near real time"]
OPERATING_MODELS = ["Central platform team", "Federated product team", "Shared service", "Hybrid"]


@dataclass
class SchemaMap:
    business_capability_l1: str | None = None
    business_capability_l2: str | None = None
    business_capability_l3: str | None = None
    domain_class: str | None = None
    solution_category: str | None = None
    platform: str | None = None
    application: str | None = None
    data_product: str | None = None
    data_asset: str | None = None
    technology_capability: str | None = None
    technology: str | None = None
    tech_pattern: str | None = None
    tech_archetype: str | None = None
    architecture_rule: str | None = None
    integration: str | None = None
    agent: str | None = None
    finding: str | None = None

    domain_prop: str | None = None
    enables_business_capability: str | None = None
    requires_technology_capability: str | None = None
    addresses_business_capability: str | None = None
    uses_tech_archetype: str | None = None
    realizes_technology_capability: str | None = None
    runs_on_platform: str | None = None
    has_technology: str | None = None
    tech_owner: str | None = None
    lifecycle: str | None = None
    processes: str | None = None
    stores: str | None = None
    accesses: str | None = None
    classification: str | None = None
    has_source_system: str | None = None
    affects: str | None = None
    status: str | None = None
    severity: str | None = None


_SCHEMA_CACHE: SchemaMap | None = None


def _q(query: str) -> list[dict]:
    q = f"{PREFIX_BLOCK}\n{query.strip()}"
    _, rows = _db().to_rows(_db().query(q))
    return rows



def _run_rows(query: str) -> list[dict]:
    try:
        return _q(query)
    except Exception as exc:
        logger.warning("Guided SA query failed: %s", exc)
        return []



def _iri(iri: str) -> str:
    return f"<{iri}>"



def _union_selects(parts: list[str]) -> str:
    return "\nUNION\n".join(f"{{ {p} }}" for p in parts if p)



def _candidate_regex(candidates: list[str]) -> str:
    vals = [re.escape(c) for c in candidates if c]
    return "|".join(vals)



def _resolve_class(*candidates: str) -> str | None:
    regex = _candidate_regex(list(candidates))
    if not regex:
        return None
    q = f"""
    SELECT DISTINCT ?term ?label WHERE {{
      {{ ?term a owl:Class }} UNION {{ ?term a rdfs:Class }}
      OPTIONAL {{ ?term rdfs:label ?label FILTER(LANG(?label) = '' || LANG(?label) = 'en') }}
      BIND(REPLACE(STR(?term), '^.*(#|/)', '') AS ?local)
      FILTER(
        REGEX(LCASE(?local), '^(?:{regex.lower()})$') ||
        (BOUND(?label) && REGEX(LCASE(STR(?label)), '^(?:{regex.lower()})$'))
      )
    }}
    LIMIT 1
    """
    rows = _run_rows(q)
    return rows[0].get("term") if rows else None



def _resolve_property(*candidates: str) -> str | None:
    regex = _candidate_regex(list(candidates))
    if not regex:
        return None
    q = f"""
    SELECT DISTINCT ?term ?label WHERE {{
      {{ ?term a owl:ObjectProperty }} UNION {{ ?term a owl:DatatypeProperty }} UNION {{ ?term a rdf:Property }}
      OPTIONAL {{ ?term rdfs:label ?label FILTER(LANG(?label) = '' || LANG(?label) = 'en') }}
      BIND(REPLACE(STR(?term), '^.*(#|/)', '') AS ?local)
      FILTER(
        REGEX(LCASE(?local), '^(?:{regex.lower()})$') ||
        (BOUND(?label) && REGEX(LCASE(STR(?label)), '^(?:{regex.lower()})$'))
      )
    }}
    LIMIT 1
    """
    rows = _run_rows(q)
    return rows[0].get("term") if rows else None



def _get_schema() -> SchemaMap:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    s = SchemaMap(
        business_capability_l1=_resolve_class("BusinessCapabilityL1"),
        business_capability_l2=_resolve_class("BusinessCapabilityL2"),
        business_capability_l3=_resolve_class("BusinessCapabilityL3"),
        domain_class=_resolve_class("EABusinessDomain", "BusinessDomain", "Domain"),
        solution_category=_resolve_class("SolutionCategory"),
        platform=_resolve_class("Platform"),
        application=_resolve_class("Application"),
        data_product=_resolve_class("DataProduct"),
        data_asset=_resolve_class("DataAsset"),
        technology_capability=_resolve_class("TechnologyCapability", "TechnologyCapabilityL3", "TechnologyCapabilityL2", "TechnologyCapabilityL1"),
        technology=_resolve_class("Technology"),
        tech_pattern=_resolve_class("TechPattern", "TechnologyPattern", "IntegrationPattern"),
        tech_archetype=_resolve_class("TechArchetype", "TechnologyArchetype"),
        architecture_rule=_resolve_class("ArchitectureRule", "PolicyRule"),
        integration=_resolve_class("Integration"),
        agent=_resolve_class("Agent"),
        finding=_resolve_class("AgentFinding", "Finding"),
        domain_prop=_resolve_property("belongsToBusinessDomain", "domain", "businessDomain"),
        enables_business_capability=_resolve_property("enablesBusinessCapability"),
        requires_technology_capability=_resolve_property("requiresTechnologyCapability"),
        addresses_business_capability=_resolve_property("addressesBusinessCapability"),
        uses_tech_archetype=_resolve_property("usesTechArchetype"),
        realizes_technology_capability=_resolve_property("realizesTechnologyCapability"),
        runs_on_platform=_resolve_property("runsOnPlatform"),
        has_technology=_resolve_property("hasTechnology"),
        tech_owner=_resolve_property("techOwner", "owner"),
        lifecycle=_resolve_property("lifecycle", "status"),
        processes=_resolve_property("processes"),
        stores=_resolve_property("stores"),
        accesses=_resolve_property("accesses"),
        classification=_resolve_property("classification", "dataClassification"),
        has_source_system=_resolve_property("hasSourceSystem", "sourceSystem", "sourceApplication"),
        affects=_resolve_property("affects"),
        status=_resolve_property("status"),
        severity=_resolve_property("severity"),
    )
    _SCHEMA_CACHE = s
    return s



def invalidate_schema_cache() -> None:
    global _SCHEMA_CACHE
    _SCHEMA_CACHE = None
    logger.info("SA advisor schema cache invalidated.")



def _label_filter(var_name: str, value: str) -> str:
    if not value:
        return ""
    return f'FILTER(CONTAINS(LCASE(STR(?{var_name})), "{_safe(value.lower())}"))'



def _app_asset_path(schema: SchemaMap, app_var: str = "app", asset_var: str = "asset") -> str:
    props = [p for p in [schema.processes, schema.stores, schema.accesses] if p]
    if not props:
        return ""
    if len(props) == 1:
        return f"?{app_var} {_iri(props[0])} ?{asset_var} ."
    union = " | ".join(_iri(p) for p in props)
    return f"?{app_var} ({union}) ?{asset_var} ."



def _schema_summary(schema: SchemaMap) -> list[dict]:
    out: list[dict] = []
    for k, v in asdict(schema).items():
        if v:
            out.append({"term": k, "iri": v})
    return out



def list_business_domains(limit: int = 50) -> list[str]:
    """
    Query ea:EABusinessDomain instances directly using the known IRI.
    Falls back to walking BusinessCapabilityL3 -> domain_prop if the
    direct query returns nothing (e.g. data not yet loaded).
    """
    # ── Primary: query ea:EABusinessDomain directly ──────────────────
    q_direct = f"""
    SELECT DISTINCT ?label WHERE {{
      ?domain a <{EA_BUSINESS_DOMAIN_IRI}> .
      ?domain rdfs:label ?label .
    }} ORDER BY ?label LIMIT {limit}
    """
    rows = _run_rows(q_direct)
    vals = [r.get("label", "") for r in rows if r.get("label")]
    if vals:
        return vals

    # ── Fallback: resolve schema and walk capability -> domain ────────
    schema = _get_schema()
    if schema.business_capability_l3 and schema.domain_prop:
        q_walk = f"""
        SELECT DISTINCT ?domainLabel ?domain WHERE {{
          ?cap a {_iri(schema.business_capability_l3)} .
          ?cap {_iri(schema.domain_prop)} ?domain .
          OPTIONAL {{ ?domain rdfs:label ?domainLabel }}
        }} ORDER BY ?domainLabel LIMIT {limit}
        """
        rows = _run_rows(q_walk)
        vals = [r.get("domainLabel") or r.get("domain", "") for r in rows]
        return [v for v in vals if v]

    return []



def _resolve_domain_iri(domain_label: str) -> str | None:
    """
    Given a domain label (e.g. 'GFS'), return the IRI of the
    ea:EABusinessDomain node that has that label.
    """
    escaped = _safe(domain_label.lower())
    q = f"""
    SELECT ?domain WHERE {{
      ?domain a <{EA_BUSINESS_DOMAIN_IRI}> .
      ?domain rdfs:label ?label .
      FILTER(LCASE(STR(?label)) = "{escaped}")
    }} LIMIT 1
    """
    rows = _run_rows(q)
    return rows[0].get("domain") if rows else None


def search_capabilities(level: str = "L3", domain: str = "", search: str = "", limit: int = 100) -> list[str]:
    """
    Return capability labels for the given level, scoped to domain when supplied.

    Domain filtering strategy (in order):
    1. Resolve the domain label -> domain IRI via ea:EABusinessDomain
    2. Try cap -> domain via known predicates (belongsToBusinessDomain, domain)
    3. Try domain -> cap (reverse direction) via same predicates
    4. If no domain IRI found, fall back to CONTAINS label/URI match
    """
    schema = _get_schema()

    _EA_CAP = "https://ontology.ea.example.org/ea#"
    known_cap_iris = {
        "L1": f"{_EA_CAP}BusinessCapabilityL1",
        "L2": f"{_EA_CAP}BusinessCapabilityL2",
        "L3": f"{_EA_CAP}BusinessCapabilityL3",
    }
    lvl = level.upper()
    cap_iri = known_cap_iris.get(lvl) or {
        "L1": schema.business_capability_l1,
        "L2": schema.business_capability_l2,
        "L3": schema.business_capability_l3,
    }.get(lvl)
    if not cap_iri:
        return []

    search_filter = _label_filter("label", search)

    if domain:
        domain_iri = _resolve_domain_iri(domain)
        if domain_iri:
            # Use exact domain IRI — try both directions and both predicates
            domain_block = f"""
              {{
                {{ ?cap <{EA_DOMAIN_PROP_IRI}> <{domain_iri}> }}
                UNION
                {{ ?cap <{EA_DOMAIN_PROP_ALT}> <{domain_iri}> }}
                UNION
                {{ <{domain_iri}> <{EA_DOMAIN_PROP_IRI}> ?cap }}
                UNION
                {{ <{domain_iri}> <{EA_DOMAIN_PROP_ALT}> ?cap }}
                UNION
                {{ ?cap ?anyProp <{domain_iri}> . FILTER(?anyProp != rdf:type) }}
                UNION
                {{ <{domain_iri}> ?anyProp ?cap . FILTER(?anyProp != rdf:type) }}
              }}"""
        else:
            # Domain IRI not found — fall back to label/URI CONTAINS match
            escaped = _safe(domain.lower())
            domain_block = f"""
              {{
                {{ ?cap <{EA_DOMAIN_PROP_IRI}> ?domainNode }}
                UNION
                {{ ?cap <{EA_DOMAIN_PROP_ALT}> ?domainNode }}
              }}
              OPTIONAL {{ ?domainNode rdfs:label ?domainLabel }}
              FILTER(
                (BOUND(?domainLabel) && CONTAINS(LCASE(STR(?domainLabel)), "{escaped}")) ||
                CONTAINS(LCASE(STR(?domainNode)), "{escaped}")
              )"""
    else:
        domain_block = ""

    q = f"""
    SELECT DISTINCT ?label WHERE {{
      ?cap a <{cap_iri}> .
      ?cap rdfs:label ?label .
      {domain_block}
      {search_filter}
    }} ORDER BY ?label LIMIT {limit}
    """
    return [r.get("label", "") for r in _run_rows(q) if r.get("label")]



def search_applications(search: str = "", limit: int = 100) -> list[str]:
    schema = _get_schema()
    if not schema.application:
        return []
    search_filter = _label_filter("label", search)
    q = f"""
    SELECT DISTINCT ?label WHERE {{
      ?app a {_iri(schema.application)} .
      ?app rdfs:label ?label .
      {search_filter}
    }} ORDER BY ?label LIMIT {limit}
    """
    return [r.get("label", "") for r in _run_rows(q) if r.get("label")]



def search_platforms(search: str = "", limit: int = 100) -> list[str]:
    schema = _get_schema()
    if not schema.platform:
        return []
    search_filter = _label_filter("label", search)
    q = f"""
    SELECT DISTINCT ?label WHERE {{
      ?p a {_iri(schema.platform)} .
      ?p rdfs:label ?label .
      {search_filter}
    }} ORDER BY ?label LIMIT {limit}
    """
    return [r.get("label", "") for r in _run_rows(q) if r.get("label")]



def list_solution_categories(limit: int = 100) -> list[str]:
    schema = _get_schema()
    if not schema.solution_category:
        return []
    q = f"""
    SELECT DISTINCT ?label WHERE {{
      ?sc a {_iri(schema.solution_category)} .
      OPTIONAL {{ ?sc rdfs:label ?label }}
    }} ORDER BY ?label LIMIT {limit}
    """
    return [r.get("label", "") for r in _run_rows(q) if r.get("label")]



def search_data_products(search: str = "", limit: int = 100) -> list[str]:
    schema = _get_schema()
    if not schema.data_product:
        return []
    search_filter = _label_filter("label", search)
    q = f"""
    SELECT DISTINCT ?label WHERE {{
      ?dp a {_iri(schema.data_product)} .
      ?dp rdfs:label ?label .
      {search_filter}
    }} ORDER BY ?label LIMIT {limit}
    """
    return [r.get("label", "") for r in _run_rows(q) if r.get("label")]



def search_agents(search: str = "", limit: int = 100) -> list[str]:
    schema = _get_schema()
    if not schema.agent:
        return []
    search_filter = _label_filter("label", search)
    q = f"""
    SELECT DISTINCT ?label WHERE {{
      ?a a {_iri(schema.agent)} .
      ?a rdfs:label ?label .
      {search_filter}
    }} ORDER BY ?label LIMIT {limit}
    """
    return [r.get("label", "") for r in _run_rows(q) if r.get("label")]



def search_integrations(search: str = "", limit: int = 100) -> list[str]:
    schema = _get_schema()
    if not schema.integration:
        return []
    search_filter = _label_filter("label", search)
    q = f"""
    SELECT DISTINCT ?label WHERE {{
      ?i a {_iri(schema.integration)} .
      ?i rdfs:label ?label .
      {search_filter}
    }} ORDER BY ?label LIMIT {limit}
    """
    return [r.get("label", "") for r in _run_rows(q) if r.get("label")]



def enrich_guided_sa(state: GuidedSAState) -> GraphRecommendations:
    schema = _get_schema()
    domain = state.business_context.domain
    cap = state.business_context.capability_l3 or state.business_context.capability_l2 or state.business_context.capability_l1
    rec = GraphRecommendations(schema_summary=_schema_summary(schema))

    domain_join = f"OPTIONAL {{ ?cap {_iri(schema.domain_prop)} ?domain . OPTIONAL {{ ?domain rdfs:label ?domainLabel }} }}" if schema.domain_prop else ""
    domain_filter = _label_filter("domainLabel", domain) if schema.domain_prop and domain else ""
    cap_filter = _label_filter("capLabel", cap) if cap else ""

    if schema.business_capability_l3 and schema.application and schema.enables_business_capability:
        q_support = f"""
        SELECT DISTINCT ?capLabel ?appLabel ?lifecycle ?ownerLabel WHERE {{
          ?cap a {_iri(schema.business_capability_l3)} ; rdfs:label ?capLabel .
          {domain_join}
          ?app a {_iri(schema.application)} ; {_iri(schema.enables_business_capability)} ?cap .
          OPTIONAL {{ ?app rdfs:label ?appLabel }}
          {f'OPTIONAL {{ ?app {_iri(schema.lifecycle)} ?lifecycle }}' if schema.lifecycle else ''}
          {f'OPTIONAL {{ ?app {_iri(schema.tech_owner)} ?owner . ?owner rdfs:label ?ownerLabel }}' if schema.tech_owner else ''}
          {domain_filter}
          {cap_filter}
        }} ORDER BY ?appLabel LIMIT 50
        """
        rec.existing_supporting_apps = _run_rows(q_support)

    if schema.solution_category:
        optional_cap_join = ""
        if schema.addresses_business_capability:
            optional_cap_join = f"""
            OPTIONAL {{
              ?sc {_iri(schema.addresses_business_capability)} ?cap .
              ?cap rdfs:label ?capLabel .
            }}
            """
        optional_tc_join = ""
        if schema.requires_technology_capability:
            optional_tc_join = f"""
            OPTIONAL {{
              ?sc {_iri(schema.requires_technology_capability)} ?tc .
              OPTIONAL {{ ?tc rdfs:label ?technologyCapabilityLabel }}
            }}
            """
        q_solutions = f"""
        SELECT DISTINCT ?solutionCategoryLabel ?technologyCapabilityLabel WHERE {{
          ?sc a {_iri(schema.solution_category)} ; rdfs:label ?solutionCategoryLabel .
          {optional_cap_join}
          {optional_tc_join}
          {cap_filter}
        }} ORDER BY ?solutionCategoryLabel LIMIT 50
        """
        rows = _run_rows(q_solutions)
        rec.candidate_solution_categories = sorted({r.get("solutionCategoryLabel", "") for r in rows if r.get("solutionCategoryLabel")})
        rec.candidate_technologies = sorted({r.get("technologyCapabilityLabel", "") for r in rows if r.get("technologyCapabilityLabel")})

    if schema.solution_category or schema.tech_pattern:
        arch_join = ""
        if schema.solution_category and schema.addresses_business_capability and schema.uses_tech_archetype:
            arch_join = f"""
            OPTIONAL {{
              ?sc a {_iri(schema.solution_category)} ; rdfs:label ?solutionCategoryLabel .
              ?sc {_iri(schema.addresses_business_capability)} ?cap .
              ?cap rdfs:label ?capLabel .
              OPTIONAL {{ ?sc {_iri(schema.uses_tech_archetype)} ?arch . ?arch rdfs:label ?archetypeLabel }}
            }}
            """
        pat_join = ""
        if schema.tech_pattern and schema.realizes_technology_capability:
            pat_join = f"""
            OPTIONAL {{
              ?pattern a {_iri(schema.tech_pattern)} ;
                       {_iri(schema.realizes_technology_capability)} ?tc .
              OPTIONAL {{ ?pattern rdfs:label ?patternLabel }}
              OPTIONAL {{ ?tc rdfs:label ?technologyCapabilityLabel }}
            }}
            """
        q_patterns = f"""
        SELECT DISTINCT ?archetypeLabel ?patternLabel WHERE {{
          {arch_join}
          {pat_join}
          {cap_filter}
        }} LIMIT 100
        """
        rows = _run_rows(q_patterns)
        rec.candidate_archetypes = sorted({r.get("archetypeLabel", "") for r in rows if r.get("archetypeLabel")})
        rec.candidate_patterns = sorted({r.get("patternLabel", "") for r in rows if r.get("patternLabel")})

    app_filters = [_label_filter("appLabel", a) for a in state.source_context.source_apps[:5] if a]
    if schema.application and schema.platform and schema.runs_on_platform:
        if app_filters:
            union = _union_selects(app_filters)
            q_platforms = f"""
            SELECT DISTINCT ?appLabel ?platformLabel ?technologyLabel WHERE {{
              ?app a {_iri(schema.application)} ; rdfs:label ?appLabel .
              OPTIONAL {{ ?app {_iri(schema.runs_on_platform)} ?platform . ?platform rdfs:label ?platformLabel }}
              {f'OPTIONAL {{ ?platform {_iri(schema.has_technology)} ?technology . ?technology rdfs:label ?technologyLabel }}' if schema.has_technology else ''}
              {union}
            }} LIMIT 100
            """
        else:
            q_platforms = f"""
            SELECT DISTINCT ?platformLabel ?technologyLabel WHERE {{
              ?platform a {_iri(schema.platform)} ; rdfs:label ?platformLabel .
              {f'OPTIONAL {{ ?platform {_iri(schema.has_technology)} ?technology . ?technology rdfs:label ?technologyLabel }}' if schema.has_technology else ''}
            }} ORDER BY ?platformLabel LIMIT 40
            """
        rows = _run_rows(q_platforms)
        rec.candidate_platforms = sorted({r.get("platformLabel", "") for r in rows if r.get("platformLabel")})
        rec.candidate_technologies = sorted(set(rec.candidate_technologies) | {r.get("technologyLabel", "") for r in rows if r.get("technologyLabel")})

    if schema.architecture_rule:
        q_rules = f"""
        SELECT DISTINCT ?ruleLabel WHERE {{
          ?rule a {_iri(schema.architecture_rule)} .
          OPTIONAL {{ ?rule rdfs:label ?ruleLabel }}
        }} ORDER BY ?ruleLabel LIMIT 30
        """
        rec.related_architecture_rules = [r.get("ruleLabel", "") for r in _run_rows(q_rules) if r.get("ruleLabel")]

    if schema.business_capability_l3 and schema.application and schema.enables_business_capability:
        q_gaps = f"""
        SELECT ?capLabel ?domainLabel WHERE {{
          ?cap a {_iri(schema.business_capability_l3)} ; rdfs:label ?capLabel .
          {domain_join}
          FILTER NOT EXISTS {{ ?app {_iri(schema.enables_business_capability)} ?cap }}
          {domain_filter}
        }} LIMIT 20
        """
        rec.capability_gaps = _run_rows(q_gaps)

    if schema.application:
        lifecycle_join = f'OPTIONAL {{ ?app {_iri(schema.lifecycle)} ?lifecycle }}' if schema.lifecycle else ''
        platform_join = f'OPTIONAL {{ ?app {_iri(schema.runs_on_platform)} ?platform . ?platform rdfs:label ?platformLabel }}' if schema.runs_on_platform else ''
        q_td = f"""
        SELECT ?appLabel ?lifecycle ?platformLabel WHERE {{
          ?app a {_iri(schema.application)} ; rdfs:label ?appLabel .
          {lifecycle_join}
          {platform_join}
          OPTIONAL {{ ?app {_iri(schema.domain_prop)} ?domain . OPTIONAL {{ ?domain rdfs:label ?domainLabel }} }}
          FILTER(
            CONTAINS(LCASE(STR(?lifecycle)), "retire") ||
            CONTAINS(LCASE(STR(?lifecycle)), "legacy") ||
            CONTAINS(LCASE(STR(?lifecycle)), "eol") ||
            CONTAINS(LCASE(STR(?lifecycle)), "sunset")
          )
          {domain_filter if schema.domain_prop else ''}
        }} LIMIT 20
        """
        rec.tech_debt_warnings = _run_rows(q_td)

    if schema.business_capability_l3 and schema.application and schema.enables_business_capability:
        q_dupes = f"""
        SELECT ?capLabel (COUNT(DISTINCT ?app) AS ?appCount) WHERE {{
          ?cap a {_iri(schema.business_capability_l3)} ; rdfs:label ?capLabel .
          ?app a {_iri(schema.application)} ; {_iri(schema.enables_business_capability)} ?cap .
          {domain_join}
          {domain_filter}
        }} GROUP BY ?capLabel HAVING(COUNT(DISTINCT ?app) >= 2)
        ORDER BY DESC(?appCount) LIMIT 15
        """
        rec.duplicate_risks = _run_rows(q_dupes)

    if schema.application and schema.integration and schema.has_source_system:
        q_hotspots = f"""
        SELECT ?appLabel (COUNT(DISTINCT ?integration) AS ?integrationCount) WHERE {{
          ?app a {_iri(schema.application)} ; rdfs:label ?appLabel .
          OPTIONAL {{ ?integration a {_iri(schema.integration)} ; {_iri(schema.has_source_system)} ?app }}
          {f'OPTIONAL {{ ?app {_iri(schema.domain_prop)} ?domain . OPTIONAL {{ ?domain rdfs:label ?domainLabel }} }}' if schema.domain_prop else ''}
          {domain_filter if schema.domain_prop else ''}
        }} GROUP BY ?appLabel ORDER BY DESC(?integrationCount) LIMIT 15
        """
        rec.integration_hotspots = _run_rows(q_hotspots)

    asset_path = _app_asset_path(schema)
    if schema.application and asset_path and schema.classification:
        finding_join = ""
        if schema.finding and schema.affects:
            finding_join = f"""
            OPTIONAL {{
              ?finding a {_iri(schema.finding)} ; {_iri(schema.affects)} ?app .
              {f'?finding {_iri(schema.status)} ?status .' if schema.status else ''}
              {f'FILTER(?status != "Resolved")' if schema.status else ''}
              OPTIONAL {{ ?finding rdfs:label ?findingLabel }}
              {f'OPTIONAL {{ ?finding {_iri(schema.severity)} ?severity }}' if schema.severity else ''}
            }}
            """
        q_datarisk = f"""
        SELECT DISTINCT ?appLabel ?classification ?findingLabel ?severity WHERE {{
          ?app a {_iri(schema.application)} ; rdfs:label ?appLabel .
          {asset_path}
          ?asset {_iri(schema.classification)} ?classification .
          FILTER(?classification IN ("Restricted", "Confidential"))
          {finding_join}
          {f'OPTIONAL {{ ?app {_iri(schema.domain_prop)} ?domain . OPTIONAL {{ ?domain rdfs:label ?domainLabel }} }}' if schema.domain_prop else ''}
          {domain_filter if schema.domain_prop else ''}
        }} LIMIT 20
        """
        rec.data_risks = _run_rows(q_datarisk)

    summaries: list[dict] = []
    for app_label in state.source_context.source_apps[:5]:
        if not (schema.application and app_label):
            continue
        q = f"""
        SELECT ?appLabel ?ownerLabel ?lifecycle ?platformLabel ?classification WHERE {{
          ?app a {_iri(schema.application)} ; rdfs:label ?appLabel .
          {_label_filter('appLabel', app_label)}
          {f'OPTIONAL {{ ?app {_iri(schema.tech_owner)} ?owner . ?owner rdfs:label ?ownerLabel }}' if schema.tech_owner else ''}
          {f'OPTIONAL {{ ?app {_iri(schema.lifecycle)} ?lifecycle }}' if schema.lifecycle else ''}
          {f'OPTIONAL {{ ?app {_iri(schema.runs_on_platform)} ?platform . ?platform rdfs:label ?platformLabel }}' if schema.runs_on_platform else ''}
          {f'OPTIONAL {{ {_app_asset_path(schema)} ?asset {_iri(schema.classification)} ?classification . }}' if _app_asset_path(schema) and schema.classification else ''}
        }} LIMIT 3
        """
        summaries.extend(_run_rows(q))
    rec.source_context_summary = summaries
    return rec


_GUIDED_SA_SYSTEM = """You are a principal enterprise architect and solutions architect.

You are given:
1. A guided architecture interview
2. Graph-enriched enterprise context
3. A schema summary that reflects the live ontology used to ground the graph queries

Return ONLY valid JSON with EXACTLY these keys:
{
  "problem_statement": "<2-3 sentences>",
  "capability_context": "<2-3 sentences>",
  "existing_landscape": "<2-4 sentences summarising current estate>",
  "recommendation_narrative": "<4-6 sentences, decisive, specific, grounded in the graph>",
  "options": [
    {
      "name": "<short option name>",
      "summary": "<what it is>",
      "fit": "<why it fits>",
      "risks": ["<risk>", "..."],
      "recommended_platforms": ["<platform>", "..."],
      "recommended_patterns": ["<pattern>", "..."],
      "recommended_technologies": ["<technology>", "..."],
      "estimated_complexity": "Low|Medium|High"
    }
  ],
  "rationale": "<why the preferred option is preferred>",
  "risks": ["<risk>", "..."],
  "roadmap": ["<step>", "..."],
  "architecture_decision_record": "<ADR-style decision summary>"
}

Rules:
- Maximum 3 options
- Prefer reuse of existing enterprise assets where practical
- Call out tech debt, duplicate risk, policy constraints, data risk, and integration hot spots if relevant
- Recommendation must clearly reflect the interview and the graph signals
- Be direct and specific
- Do not invent enterprise assets that are not present in the graph summary
"""



def synthesise_guided_sa(state: GuidedSAState, graph_rec: GraphRecommendations) -> AdvisorOutput:
    payload = {
        "interview": state.to_dict(),
        "graph_recommendations": asdict(graph_rec),
    }
    try:
        resp = _openai().chat.completions.create(
            model=settings.openai.answer_model,
            messages=[
                {"role": "system", "content": _GUIDED_SA_SYSTEM},
                {"role": "user", "content": json.dumps(payload, indent=2)},
            ],
            temperature=0.2,
            max_tokens=3000,
        )
        raw = _content(resp.choices[0].message).strip()
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("guided SA synthesis failed: %s", exc)
        data = {
            "problem_statement": f"Improve {state.business_context.capability_l3 or state.business_context.business_goal or 'the selected business area'} with governed reuse of existing enterprise assets.",
            "capability_context": f"Domain: {state.business_context.domain or 'unspecified'}. Change type: {state.business_context.change_type}.",
            "existing_landscape": f"{len(graph_rec.existing_supporting_apps)} supporting applications and {len(graph_rec.candidate_platforms)} candidate platforms were found in the graph.",
            "recommendation_narrative": "Use a capability-led, graph-grounded design that prioritises reuse of current platforms, minimises duplication, and explicitly addresses identified data and lifecycle risks.",
            "options": [],
            "rationale": "Preference is given to options that reuse governed platforms and reduce integration and data risk.",
            "risks": ["Graph coverage may be incomplete for some domains."],
            "roadmap": ["Confirm scope", "Validate source applications", "Select preferred platform/pattern", "Generate target architecture", "Create ADR and delivery backlog"],
            "architecture_decision_record": "Decision: proceed with a graph-grounded target architecture assessment and platform reuse first.",
        }

    out = AdvisorOutput(
        problem_statement=data.get("problem_statement", ""),
        capability_context=data.get("capability_context", ""),
        existing_landscape=data.get("existing_landscape", ""),
        recommendation_narrative=data.get("recommendation_narrative", ""),
        options=data.get("options", []) or [],
        rationale=data.get("rationale", ""),
        risks=data.get("risks", []) or [],
        roadmap=data.get("roadmap", []) or [],
        architecture_decision_record=data.get("architecture_decision_record", ""),
    )
    out.archimate_prompt = build_archimate_prompt(state, graph_rec, out)
    return out



def build_archimate_prompt(state: GuidedSAState, graph_rec: GraphRecommendations, output: AdvisorOutput) -> str:
    return f"""
Create an ArchiMate target architecture for:
Business domain: {state.business_context.domain}
Business capability: {state.business_context.capability_l3 or state.business_context.capability_l2 or state.business_context.capability_l1}
Business goal: {state.business_context.business_goal}
Change type: {state.business_context.change_type}

Source applications: {", ".join(state.source_context.source_apps) or "None provided"}
Existing platforms: {", ".join(state.source_context.existing_platforms or graph_rec.candidate_platforms[:4]) or "Not specified"}
Source data products: {", ".join(state.source_context.source_data_products) or "Not specified"}
Existing agents: {", ".join(state.source_context.existing_agents) or "None"}

Functional requirements:
{state.functional_requirements.narrative}

Non-functional requirements:
{state.non_functional_requirements.narrative}

Preferred patterns: {", ".join(graph_rec.candidate_patterns[:5]) or "Use best-fit enterprise patterns"}
Candidate platforms: {", ".join(graph_rec.candidate_platforms[:5]) or "Use best-fit enterprise platforms"}
Candidate technologies: {", ".join(graph_rec.candidate_technologies[:6]) or "Use best-fit enterprise technologies"}

Recommendation:
{output.recommendation_narrative}

Risks:
{"; ".join(output.risks)}

Build a target-state diagram across Motivation, Business, Application, and Technology layers with clear traceability from business goal to services, applications, and enabling platform/technology.
""".strip()



def run_guided_sa(state: GuidedSAState) -> GuidedSAResult:
    try:
        graph_rec = enrich_guided_sa(state)
        output = synthesise_guided_sa(state, graph_rec)
        return GuidedSAResult(state=state, graph_recommendations=graph_rec, advisor_output=output)
    except Exception as exc:
        logger.exception("run_guided_sa failed")
        return GuidedSAResult(
            state=state,
            graph_recommendations=GraphRecommendations(),
            advisor_output=AdvisorOutput(),
            error=str(exc),
        )
