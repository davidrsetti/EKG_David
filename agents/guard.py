"""
agents/guard.py — Responsible AI pre-flight check + security filter.

Two responsibilities:
  1. ResponsibleAI check — screen the user's question for harmful intent BEFORE
     any query is generated. Uses gpt-4o-mini (fast, cheap classification).

  2. SecurityFilter — given the authenticated user's role and clearance,
     produce SPARQL FILTER clauses that enforce row-level security. These are
     injected into the nl_to_sparql prompt so the LLM generates a compliant query.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from enum import Enum

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


# ── Risk levels ────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    BLOCKED  = "blocked"


@dataclass
class GuardResult:
    allowed:    bool
    risk_level: RiskLevel
    reason:     str
    flags:      list[str]

    @property
    def should_warn(self) -> bool:
        return self.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)


# ── Responsible AI pre-flight ──────────────────────────────────────────

_GUARD_SYSTEM = """You are a Responsible AI safety classifier for an enterprise knowledge graph.

Classify the user's question for risk. Return a JSON object:
{
  "allowed":    true | false,
  "risk_level": "low" | "medium" | "high" | "blocked",
  "reason":     "<one sentence>",
  "flags":      ["<flag>", ...]
}

BLOCK (allowed=false, risk_level="blocked") ONLY for these specific cases:
- Bulk credential exfiltration: asks for passwords, secrets, tokens, or API keys by name
- Mass PII dump: "export all", "dump all", "list every employee's" email/phone/salary/address
- Privilege escalation probe: asks which accounts have superuser, DBA, or root access
- Targeted harassment: asks about a named individual's protected characteristics
  (race, religion, gender, health, sexuality, age, disability) WITH apparent intent to discriminate
  — NOT simply asking about a person's role, manager, applications, or work assignments

DO NOT block standard enterprise lookups such as:
- "Who does [name] report to?"
- "What applications does [name] own?"
- "Show me [name]'s access certifications"
- "Which team is [name] on?"
- "List applications associated with business capabilities"
- Any query about org structure, app ownership, data lineage, or agent registrations

HIGH RISK (allowed=true, risk_level="high") when the question:
- Requests access certification status across ALL users simultaneously
- Asks for salary, compensation, or performance data for more than one person
- Crosses three or more security domains in a single query

MEDIUM RISK (allowed=true, risk_level="medium") when:
- Requests PII fields (email, phone) for a specific named person
- Queries AI agent permissions or security role assignments
- Asks about a single person's access grants or clearance level

LOW RISK (allowed=true, risk_level="low") everything else, including:
- Any question about applications, capabilities, data assets, or infrastructure
- Org-chart and reporting-line queries, even when a name is mentioned
- Agent registrations, findings, lineage, governance, or architecture queries

When in doubt, allow the query — row-level security and PII redaction downstream
will enforce data access controls. The guard's job is to block malicious intent,
not to second-guess legitimate business questions.

