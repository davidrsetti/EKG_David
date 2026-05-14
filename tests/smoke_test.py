#!/usr/bin/env python3
"""
NEXUS v2 EKG Platform — Smoke Test Suite
=========================================
Repeatable competency question (CQ) tests against the live Stardog graph
and the FastAPI REST layer.  Run this any time the code or model changes.

Usage (from /Users/drs58706/david/EKG_David/):
    python tests/smoke_test.py                          # run all tests
    python tests/smoke_test.py --category sparql        # SPARQL-only
    python tests/smoke_test.py --category api           # API-only
    python tests/smoke_test.py --category nl            # NL pipeline-only
    python tests/smoke_test.py --api http://localhost:8000 --timeout 60
    python tests/smoke_test.py --no-html --verbose

Categories
----------
  GRAPH      CQ-G  Graph population sanity (triple counts)
  PORTFOLIO  CQ-P  Application portfolio competency questions
  CAPABILITY CQ-C  EA business capability model competency
  PEOPLE     CQ-H  HR / people-graph competency
  AGENTS     CQ-A  AI agent registry competency
  INTEGRATE  CQ-I  Integration topology competency
  API        CQ-API FastAPI health endpoints
  NL         CQ-NL  End-to-end NL→SPARQL→answer pipeline
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

# ── Resolve repo root so 'nexus' package is importable via the symlink ───────
# Walk up from this file's directory until we find the 'nexus' symlink/dir.
def _find_repo_root() -> str:
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.exists(os.path.join(d, "nexus")):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = _find_repo_root()
sys.path.insert(0, REPO_ROOT)

import requests  # noqa: E402

# ── ANSI colours (disabled if not a TTY) ─────────────────────────────────────
_TTY = sys.stdout.isatty()
GREEN  = "\033[92m" if _TTY else ""
RED    = "\033[91m" if _TTY else ""
YELLOW = "\033[93m" if _TTY else ""
CYAN   = "\033[96m" if _TTY else ""
DIM    = "\033[2m"  if _TTY else ""
BOLD   = "\033[1m"  if _TTY else ""
RESET  = "\033[0m"  if _TTY else ""


# ══════════════════════════════════════════════════════════════════════════════
# DATA TYPES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TestResult:
    id:               str
    category:         str
    name:             str
    status:           str        # PASS | FAIL | ERROR | SKIP
    duration_ms:      int
    rows_returned:    int        # -1 = not applicable
    assertion_detail: str
    error_message:    str = ""
    sparql_used:      str = ""
    extra:            dict = field(default_factory=dict)


@dataclass
class TestCase:
    id:       str
    category: str
    name:     str
    fn:       Callable
    tags:     list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# TEST CONTEXT  (shared state passed into every test)
# ══════════════════════════════════════════════════════════════════════════════

class TestContext:
    def __init__(self, api_base: str, timeout: int, verbose: bool):
        self.api_base = api_base.rstrip("/")
        self.timeout  = timeout
        self.verbose  = verbose
        self._db      = None
        self._db_ok: bool | None = None

    def db(self):
        """Lazy-load Stardog client; return None if unavailable."""
        if self._db_ok is False:
            return None
        if self._db is None:
            try:
                from nexus.core.stardog_client import get_stardog
                self._db = get_stardog()
                self._db_ok = True
            except Exception as exc:
                print(f"  {YELLOW}[WARN] Stardog client unavailable: {exc}{RESET}")
                self._db_ok = False
        return self._db


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def sparql_count(ctx: TestContext, query: str) -> tuple[int, str]:
    """Run a COUNT(*) SPARQL query; return (count, error)."""
    db = ctx.db()
    if db is None:
        return -1, "Stardog unavailable"
    try:
        _, rows = db.to_rows(db.query(query, inject_prefixes=True))
        count = int(rows[0].get("count", 0)) if rows else 0
        return count, ""
    except Exception as exc:
        return -1, str(exc)


def sparql_rows(ctx: TestContext, query: str) -> tuple[list[dict], str]:
    """Run a SELECT SPARQL query; return (rows, error)."""
    db = ctx.db()
    if db is None:
        return [], "Stardog unavailable"
    try:
        _, rows = db.to_rows(db.query(query, inject_prefixes=True))
        return rows, ""
    except Exception as exc:
        return [], str(exc)


def api_get(ctx: TestContext, path: str) -> tuple[dict, int, str]:
    try:
        r = requests.get(f"{ctx.api_base}{path}", timeout=ctx.timeout)
        return r.json() if r.content else {}, r.status_code, ""
    except Exception as exc:
        return {}, 0, str(exc)


def api_post(ctx: TestContext, path: str, body: dict) -> tuple[dict, int, str]:
    try:
        r = requests.post(f"{ctx.api_base}{path}", json=body, timeout=ctx.timeout)
        return r.json() if r.content else {}, r.status_code, ""
    except Exception as exc:
        return {}, 0, str(exc)


def _result(tc: TestCase, passed: bool, ms: int, rows: int,
            detail: str, error: str = "", sparql: str = "",
            extra: dict | None = None) -> TestResult:
    status = "PASS" if passed else ("ERROR" if error else "FAIL")
    return TestResult(
        id=tc.id, category=tc.category, name=tc.name, status=status,
        duration_ms=ms, rows_returned=rows, assertion_detail=detail,
        error_message=error, sparql_used=sparql, extra=extra or {},
    )


# ══════════════════════════════════════════════════════════════════════════════
# CQ-G  GRAPH POPULATION (direct Stardog)
# ══════════════════════════════════════════════════════════════════════════════

def _g01(tc, ctx):
    """Total triple count is substantial (> 1 000)."""
    q = "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, c > 1000, ms, c, f"Triple count = {c:,} (expected > 1,000)", err, q)

def _g02(tc, ctx):
    """Applications exist in the graph (> 0)."""
    q = "SELECT (COUNT(*) AS ?count) WHERE { ?s a app:Application }"
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, c > 0, ms, c, f"app:Application = {c:,} (expected > 0)", err, q)

def _g03(tc, ctx):
    """Users exist in the graph (> 0)."""
    q = "SELECT (COUNT(*) AS ?count) WHERE { ?s a hr:User }"
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, c > 0, ms, c, f"hr:User = {c:,} (expected > 0)", err, q)

def _g04(tc, ctx):
    """Business capabilities (L3) exist in the graph (> 0)."""
    q = "SELECT (COUNT(*) AS ?count) WHERE { ?s a ea:BusinessCapabilityL3 }"
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, c > 0, ms, c, f"ea:BusinessCapabilityL3 = {c} (expected > 0)", err, q)

def _g05(tc, ctx):
    """AI agents are registered in the graph (≥ 1)."""
    q = "SELECT (COUNT(*) AS ?count) WHERE { ?s a ai:Agent }"
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, c >= 1, ms, c, f"ai:Agent = {c} (expected ≥ 1)", err, q)


# ══════════════════════════════════════════════════════════════════════════════
# CQ-P  APPLICATION PORTFOLIO (direct Stardog)
# ══════════════════════════════════════════════════════════════════════════════

def _p01(tc, ctx):
    """Applications expose environment metadata (app:environment, distinct values > 0)."""
    q = """
    SELECT DISTINCT ?env (COUNT(?app) AS ?n)
    WHERE { ?app a app:Application ; app:environment ?env }
    GROUP BY ?env ORDER BY DESC(?n) LIMIT 20
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    sample = ", ".join(r.get("env", "?") for r in rows[:5]) if rows else "—"
    return _result(tc, len(rows) > 0, ms, len(rows),
                   f"Environment values = {len(rows)} (sample: {sample})", err, q)

