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
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = int(os.getenv("ONTOLOGY_CACHE_TTL", "3600"))
_CLASS_LIMIT = int(os.getenv("ONTOLOGY_CLASS_LIMIT", "500"))
_PROPERTY_LIMIT = int(os.getenv("ONTOLOGY_PROPERTY_LIMIT", "500"))
_ONTOLOGY_BASES = (
    "http://example.com/",
    "http://nexus.enterprise.com/",
    "urn:EA_AI_Intelligence:",
)


@dataclass
class OntologyContext:
    classes_text: str = ""
    properties_text: str = ""
    sample_data_text: str = ""
    fetched_at: float = 0.0

    @property
    def full_text(self) -> str:
        parts = [
            f"Classes:\n{self.classes_text}",
            f"Properties:\n{self.properties_text}",
        ]
        if self.sample_data_text:
            parts.append(f"Sample instance values (use these exact labels/values in FILTER clauses):\n{self.sample_data_text}")
        return "\n\n".join(parts)

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.fetched_at) > _CACHE_TTL_SECONDS


_ctx  = OntologyContext()
_lock = threading.Lock()


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

    # Sample capability labels per key class — grounds the model on real values.
    # Query each class independently so one large class can't consume the full limit.
    _SAMPLE_CLASSES = [
        ("TechnologyCapabilityL1", "http://example.com/ea#TechnologyCapabilityL1"),
        ("TechnologyCapabilityL2", "http://example.com/ea#TechnologyCapabilityL2"),
        ("TechnologyCapabilityL3", "http://example.com/ea#TechnologyCapabilityL3"),
        ("BusinessCapabilityL1",   "http://example.com/ea#BusinessCapabilityL1"),
        ("BusinessCapabilityL2",   "http://example.com/ea#BusinessCapabilityL2"),
        ("BusinessCapabilityL3",   "http://example.com/ea#BusinessCapabilityL3"),
        ("CSOCapabilityL1",        "http://example.com/ea#CSOCapabilityL1"),
        ("CSOCapabilityL2",        "http://example.com/ea#CSOCapabilityL2"),
        ("CSOCapabilityL3",        "http://example.com/ea#CSOCapabilityL3"),
        ("EATechnologyDomain",     "http://example.com/ea#EATechnologyDomain"),
        ("Technology",             "http://example.com/ea#Technology"),
        ("Department",             "http://example.com/hr#Department"),
    ]

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

        # Sample labels from each key class independently
        sample_lines: list[str] = []
        for cls_name, cls_iri in _SAMPLE_CLASSES:
            q = f"""
            SELECT DISTINCT ?label WHERE {{
              ?inst a <{cls_iri}> ; rdfs:label ?label .
            }} ORDER BY ?label LIMIT 60
            """
            try:
                _, rows = db.to_rows(db.query(q))
                labels = [r.get("label", "") for r in rows]
                if labels:
                    sample_lines.append(
                        f"  {cls_name} rdfs:label values: {', '.join(repr(l) for l in labels)}"
                    )
            except Exception:
                pass

        _ctx.classes_text = "\n".join(classes) or "  (no classes found)"
        _ctx.properties_text = "\n".join(props) or "  (no properties found)"
        _ctx.sample_data_text = "\n".join(sample_lines)
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
        with _lock:
            if _ctx.is_stale:  # double-checked locking
                _fetch()
    return _ctx


def invalidate_ontology_cache() -> None:
    with _lock:
        _ctx.fetched_at = 0.0
    logger.info("Ontology cache invalidated — will re-fetch on next access.")