Return ONLY the JSON — no markdown, no preamble."""


def check_intent(question: str, user_role: str = "analyst") -> GuardResult:
    """
    Run the Responsible AI pre-flight check on a user's question.
    Call this BEFORE clarification or SPARQL generation.
    """
    try:
        resp = _openai().chat.completions.create(
            model=settings.openai.guard_model,
            messages=[
                {"role": "system", "content": _GUARD_SYSTEM},
                {"role": "user",   "content": f"User role: {user_role}\nQuestion: {question}"},
            ],
            temperature=0,
            **_token_param(settings.openai.guard_model, 300),
        )
        raw = _content(resp.choices[0].message).strip()

        import re
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

        data = json.loads(raw)
        return GuardResult(
            allowed    = bool(data.get("allowed", True)),
            risk_level = RiskLevel(data.get("risk_level", "low")),
            reason     = data.get("reason", ""),
            flags      = data.get("flags", []),
        )

    except Exception as exc:
        logger.warning("guard.check_intent() failed: %s — defaulting to allowed/low", exc)
        return GuardResult(allowed=True, risk_level=RiskLevel.LOW, reason="Guard check unavailable.", flags=[])


# ── Security filter (row-level security) ──────────────────────────────

# Maps role → what data classifications they can see
_CLASSIFICATION_CLEARANCE: dict[str, list[str]] = {
    "admin":        ["Public", "Internal", "Confidential", "Restricted"],
    "data-steward": ["Public", "Internal", "Confidential", "Restricted"],
    "analyst":      ["Public", "Internal"],
    "viewer":       ["Public"],
    "agent":        ["Public", "Internal"],           # AI agents default clearance
    "agent-admin":  ["Public", "Internal", "Confidential"],
}

# Maps role → HR domain scope (None = no restriction)
_HR_SCOPE: dict[str, str | None] = {
    "admin":        None,       # sees all people
    "data-steward": None,
    "analyst":      None,
    "viewer":       "own-dept", # can only see their own department
    "agent":        None,
    "agent-admin":  None,
}


@dataclass
class SecurityFilter:
    """
    Contains SPARQL FILTER clauses and result-level constraints for a role.
    Injected into nl_to_sparql and applied post-query.
    """
    allowed_classifications: list[str]
    sparql_data_filter: str    # injected into WHERE clause
    hr_scope: str | None       # None = no restriction
    max_rows: int


def build_security_filter(
    user_role: str,
    user_department: str = "",
    override_classification: list[str] | None = None,
) -> SecurityFilter:
    """
    Build row-level security filters for a given role.
    Called by the API auth layer before handing off to the query pipeline.
    """
    clearance = override_classification or _CLASSIFICATION_CLEARANCE.get(
        user_role, ["Public"]
    )
    hr_scope = _HR_SCOPE.get(user_role)

    # Build SPARQL filter for data classification
    if len(clearance) == 4:  # Admin sees all
        data_filter = ""
    else:
        vals = ", ".join(f'"{c}"' for c in clearance)
        data_filter = (
            f"FILTER(!BOUND(?classification) || ?classification IN ({vals}))"
        )

    # Additional HR scope filter — viewers without a department see nothing
    if hr_scope == "own-dept":
        if user_department:
            dept_filter = (
                f'\n  OPTIONAL {{ ?person hr:department ?dept }}'
                f'\n  FILTER(!BOUND(?dept) || STR(?dept) = "https://nexus.platform/ops#hr/{user_department}")'
            )
            data_filter = (data_filter + dept_filter).strip()
        else:
            # No department set: block all HR data for viewer role
            dept_filter = '\n  FILTER(false)'
            data_filter = (data_filter + dept_filter).strip()

    return SecurityFilter(
        allowed_classifications = clearance,
        sparql_data_filter      = data_filter,
        hr_scope                = hr_scope,
        max_rows                = settings.security.max_result_rows,
    )


# ── Agent-specific permission checker ─────────────────────────────────

@dataclass
class AgentPermissionResult:
    permitted:      bool
    agent_id:       str
    scope_matched:  bool
    policy_applied: str
    reason:         str


def check_agent_permission(
    agent_id: str,
    requested_domain: str,
    requested_classification: str,
) -> AgentPermissionResult:
    """
    Validate whether a named AI agent is permitted to access a given domain
    and data classification. Queries the NEXUS agent registry.
    """
    from nexus.agents.registry import get_agent_profile

    try:
        profile = get_agent_profile(agent_id)
        if profile is None:
            return AgentPermissionResult(
                permitted=False, agent_id=agent_id, scope_matched=False,
                policy_applied="deny-unknown-agent",
                reason=f"Agent '{agent_id}' is not registered in NEXUS.",
            )

        # Check domain scope
        scope_ok = (
            not profile.get("scopedDomains")  # no restriction = all domains
            or requested_domain in profile.get("scopedDomains", [])
        )

        # Check classification clearance
        agent_clearance = profile.get("clearanceLevel", "Internal")
        classification_rank = {"Public": 0, "Internal": 1, "Confidential": 2, "Restricted": 3}
        clearance_ok = (
            classification_rank.get(requested_classification, 99)
            <= classification_rank.get(agent_clearance, 1)
        )

        permitted = scope_ok and clearance_ok
        return AgentPermissionResult(
            permitted      = permitted,
            agent_id       = agent_id,
            scope_matched  = scope_ok,
            policy_applied = profile.get("policy", "default-agent-policy"),
            reason         = (
                "Permitted." if permitted
                else f"Denied: scope_ok={scope_ok}, clearance_ok={clearance_ok}, "
                     f"agent_clearance={agent_clearance}, requested={requested_classification}"
            ),
        )
    except Exception as exc:
        logger.error("check_agent_permission(%s) error: %s", agent_id, exc)
        return AgentPermissionResult(
            permitted=False, agent_id=agent_id, scope_matched=False,
            policy_applied="error-deny",
            reason=f"Permission check failed: {exc}",
        )