def _p02(tc, ctx):
    """Orphaned applications (no techOwner) are detectable."""
    q = """
    SELECT (COUNT(DISTINCT ?app) AS ?count)
    WHERE { ?app a app:Application . FILTER NOT EXISTS { ?app app:techOwner ?o } }
    """
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, c, f"Orphaned apps (no techOwner) = {c:,}", err, q)

def _p03(tc, ctx):
    """Decommission / legacy environment apps identifiable via app:environment."""
    q = """
    SELECT ?app ?appLabel ?env WHERE {
        ?app a app:Application ; app:environment ?env .
        OPTIONAL { ?app rdfs:label ?appLabel }
        FILTER(
            CONTAINS(LCASE(STR(?env)), "retire")      ||
            CONTAINS(LCASE(STR(?env)), "legacy")      ||
            CONTAINS(LCASE(STR(?env)), "sunset")      ||
            CONTAINS(LCASE(STR(?env)), "eol")         ||
            CONTAINS(LCASE(STR(?env)), "decommission")
        )
    } LIMIT 50
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, len(rows),
                   f"Decommission/legacy env apps = {len(rows)} (query executed)", err, q)

def _p04(tc, ctx):
    """Applications are linked to business capabilities (ea:enablesBusinessCapabilityL3)."""
    q = """
    SELECT (COUNT(DISTINCT ?app) AS ?count) WHERE {
        ?app a app:Application ; ea:enablesBusinessCapabilityL3 ?cap .
    }
    """
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, c,
                   f"Apps with capability linkage = {c:,} (query executed)", err, q)

def _p05(tc, ctx):
    """Application distribution by domain is queryable (returns rows)."""
    q = """
    SELECT ?domain (COUNT(?app) AS ?n) WHERE {
        ?app a app:Application .
        OPTIONAL { ?app ea:domain ?domain }
    } GROUP BY ?domain ORDER BY DESC(?n) LIMIT 20
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, len(rows) > 0, ms, len(rows),
                   f"Domain distribution rows = {len(rows)} (expected > 0)", err, q)


# ══════════════════════════════════════════════════════════════════════════════
# CQ-C  EA CAPABILITY MODEL (direct Stardog)
# ══════════════════════════════════════════════════════════════════════════════

