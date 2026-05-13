"""
core/clarifier.py — Human-in-the-loop intent mapper.
Maps the user's question to the NEXUS ontology BEFORE any query executes.
Uses gpt-4o-mini (fast, low-cost) for this classification step.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field

from openai import OpenAI
from nexus.config.settings import settings
from nexus.config.ontology_prefixes import DOMAIN_HINTS
from nexus.core.ontology import get_ontology

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai.api_key)
    return _client


def _content(msg) -> str:
    c = msg.content if hasattr(msg, "content") else msg.get("content", "")
    if isinstance(c, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return str(c)


_COMPLETION_TOKEN_MODELS = {"o3-mini", "o3", "o1", "o1-mini", "o1-preview"}


def _token_param(model: str, n: int) -> dict:
    """Return the correct token-limit kwarg for the given model."""
    key = "max_completion_tokens" if model in _COMPLETION_TOKEN_MODELS else "max_tokens"
    return {key: n}


@dataclass
class ClarificationPlan:
    interpreted_intent:   str        = ""
    domains_involved:     list[str]  = field(default_factory=list)
    mapped_entities:      list[str]  = field(default_factory=list)
    mapped_relationships: list[str]  = field(default_factory=list)
    assumptions:          list[str]  = field(default_factory=list)
    clarifying_questions: list[str]  = field(default_factory=list)
    security_notes:       list[str]  = field(default_factory=list)
    ready_to_execute:     bool       = True
    confidence:           float      = 1.0   # 0.0–1.0

    def to_dict(self) -> dict:
        return {
            "interpreted_intent":   self.interpreted_intent,
            "domains_involved":     self.domains_involved,
            "mapped_entities":      self.mapped_entities,
            "mapped_relationships": self.mapped_relationships,
            "assumptions":          self.assumptions,
            "clarifying_questions": self.clarifying_questions,
            "security_notes":       self.security_notes,
            "ready_to_execute":     self.ready_to_execute,
            "confidence":           self.confidence,
        }


def clarify(question: str, user_role: str = "analyst") -> ClarificationPlan:
    """
    Analyse the user's question against the NEXUS ontology.
    Returns a ClarificationPlan that drives the human-in-the-loop UI step.
    """
    ont   = get_ontology()
    hints = "\n".join(f"  {k}: {v}" for k, v in DOMAIN_HINTS.items())

    system = f"""You are NEXUS, an Enterprise Knowledge Graph assistant.

Your job is to analyse a user's question and map it to the enterprise ontology
BEFORE any query is executed. This is a human-in-the-loop safety step.

DOMAIN VOCABULARY:
{hints}

ONTOLOGY SNAPSHOT:
{ont.full_text}

USER ROLE: {user_role}

Return a JSON object with EXACTLY these keys:
{{
  "interpreted_intent":   "<one precise sentence — what the user is really asking>",
  "domains_involved":     ["<domain name>", ...],
  "mapped_entities":      ["<OntologyClass or instance>", ...],
  "mapped_relationships": ["<property name>", ...],
  "assumptions":          ["<ambiguity resolved automatically>", ...],
  "clarifying_questions": ["<question to ask user if genuinely ambiguous>", ...],
  "security_notes":       ["<flag if query touches sensitive data or crosses permission boundaries>", ...],
  "ready_to_execute":     true | false,
  "confidence":           0.0 to 1.0
}}

Rules:
- ready_to_execute = false ONLY when clarifying_questions is non-empty AND
  the ambiguity would materially change the query result.
- Maximum 2 clarifying questions — only ask when genuinely necessary.
- security_notes should flag: PII access, Restricted data, cross-domain admin queries,
  queries about other users' access rights.
- confidence reflects how well the question maps to the known ontology.
- Return ONLY the JSON — no markdown fences, no preamble.
"""

    try:
        resp = _openai().chat.completions.create(
            model=settings.openai.clarify_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": f"Analyse this question: {question}"},
            ],
            temperature=0,
            **_token_param(settings.openai.clarify_model, 800),
        )
        raw = _content(resp.choices[0].message).strip()

        # Strip accidental fences
        if raw.startswith("```"):
            import re
            raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw).strip()

        data = json.loads(raw)
        return ClarificationPlan(**{k: data.get(k, v) for k, v in ClarificationPlan().__dict__.items()})

    except Exception as exc:
        logger.warning("clarify() failed: %s — returning pass-through plan", exc)
        return ClarificationPlan(
            interpreted_intent=question,
            ready_to_execute=True,
            confidence=0.5,
        )