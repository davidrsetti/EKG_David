"""
core/answer_engine.py — Synthesises SPARQL results into structured NL answers.
Uses gpt-4o or Claude Sonnet for nuanced, three-part responses.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass

from openai import OpenAI
from nexus.config.settings import settings

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
class AnswerResult:
    answer:       str
    sparql:       str
    columns:      list[str]
    rows:         list[dict]
    row_count:    int
    error:        str | None
    pii_detected: bool = False
    redacted:     bool = False


SYSTEM_PROMPT = """You are NEXUS, a precise enterprise knowledge graph assistant.

Answer the user's question using the SPARQL results provided.
Structure your response in EXACTLY THREE sections using these headers:

**Direct Answer**
Clear, concise answer in plain English. Highlight key entities, counts, and relationships.
Use bullet points for lists of 4 or more items.

**Reasoning & Explanation**
Explain which parts of the enterprise knowledge model were traversed to derive this answer.
Call out notable patterns, relationships, or gaps (e.g. missing stewards, orphaned applications).
If the result implies a risk or compliance concern, say so plainly.

**Confidence & Caveats**
State your confidence in the answer (High / Medium / Low).
Note any assumptions, empty OPTIONAL fields, partial data coverage, or reasons the answer
could be incomplete. If the result is complete and unambiguous, state that clearly.

Write in professional, direct prose. Do NOT mention SPARQL, graph queries, or technical details
unless explicitly asked. Numbers and entity names should be precise — never paraphrase facts."""


def synthesise(
    question: str,
    columns: list[str],
    rows: list[dict],
    sparql: str,
    total_count: int,
) -> str:
    """
    Generate a structured natural language answer from SPARQL results.
    Returns the formatted answer string.
    """
    if not rows:
        return (
            "**Direct Answer**\n"
            f"No results were found for: _{question}_\n\n"
            "**Reasoning & Explanation**\n"
            "The query executed successfully but returned zero matching records. "
            "This could mean: the entities don't exist in the graph yet, the relationships "
            "are modelled differently, or the data has not been synchronised from the source system.\n\n"
            "**Confidence & Caveats**\n"
            "High confidence that the query is correct; low confidence that 'no data' is the "
            "true answer — it may reflect incomplete graph coverage. "
            "Consider checking the source system directly or reviewing the ontology mappings."
        )

    preview = json.dumps(rows[:30], indent=2)
    shown   = min(30, len(rows))

    try:
        resp = _openai().chat.completions.create(
            model=settings.openai.answer_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": (
                    f"Question: {question}\n\n"
                    f"Result columns: {', '.join(columns)}\n"
                    f"Total results: {total_count} (showing first {shown})\n\n"
                    f"Results:\n{preview}"
                )},
            ],
            temperature=0.2,
            **_token_param(settings.openai.answer_model, settings.openai.max_tokens),
        )
        return _content(resp.choices[0].message).strip()

    except Exception as exc:
        logger.error("answer_engine.synthesise() failed: %s", exc)
        # Graceful degradation — return a plain summary
        return (
            f"**Direct Answer**\n"
            f"Found {total_count} result(s) for: _{question}_\n\n"
            f"**Reasoning & Explanation**\n"
            f"Results contain columns: {', '.join(columns)}. "
            f"The answer synthesis model was unavailable — raw results are shown in the table below.\n\n"
            f"**Confidence & Caveats**\n"
            f"Data is accurate; narrative explanation unavailable due to a model error: {exc}"
        )