def _c01(tc, ctx):
    """All L3 business capabilities are fully retrievable with labels."""
    q = """
    SELECT ?cap ?capLabel ?domain WHERE {
        ?cap a ea:BusinessCapabilityL3 .
        OPTIONAL { ?cap rdfs:label ?capLabel }
        OPTIONAL { ?cap ea:domain  ?domain   }
    } LIMIT 100
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, len(rows) > 0, ms, len(rows),
                   f"Capabilities retrieved = {len(rows)} (expected > 0)", err, q)

def _c02(tc, ctx):
    """Capability gaps (L3 with no supporting application) are detectable."""
    q = """
    SELECT (COUNT(?cap) AS ?count) WHERE {
        ?cap a ea:BusinessCapabilityL3 .
        FILTER NOT EXISTS { ?app ea:enablesBusinessCapabilityL3 ?cap }
    }
    """
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, c,
                   f"Capability gaps (no app) = {c} (query executed)", err, q)

def _c03(tc, ctx):
    """Capabilities with 2+ apps (rationalisation candidates) are detectable."""
    q = """
    SELECT ?cap ?capLabel (COUNT(DISTINCT ?app) AS ?n) WHERE {
        ?cap a ea:BusinessCapabilityL3 .
        OPTIONAL { ?cap rdfs:label ?capLabel }
        ?app ea:enablesBusinessCapabilityL3 ?cap .
    } GROUP BY ?cap ?capLabel HAVING(COUNT(DISTINCT ?app) >= 2)
    ORDER BY DESC(?n) LIMIT 20
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, len(rows),
                   f"Rationalisation candidates = {len(rows)} (query executed)", err, q)

def _c04(tc, ctx):
    """App-to-capability linkage traversal works end-to-end."""
    q = """
    SELECT ?app ?appLabel ?cap ?capLabel WHERE {
        ?app a app:Application ; ea:enablesBusinessCapabilityL3 ?cap .
        OPTIONAL { ?app rdfs:label ?appLabel }
        OPTIONAL { ?cap rdfs:label ?capLabel }
    } LIMIT 30
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, len(rows),
                   f"App→capability joins = {len(rows)} (query executed)", err, q)


# ══════════════════════════════════════════════════════════════════════════════
# CQ-H  PEOPLE / HR GRAPH (direct Stardog)
# ══════════════════════════════════════════════════════════════════════════════

def _h01(tc, ctx):
    """Users are linked to departments (hr:belongsToDepartment)."""
    q = """
    SELECT (COUNT(?u) AS ?count) WHERE {
        ?u a hr:User ; hr:belongsToDepartment ?dept .
    }
    """
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, c > 0, ms, c,
                   f"Users with dept linkage = {c:,} (expected > 0)", err, q)

def _h02(tc, ctx):
    """Departmental headcount is queryable (returns ranked list)."""
    q = """
    SELECT ?dept (COUNT(?u) AS ?n) WHERE {
        ?u a hr:User ; hr:belongsToDepartment ?dept .
    } GROUP BY ?dept ORDER BY DESC(?n) LIMIT 10
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, len(rows) > 0, ms, len(rows),
                   f"Top departments returned = {len(rows)} (expected > 0)", err, q)

def _h03(tc, ctx):
    """Application tech-ownership (app:techOwner) linkage is traversable."""
    q = """
    SELECT ?owner ?ownerLabel (COUNT(?app) AS ?n) WHERE {
        ?app a app:Application ; app:techOwner ?owner .
        OPTIONAL { ?owner rdfs:label ?ownerLabel }
    } GROUP BY ?owner ?ownerLabel ORDER BY DESC(?n) LIMIT 10
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, len(rows),
                   f"Owners with apps = {len(rows)} (query executed)", err, q)


# ══════════════════════════════════════════════════════════════════════════════
# CQ-I  INTEGRATION TOPOLOGY (direct Stardog)
# ══════════════════════════════════════════════════════════════════════════════

def _i01(tc, ctx):
    """App dependency graph (app:dependsOn) is traversable."""
    q = """
    SELECT (COUNT(*) AS ?count) WHERE {
        ?app a app:Application ; app:dependsOn ?dep .
    }
    """
    t0 = time.monotonic()
    c, err = sparql_count(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, c,
                   f"app:dependsOn triples = {c:,} (query executed)", err, q)

def _i02(tc, ctx):
    """Integration hotspots (highest outbound dependency count) are rankable."""
    q = """
    SELECT ?app ?appLabel (COUNT(DISTINCT ?dep) AS ?depCount) WHERE {
        ?app a app:Application .
        OPTIONAL { ?app rdfs:label ?appLabel }
        OPTIONAL { ?app app:dependsOn ?dep }
    } GROUP BY ?app ?appLabel ORDER BY DESC(?depCount) LIMIT 10
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, len(rows),
                   f"Top hotspots returned = {len(rows)} (query executed)", err, q)


# ══════════════════════════════════════════════════════════════════════════════
# CQ-A  AI AGENT REGISTRY (direct Stardog)
# ══════════════════════════════════════════════════════════════════════════════

