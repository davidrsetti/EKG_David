"""
core/ontology.py — Loads and caches ontology context from the graph.

This version fixes the next priority issues:
- includes both https://ontology.ea.example.org/ and urn:EA_AI_Intelligence: namespaces
- reads rdfs:domain/range plus schema.org domainIncludes/rangeIncludes
- emits richer prompt context including exact IRIs
- avoids dropping useful ontology terms outside the original base URI
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = int(os.getenv("ONTOLOGY_CACHE_TTL", "3600"))
_CLASS_LIMIT = int(os.getenv("ONTOLOGY_CLASS_LIMIT", "500"))
_PROPERTY_LIMIT = int(os.getenv("ONTOLOGY_PROPERTY_LIMIT", "500"))
_ONTOLOGY_BASES = (
    "https://ontology.ea.example.org/",
    "urn:EA_AI_Intelligence:",
)


@dataclass
class OntologyContext:
    classes_text: str = ""
    properties_text: str = ""
    fetched_at: float = 0.0

    @property
    def full_text(self) -> str:
        return f"Classes:\n{self.classes_text}\n\nProperties:\n{self.properties_text}"

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.fetched_at) > _CACHE_TTL_SECONDS


_ctx = OntologyContext()


def _uri_filter(var_name: str) -> str:
    return " || ".join(f'STRSTARTS(STR(?{var_name}), "{base}")' for base in _ONTOLOGY_BASES)


def _shorten(uri: str | None) -> str:
    if not uri:
        return "?"
    value = str(uri)
    if "#" in value:
        return value.rsplit("#", 1)[-1]
    if value.startswith("urn:"):
        return value.rsplit(":", 1)[-1]
    return value.rstrip("/").rsplit("/", 1)[-1]


def _fetch() -> None:
    from nexus.core.stardog_client import get_stardog

    db = get_stardog()

    class_q = f"""
    SELECT DISTINCT ?class ?label ?comment WHERE {{
        {{ ?class a owl:Class }} UNION {{ ?class a rdfs:Class }}
        FILTER({_uri_filter('class')})
        OPTIONAL {{ ?class rdfs:label ?label FILTER(LANG(?label) = "en" || LANG(?label) = "") }}
        OPTIONAL {{ ?class rdfs:comment ?comment FILTER(LANG(?comment) = "en" || LANG(?comment) = "") }}
    }}
    ORDER BY ?class
    LIMIT {_CLASS_LIMIT}
    """

    prop_q = f"""
    SELECT DISTINCT ?prop ?label ?domain ?range ?comment WHERE {{
        {{ ?prop a owl:ObjectProperty }} UNION {{ ?prop a owl:DatatypeProperty }}
        FILTER({_uri_filter('prop')})
        OPTIONAL {{ ?prop rdfs:label ?label FILTER(LANG(?label) = "en" || LANG(?label) = "") }}
        OPTIONAL {{
            {{ ?prop rdfs:domain ?domain }}
            UNION
            {{ ?prop <http://schema.org/domainIncludes> ?domain }}
        }}
        OPTIONAL {{
            {{ ?prop rdfs:range ?range }}
            UNION
            {{ ?prop <http://schema.org/rangeIncludes> ?range }}
        }}
        OPTIONAL {{ ?prop rdfs:comment ?comment FILTER(LANG(?comment) = "en" || LANG(?comment) = "") }}
    }}
    ORDER BY ?prop
    LIMIT {_PROPERTY_LIMIT}
    """

    try:
        _, class_rows = db.to_rows(db.query(class_q))
        _, prop_rows = db.to_rows(db.query(prop_q))

        classes: list[str] = []
        for r in class_rows:
            iri = r.get("class", "?")
            lbl = r.get("label") or _shorten(iri)
            cmt = r.get("comment", "")
            line = f"  - {lbl} <{iri}>"
            if cmt:
                line += f": {cmt}"
            classes.append(line)

        props: list[str] = []
        for r in prop_rows:
            iri = r.get("prop", "?")
            lbl = r.get("label") or _shorten(iri)
            dom = _shorten(r.get("domain"))
            rng = _shorten(r.get("range"))
            cmt = r.get("comment", "")
            line = f"  - {lbl} <{iri}> ({dom} → {rng})"
            if cmt:
                line += f": {cmt}"
            props.append(line)

        _ctx.classes_text = "\n".join(classes) or "  (no classes found)"
        _ctx.properties_text = "\n".join(props) or "  (no properties found)"
        _ctx.fetched_at = time.time()

        logger.info(
            "Ontology context refreshed: %d classes, %d properties (bases=%s)",
            len(classes),
            len(props),
            ", ".join(_ONTOLOGY_BASES),
        )
    except Exception as exc:
        logger.warning("Could not fetch ontology context: %s", exc)
        if not _ctx.classes_text:
            _ctx.classes_text = "  (ontology unavailable)"
            _ctx.properties_text = "  (ontology unavailable)"
            _ctx.fetched_at = time.time()


def get_ontology() -> OntologyContext:
    if _ctx.is_stale:
        _fetch()
    return _ctx


def invalidate_ontology_cache() -> None:
    _ctx.fetched_at = 0.0
    logger.info("Ontology cache invalidated — will re-fetch on next access.")
