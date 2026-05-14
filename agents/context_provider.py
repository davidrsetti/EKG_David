"""
agents/context_provider.py — Builds rich context bundles for AI agent consumption.

When an agent calls GET /v1/context?entity=X, this module:
1. Resolves the entity in the graph
2. Fetches its 2-hop neighbourhood (related entities)
3. Fetches applicable policies and regulations
4. Fetches any open agent findings affecting it
5. Returns a structured bundle the agent can act on
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ContextBundle:
    entity_uri:       str
    entity_label:     str
    entity_type:      str
    domain:           str
    classification:   str
    owner:            str
    steward:          str
    policies:         list[dict] = field(default_factory=list)
    regulations:      list[str]  = field(default_factory=list)
    related_entities: list[dict] = field(default_factory=list)
    open_findings:    list[dict] = field(default_factory=list)
    lineage_upstream: list[dict] = field(default_factory=list)
    access_grants:    list[dict] = field(default_factory=list)
    error:            str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def get_context(entity_name: str, requesting_agent: str = "") -> ContextBundle:
    """
    Build a full context bundle for a named entity.
    Used by AI agents and orchestrators before acting on enterprise data.
    """
    from nexus.core.stardog_client import get_stardog
    db = get_stardog()

    # ── Step 1: Resolve entity ────────────────────────────────────
    resolve_q = f"""
    SELECT ?entity ?label ?type ?domain ?classification ?owner ?ownerLabel ?steward ?stewardLabel WHERE {{
        ?entity rdfs:label ?label .
        FILTER(CONTAINS(LCASE(STR(?label)), "{entity_name.lower()}"))
        OPTIONAL {{ ?entity a ?type }}
        OPTIONAL {{ ?entity ea:domain ?domain }}
        OPTIONAL {{ ?entity data:classification ?classification }}
        OPTIONAL {{ ?entity app:techOwner ?owner . ?owner rdfs:label ?ownerLabel }}
        OPTIONAL {{ ?entity data:owner    ?owner . ?owner rdfs:label ?ownerLabel }}
        OPTIONAL {{ ?entity data:steward  ?steward . ?steward rdfs:label ?stewardLabel }}
    }} LIMIT 1
    """

    try:
        _, rows = db.to_rows(db.query(resolve_q))
        if not rows:
            return ContextBundle(
                entity_uri="", entity_label=entity_name, entity_type="",
                domain="", classification="", owner="", steward="",
                error=f"Entity '{entity_name}' not found in NEXUS graph.",
            )

        r = rows[0]
        entity_uri   = r.get("entity", "")
        entity_label = r.get("label", entity_name)
        entity_type  = r.get("type",  "").split("#")[-1].split("/")[-1]
        domain       = r.get("domain", "").split("#")[-1].split("/")[-1]

    except Exception as exc:
        return ContextBundle(
            entity_uri="", entity_label=entity_name, entity_type="",
            domain="", classification="", owner="", steward="",
            error=str(exc),
        )

    # ── Step 2: Policies & Regulations ───────────────────────────
    policies, regulations = [], []
    try:
        pol_q = f"""
        SELECT ?policy ?policyLabel ?regulation WHERE {{
            <{entity_uri}> (data:regulatedBy|gov:governedBy|sec:policy) ?policy .
            OPTIONAL {{ ?policy rdfs:label ?policyLabel }}
            OPTIONAL {{ ?policy a gov:Regulation . BIND(STR(?policy) AS ?regulation) }}
        }} LIMIT 20
        """
        _, pol_rows = db.to_rows(db.query(pol_q, inject_prefixes=True))
        for pr in pol_rows:
            if pr.get("policyLabel"):
                policies.append({"label": pr["policyLabel"], "uri": pr.get("policy", "")})
            if pr.get("regulation"):
                regulations.append(pr["regulation"].split("#")[-1].split("/")[-1])
    except Exception:
        pass

    # ── Step 3: 2-hop neighbourhood ───────────────────────────────
    related = []
    try:
        nbr_q = f"""
        SELECT DISTINCT ?rel ?relLabel ?neighbour ?neighbourLabel ?neighbourType WHERE {{
            {{ <{entity_uri}> ?rel ?neighbour }}
            UNION
            {{ ?neighbour ?rel <{entity_uri}> }}
            ?neighbour rdfs:label ?neighbourLabel .
            OPTIONAL {{ ?neighbour a ?neighbourType }}
            OPTIONAL {{ ?rel rdfs:label ?relLabel }}
            FILTER(?neighbour != <{entity_uri}>)
            FILTER(!isLiteral(?neighbour))
        }} LIMIT 30
        """
        _, nbr_rows = db.to_rows(db.query(nbr_q, inject_prefixes=False))
        for nr in nbr_rows:
            related.append({
                "relationship": nr.get("relLabel") or nr.get("rel", "").split("#")[-1].split("/")[-1],
                "entity":       nr.get("neighbourLabel", ""),
                "type":         nr.get("neighbourType", "").split("#")[-1].split("/")[-1],
            })
    except Exception:
        pass

    # ── Step 4: Open agent findings ──────────────────────────────
    findings = []
    try:
        find_q = f"""
        SELECT ?finding ?findingLabel ?severity ?status ?foundBy ?foundByLabel ?foundAt WHERE {{
            ?finding a nexus:AgentFinding ;
                     nexus:affects       <{entity_uri}> ;
                     nexus:findingStatus ?status .
            FILTER(?status != "Resolved")
            OPTIONAL {{ ?finding rdfs:label      ?findingLabel }}
            OPTIONAL {{ ?finding nexus:severity  ?severity     }}
            OPTIONAL {{ ?finding nexus:foundAt   ?foundAt      }}
            OPTIONAL {{ ?finding nexus:foundBy   ?foundBy .
                        ?foundBy rdfs:label      ?foundByLabel }}
        }} ORDER BY DESC(?foundAt) LIMIT 10
        """
        _, find_rows = db.to_rows(db.query(find_q))
        findings = find_rows
    except Exception:
        pass

    # ── Step 5: Access grants (who can access this entity) ────────
    access = []
    try:
        acc_q = f"""
        SELECT ?person ?personLabel ?role ?roleLabel ?certifiedOn ?certificationDue WHERE {{
            ?role sec:grantsAccessTo <{entity_uri}> .
            ?grant sec:role ?role .
            ?grant sec:grantedTo ?person .
            ?person rdfs:label ?personLabel .
            OPTIONAL {{ ?role  rdfs:label    ?roleLabel      }}
            OPTIONAL {{ ?grant sec:lastCertified   ?certifiedOn    }}
            OPTIONAL {{ ?grant sec:certificationDue ?certificationDue }}
        }} LIMIT 20
        """
        _, acc_rows = db.to_rows(db.query(acc_q))
        access = acc_rows
    except Exception:
        pass

    return ContextBundle(
        entity_uri       = entity_uri,
        entity_label     = entity_label,
        entity_type      = entity_type,
        domain           = domain,
        classification   = r.get("classification", ""),
        owner            = r.get("ownerLabel", ""),
        steward          = r.get("stewardLabel", ""),
        policies         = policies,
        regulations      = list(set(regulations)),
        related_entities = related,
        open_findings    = findings,
        lineage_upstream = [],  # populated by lineage module if needed
        access_grants    = access,
    )