def _a01(tc, ctx):
    """AI agent profiles with metadata are fully retrievable."""
    q = """
    SELECT ?agent ?name ?platform ?vendor ?riskTier WHERE {
        ?agent a ai:Agent .
        OPTIONAL { ?agent ai:name     ?name     }
        OPTIONAL { ?agent ai:platform ?platform }
        OPTIONAL { ?agent ai:vendor   ?vendor   }
        OPTIONAL { ?agent ai:riskTier ?riskTier }
    } LIMIT 50
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, len(rows) >= 1, ms, len(rows),
                   f"AI agent profiles = {len(rows)} (expected ≥ 1)", err, q)

def _a02(tc, ctx):
    """AI agents grouped by risk tier is queryable."""
    q = """
    SELECT ?riskTier (COUNT(?agent) AS ?n) WHERE {
        ?agent a ai:Agent .
        OPTIONAL { ?agent ai:riskTier ?riskTier }
    } GROUP BY ?riskTier ORDER BY ?riskTier
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, len(rows),
                   f"Risk-tier groups = {len(rows)} (query executed)", err, q)

def _a03(tc, ctx):
    """Agent-to-tool associations (ai:hasTool) are traversable."""
    q = """
    SELECT ?agent ?name ?tool WHERE {
        ?agent a ai:Agent .
        OPTIONAL { ?agent ai:name    ?name }
        OPTIONAL { ?agent ai:hasTool ?tool }
    } LIMIT 30
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, len(rows),
                   f"Agent-tool rows = {len(rows)} (query executed)", err, q)

def _a04(tc, ctx):
    """Agent ownership (ai:ownedBy) is traceable to users."""
    q = """
    SELECT ?agent ?name ?owner ?ownerLabel WHERE {
        ?agent a ai:Agent .
        OPTIONAL { ?agent ai:name    ?name       }
        OPTIONAL { ?agent ai:ownedBy ?owner .
                   ?owner rdfs:label ?ownerLabel }
    } LIMIT 30
    """
    t0 = time.monotonic()
    rows, err = sparql_rows(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    return _result(tc, err == "", ms, len(rows),
                   f"Agent-owner rows = {len(rows)} (query executed)", err, q)


# ══════════════════════════════════════════════════════════════════════════════
# CQ-API  FASTAPI HEALTH (REST)
# ══════════════════════════════════════════════════════════════════════════════

def _api01(tc, ctx):
    """Health endpoint responds with HTTP 200 and status = 'healthy'."""
    t0 = time.monotonic()
    body, code, err = api_get(ctx, "/v1/health/graph")
    ms = int((time.monotonic() - t0) * 1000)
    if err or code == 0:
        return _result(tc, False, ms, -1, "", f"HTTP error: {err or code}", "GET /v1/health/graph")
    status = body.get("status", "")
    passed = code == 200 and status == "healthy"
    return _result(tc, passed, ms, -1,
                   f"HTTP {code}, status={status!r} (expected 200, 'healthy')",
                   sparql="GET /v1/health/graph", extra=body.get("metrics", {}))

def _api02(tc, ctx):
    """Health metrics: total_triples > 1 000."""
    t0 = time.monotonic()
    body, code, err = api_get(ctx, "/v1/health/graph")
    ms = int((time.monotonic() - t0) * 1000)
    if err or code != 200:
        return _result(tc, False, ms, -1, "", f"HTTP {code}: {err}", "GET /v1/health/graph")
    triples = body.get("metrics", {}).get("total_triples", 0)
    passed  = isinstance(triples, int) and triples > 1000
    return _result(tc, passed, ms, -1,
                   f"total_triples = {triples:,} (expected > 1,000)",
                   sparql="GET /v1/health/graph")

def _api03(tc, ctx):
    """Health metrics: total_apps and total_people are both > 0."""
    t0 = time.monotonic()
    body, code, err = api_get(ctx, "/v1/health/graph")
    ms = int((time.monotonic() - t0) * 1000)
    if err or code != 200:
        return _result(tc, False, ms, -1, "", f"HTTP {code}: {err}", "GET /v1/health/graph")
    m      = body.get("metrics", {})
    apps   = m.get("total_apps", 0)
    people = m.get("total_people", 0)
    passed = isinstance(apps, int) and apps > 0 and isinstance(people, int) and people > 0
    return _result(tc, passed, ms, -1,
                   f"apps = {apps:,}, people = {people:,} (both expected > 0)",
                   sparql="GET /v1/health/graph")


# ══════════════════════════════════════════════════════════════════════════════
# CQ-NL  NL → SPARQL → ANSWER PIPELINE (end-to-end)
# ══════════════════════════════════════════════════════════════════════════════

def _nl(ctx, question):
    return api_post(ctx, "/v1/query", {"question": question})

def _nl01(tc, ctx):
    """'How many applications are in the portfolio?' returns a numeric answer."""
    q = "How many applications are in the portfolio?"
    t0 = time.monotonic()
    body, code, err = _nl(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    if err or code == 0:
        return _result(tc, False, ms, -1, "", f"HTTP error: {err or code}")
    if code != 200:
        return _result(tc, False, ms, -1, "", f"HTTP {code}: {body.get('detail', '')}")
    answer = body.get("answer", "")
    rows   = body.get("row_count", 0)
    has_num = bool(re.search(r"\d", answer))
    return _result(tc, has_num, ms, rows,
                   f"row_count={rows}, answer has number: {has_num}",
                   sparql=body.get("sparql", ""))

def _nl02(tc, ctx):
    """'List all AI agents' returns results without pipeline error."""
    q = "List all AI agents registered in the knowledge graph"
    t0 = time.monotonic()
    body, code, err = _nl(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    if err or code == 0:
        return _result(tc, False, ms, -1, "", f"HTTP error: {err or code}")
    if code != 200:
        return _result(tc, False, ms, -1, "", f"HTTP {code}: {body.get('detail', '')}")
    rows  = body.get("row_count", 0)
    error = body.get("error", "")
    return _result(tc, not error, ms, rows,
                   f"row_count={rows}, no pipeline error: {not bool(error)}",
                   sparql=body.get("sparql", ""))

def _nl03(tc, ctx):
    """'Which capabilities have no supporting application?' executes and answers."""
    q = "Which business capabilities have no supporting application?"
    t0 = time.monotonic()
    body, code, err = _nl(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    if err or code == 0:
        return _result(tc, False, ms, -1, "", f"HTTP error: {err or code}")
    if code != 200:
        return _result(tc, False, ms, -1, "", f"HTTP {code}: {body.get('detail', '')}")
    rows   = body.get("row_count", 0)
    error  = body.get("error", "")
    answer = body.get("answer", "")
    return _result(tc, not error and len(answer) > 10, ms, rows,
                   f"row_count={rows}, answer_chars={len(answer)}",
                   sparql=body.get("sparql", ""))

def _nl04(tc, ctx):
    """'Who are the top application owners?' returns a non-empty answer."""
    q = "Who are the top application owners by number of applications owned?"
    t0 = time.monotonic()
    body, code, err = _nl(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    if err or code == 0:
        return _result(tc, False, ms, -1, "", f"HTTP error: {err or code}")
    if code != 200:
        return _result(tc, False, ms, -1, "", f"HTTP {code}: {body.get('detail', '')}")
    rows   = body.get("row_count", 0)
    error  = body.get("error", "")
    answer = body.get("answer", "")
    return _result(tc, not error and len(answer) > 20, ms, rows,
                   f"row_count={rows}, answer_chars={len(answer)}",
                   sparql=body.get("sparql", ""))

def _nl05(tc, ctx):
    """'What departments exist and how many people are in each?' returns rows."""
    q = "What departments exist in the organisation and how many people are in each?"
    t0 = time.monotonic()
    body, code, err = _nl(ctx, q)
    ms = int((time.monotonic() - t0) * 1000)
    if err or code == 0:
        return _result(tc, False, ms, -1, "", f"HTTP error: {err or code}")
    if code != 200:
        return _result(tc, False, ms, -1, "", f"HTTP {code}: {body.get('detail', '')}")
    rows  = body.get("row_count", 0)
    error = body.get("error", "")
    return _result(tc, not error, ms, rows,
                   f"row_count={rows}, no pipeline error: {not bool(error)}",
                   sparql=body.get("sparql", ""))


# ══════════════════════════════════════════════════════════════════════════════
# TEST REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

ALL_TESTS: list[TestCase] = [
    # GRAPH
    TestCase("CQ-G01", "GRAPH",     "Total triple count > 1,000",                      _g01, ["sparql"]),
    TestCase("CQ-G02", "GRAPH",     "app:Application count > 0",                       _g02, ["sparql"]),
    TestCase("CQ-G03", "GRAPH",     "hr:User count > 0",                               _g03, ["sparql"]),
    TestCase("CQ-G04", "GRAPH",     "ea:BusinessCapabilityL3 count > 0",               _g04, ["sparql"]),
    TestCase("CQ-G05", "GRAPH",     "ai:Agent count ≥ 1",                              _g05, ["sparql"]),
    # PORTFOLIO
    TestCase("CQ-P01", "PORTFOLIO", "Apps expose environment metadata (app:environment)", _p01, ["sparql"]),
    TestCase("CQ-P02", "PORTFOLIO", "Orphaned apps (no techOwner) detectable",         _p02, ["sparql"]),
    TestCase("CQ-P03", "PORTFOLIO", "Legacy/sunset/EOL apps identifiable",             _p03, ["sparql"]),
    TestCase("CQ-P04", "PORTFOLIO", "Apps linked to capabilities via predicate",       _p04, ["sparql"]),
    TestCase("CQ-P05", "PORTFOLIO", "Portfolio distribution by domain queryable",      _p05, ["sparql"]),
    # CAPABILITY
    TestCase("CQ-C01", "CAPABILITY","All L3 capabilities retrievable with labels",     _c01, ["sparql"]),
    TestCase("CQ-C02", "CAPABILITY","Capability gaps (no app) detectable",             _c02, ["sparql"]),
    TestCase("CQ-C03", "CAPABILITY","Rationalisation candidates (2+ apps) detectable", _c03, ["sparql"]),
    TestCase("CQ-C04", "CAPABILITY","App→capability linkage traversal works",          _c04, ["sparql"]),
    # PEOPLE
    TestCase("CQ-H01", "PEOPLE",    "Users linked to departments",                     _h01, ["sparql"]),
    TestCase("CQ-H02", "PEOPLE",    "Departmental headcount queryable",                _h02, ["sparql"]),
    TestCase("CQ-H03", "PEOPLE",    "App tech-ownership linkage traversable",          _h03, ["sparql"]),
    # INTEGRATION
    TestCase("CQ-I01", "INTEGRATE", "app:dependsOn graph traversable",                _i01, ["sparql"]),
    TestCase("CQ-I02", "INTEGRATE", "Integration hotspots rankable by dependency",    _i02, ["sparql"]),
    # AGENTS
    TestCase("CQ-A01", "AGENTS",    "AI agent profiles with metadata retrievable",    _a01, ["sparql"]),
    TestCase("CQ-A02", "AGENTS",    "Agents grouped by risk tier queryable",          _a02, ["sparql"]),
    TestCase("CQ-A03", "AGENTS",    "Agent-to-tool associations traversable",         _a03, ["sparql"]),
    TestCase("CQ-A04", "AGENTS",    "Agent ownership traceable to users",             _a04, ["sparql"]),
    # API
    TestCase("CQ-API01", "API",     "Health endpoint: HTTP 200, status=healthy",      _api01, ["api"]),
    TestCase("CQ-API02", "API",     "Health metrics: total_triples > 1,000",          _api02, ["api"]),
    TestCase("CQ-API03", "API",     "Health metrics: apps > 0 and people > 0",        _api03, ["api"]),
    # NL PIPELINE
    TestCase("CQ-NL01", "NL",       "NL: 'How many applications?' → numeric answer",  _nl01, ["nl"]),
    TestCase("CQ-NL02", "NL",       "NL: 'List all AI agents' → no pipeline error",   _nl02, ["nl"]),
    TestCase("CQ-NL03", "NL",       "NL: 'Which capabilities have no app?' → answer", _nl03, ["nl"]),
    TestCase("CQ-NL04", "NL",       "NL: 'Top application owners?' → answer > 20 ch", _nl04, ["nl"]),
    TestCase("CQ-NL05", "NL",       "NL: 'Departments and headcount?' → no error",    _nl05, ["nl"]),
]

CATEGORY_TAGS = {
    "sparql": ["GRAPH", "PORTFOLIO", "CAPABILITY", "PEOPLE", "INTEGRATE", "AGENTS"],
    "api":    ["API"],
    "nl":     ["NL"],
}


# ══════════════════════════════════════════════════════════════════════════════
# TERMINAL REPORT
# ══════════════════════════════════════════════════════════════════════════════

_STATUS_COLOUR = {"PASS": GREEN, "FAIL": RED, "ERROR": YELLOW, "SKIP": DIM}

def _colour_status(s: str) -> str:
    return f"{_STATUS_COLOUR.get(s, '')}{s:<5}{RESET}"

def print_terminal_report(results: list[TestResult], elapsed: float) -> None:
    W = 120
    total = len(results)
    passed  = sum(1 for r in results if r.status == "PASS")
    failed  = sum(1 for r in results if r.status == "FAIL")
    errored = sum(1 for r in results if r.status == "ERROR")
    rate    = int(passed / total * 100) if total else 0
    colour  = GREEN if rate >= 90 else (YELLOW if rate >= 70 else RED)

    print()
    print(f"{BOLD}{'═' * W}{RESET}")
    print(f"{BOLD} NEXUS v2 EKG — Smoke Test Report   "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   "
          f"Pass rate: {colour}{passed}/{total} ({rate}%){RESET}{BOLD}{RESET}")
    print(f"{'═' * W}{RESET}")

    # Header row
    hdr = (f" {'ID':<10} {'Category':<11} {'Name':<48} {'Status':<7} "
           f"{'ms':>6} {'Rows':>7}  Detail")
    print(f"{DIM}{hdr}{RESET}")
    print(f"{DIM} {'─' * (W - 2)}{RESET}")

    for r in results:
        status_str = _colour_status(r.status)
        rows_str   = str(r.rows_returned) if r.rows_returned >= 0 else "—"
        name       = r.name[:46] + ".." if len(r.name) > 48 else r.name
        detail     = r.error_message or r.assertion_detail
        detail     = detail[:50] + ".." if len(detail) > 52 else detail
        print(f" {CYAN}{r.id:<10}{RESET} {r.category:<11} {name:<48} "
              f"{status_str} {r.duration_ms:>6}  {rows_str:>6}  {DIM}{detail}{RESET}")

    print(f"{DIM}{'─' * W}{RESET}")
    print(f"{BOLD} SUMMARY: {GREEN}{passed} PASS{RESET} | {RED}{failed} FAIL{RESET} | "
          f"{YELLOW}{errored} ERROR{RESET}    "
          f"Total runtime: {elapsed:.1f}s{RESET}")
    print(f"{'═' * W}{RESET}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT
# ══════════════════════════════════════════════════════════════════════════════

_HTML_STYLE = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0f172a;color:#e2e8f0;margin:0;padding:24px}
h1{color:#a78bfa;border-bottom:2px solid #7c3aed;padding-bottom:12px;margin:0 0 20px}
h2{color:#94a3b8;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin:0 0 12px}
.meta{color:#64748b;font-size:12px;margin:-14px 0 20px}
.summary{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}
.stat{background:#1e293b;border-radius:10px;padding:16px 22px;text-align:center;
  flex:1;min-width:110px;border:1px solid #334155}
.stat .lbl{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px}
.stat .val{font-size:30px;font-weight:700;margin-top:4px}
.val-rate{color:#a78bfa} .val-pass{color:#10b981} .val-fail{color:#ef4444}
.val-error{color:#f59e0b} .val-total{color:#60a5fa}
.progress{height:8px;background:#1e293b;border-radius:4px;margin:16px 0;overflow:hidden}
.progress-fill{height:100%;border-radius:4px;transition:width .4s;
  background:linear-gradient(90deg,#7c3aed,#10b981)}
.filters{margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap}
.fbtn{background:#1e293b;border:1px solid #334155;color:#94a3b8;
  padding:6px 18px;border-radius:20px;cursor:pointer;font-size:12px;
  transition:all .2s;font-family:inherit}
.fbtn:hover{border-color:#7c3aed;color:#a78bfa}
.fbtn.active{background:#7c3aed;border-color:#7c3aed;color:#fff}
table{width:100%;border-collapse:collapse;font-size:12.5px}
thead tr{background:#1e293b}
th{padding:10px 12px;text-align:left;color:#64748b;font-weight:600;
  text-transform:uppercase;font-size:10.5px;letter-spacing:.5px;
  border-bottom:2px solid #334155}
td{padding:8px 12px;border-bottom:1px solid #1e293b22;vertical-align:top}
tr:hover td{background:#1e293b55}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;
  font-size:11px;font-weight:700;letter-spacing:.3px}
.PASS{background:#064e3b30;color:#10b981;border:1px solid #10b98130}
.FAIL{background:#7f1d1d30;color:#ef4444;border:1px solid #ef444430}
.ERROR{background:#78350f30;color:#f59e0b;border:1px solid #f59e0b30}
.SKIP{background:#1e293b;color:#64748b;border:1px solid #33415530}
.cat{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;
  background:#1e293b;color:#a78bfa;border:1px solid #7c3aed30}
details{margin-top:4px}
summary{color:#60a5fa;cursor:pointer;font-size:11px;user-select:none;
  list-style:none;outline:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▶ ";font-size:9px;opacity:.7}
details[open] summary::before{content:"▼ "}
pre{background:#020617;border:1px solid #334155;border-radius:6px;padding:10px;
  font-size:11px;overflow-x:auto;color:#a5b4fc;margin:6px 0 0;
  white-space:pre-wrap;word-break:break-word;max-height:300px;overflow-y:auto}
.err-msg{color:#f87171;font-size:11px;margin-top:3px}
"""

_HTML_JS = """
function filter(status){
  document.querySelectorAll('.fbtn').forEach(b=>b.classList.remove('active'));
  document.getElementById('f'+status).classList.add('active');
  document.querySelectorAll('tr.row').forEach(r=>{
    r.style.display=(status==='ALL'||r.dataset.s===status)?'':'none';
  });
  document.getElementById('visible-count').textContent=
    document.querySelectorAll('tr.row:not([style*="none"])').length;
}
"""

def _esc(s: str) -> str:
    import html as _h
    return _h.escape(str(s))

def build_html_report(results: list[TestResult], elapsed: float,
                       run_ts: datetime) -> str:
    total   = len(results)
    passed  = sum(1 for r in results if r.status == "PASS")
    failed  = sum(1 for r in results if r.status == "FAIL")
    errored = sum(1 for r in results if r.status == "ERROR")
    rate    = round(passed / total * 100, 1) if total else 0

    rows_html = []
    for r in results:
        detail = _esc(r.error_message or r.assertion_detail)
        sparql = _esc(r.sparql_used) if r.sparql_used else ""
        sparql_block = (
            f"<details><summary>Query / Endpoint</summary><pre>{sparql}</pre></details>"
            if sparql else ""
        )
        err_block = (
            f'<div class="err-msg">⚠ {_esc(r.error_message)}</div>'
            if r.error_message else ""
        )
        rows_html.append(f"""
<tr class="row" data-s="{r.status}">
  <td><code style="color:#7dd3fc">{_esc(r.id)}</code></td>
  <td><span class="cat">{_esc(r.category)}</span></td>
  <td>{_esc(r.name)}</td>
  <td><span class="badge {r.status}">{r.status}</span></td>
  <td style="text-align:right;color:#94a3b8">{r.duration_ms}</td>
  <td style="text-align:right;color:#94a3b8">{"—" if r.rows_returned < 0 else r.rows_returned}</td>
  <td>{detail}{err_block}{sparql_block}</td>
</tr>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS Smoke Test — {run_ts.strftime('%Y-%m-%d %H:%M')}</title>
<style>{_HTML_STYLE}</style>
</head>
<body>
<h1>NEXUS v2 EKG — Smoke Test Report</h1>
<p class="meta">Run: {run_ts.strftime('%A %d %B %Y %H:%M:%S')} &nbsp;·&nbsp; Duration: {elapsed:.1f}s &nbsp;·&nbsp; {total} tests</p>

<div class="summary">
  <div class="stat"><div class="lbl">Pass rate</div><div class="val val-rate">{rate}%</div></div>
  <div class="stat"><div class="lbl">Total</div><div class="val val-total">{total}</div></div>
  <div class="stat"><div class="lbl">Passed</div><div class="val val-pass">{passed}</div></div>
  <div class="stat"><div class="lbl">Failed</div><div class="val val-fail">{failed}</div></div>
  <div class="stat"><div class="lbl">Errors</div><div class="val val-error">{errored}</div></div>
</div>

<div class="progress">
  <div class="progress-fill" style="width:{rate}%"></div>
</div>

<div class="filters">
  <button class="fbtn active" id="fALL"   onclick="filter('ALL')">All ({total})</button>
  <button class="fbtn" id="fPASS"  onclick="filter('PASS')">Pass ({passed})</button>
  <button class="fbtn" id="fFAIL"  onclick="filter('FAIL')">Fail ({failed})</button>
  <button class="fbtn" id="fERROR" onclick="filter('ERROR')">Error ({errored})</button>
</div>
<p style="color:#64748b;font-size:12px">Showing <span id="visible-count">{total}</span> of {total} tests</p>

<table>
<thead><tr>
  <th style="width:90px">ID</th>
  <th style="width:110px">Category</th>
  <th>Competency Question</th>
  <th style="width:70px">Status</th>
  <th style="width:60px;text-align:right">ms</th>
  <th style="width:60px;text-align:right">Rows</th>
  <th>Assertion / Detail</th>
</tr></thead>
<tbody>
{"".join(rows_html)}
</tbody>
</table>
<script>{_HTML_JS}</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_tests(tests: list[TestCase], ctx: TestContext) -> list[TestResult]:
    results = []
    for tc in tests:
        icon = "·"
        try:
            result = tc.fn(tc, ctx)
        except Exception as exc:
            result = TestResult(
                id=tc.id, category=tc.category, name=tc.name, status="ERROR",
                duration_ms=0, rows_returned=-1, assertion_detail="",
                error_message=f"Unhandled exception: {exc}",
            )
        results.append(result)
        col = _STATUS_COLOUR.get(result.status, "")
        print(f"  {icon} {CYAN}{result.id:<10}{RESET} "
              f"{col}{result.status:<5}{RESET}  {result.duration_ms:>5}ms  "
              f"{DIM}{(result.assertion_detail or result.error_message)[:70]}{RESET}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXUS EKG Smoke Test Suite")
    parser.add_argument("--api",        default="http://localhost:8000",
                        help="FastAPI base URL (default: http://localhost:8000)")
    parser.add_argument("--category",   default="all",
                        choices=["all", "sparql", "api", "nl"],
                        help="Test category filter")
    parser.add_argument("--timeout",    type=int, default=60,
                        help="Per-test timeout in seconds (default: 60)")
    parser.add_argument("--no-html",    action="store_true",
                        help="Skip HTML report generation")
    parser.add_argument("--report-dir", default=None,
                        help="Directory for HTML reports (default: tests/reports/)")
    parser.add_argument("--verbose",    action="store_true",
                        help="Show full SPARQL queries in terminal output")
    parser.add_argument("--skip-nl",    action="store_true",
                        help="Skip NL pipeline tests (useful when OpenAI is unreachable)")
    args = parser.parse_args()

    # Filter tests by category tag
    if args.category == "all":
        tests = ALL_TESTS
    else:
        allowed_cats = CATEGORY_TAGS.get(args.category, [])
        tests = [t for t in ALL_TESTS if t.category in allowed_cats]

    if args.skip_nl:
        tests = [t for t in tests if t.category != "NL"]

    ctx      = TestContext(api_base=args.api, timeout=args.timeout, verbose=args.verbose)
    run_ts   = datetime.now()
    n        = len(tests)
    cat_desc = args.category.upper() if args.category != "all" else "ALL CATEGORIES"

    print()
    print(f"{BOLD} NEXUS v2 EKG — Smoke Test Suite   "
          f"{run_ts.strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{DIM} {n} tests · {cat_desc} · API: {args.api}{RESET}")
    print(f"{DIM} {'─' * 80}{RESET}")
    print()

    t_start = time.monotonic()
    results = run_tests(tests, ctx)
    elapsed = time.monotonic() - t_start

    print_terminal_report(results, elapsed)

    if not args.no_html:
        report_dir = args.report_dir or os.path.join(
            os.path.dirname(__file__), "reports"
        )
        os.makedirs(report_dir, exist_ok=True)
        fname = f"smoke_{run_ts.strftime('%Y%m%d_%H%M%S')}.html"
        fpath = os.path.join(report_dir, fname)
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(build_html_report(results, elapsed, run_ts))
        print(f" {GREEN}HTML report saved:{RESET} {fpath}")
        print()

    # Exit code: non-zero if any FAIL or ERROR
    failures = sum(1 for r in results if r.status in ("FAIL", "ERROR"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
