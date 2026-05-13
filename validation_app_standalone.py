from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any

import pandas as pd
import requests
import streamlit as st
import sys

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
    
st.set_page_config(page_title="NEXUS SPARQL Validation Suite", layout="wide")

PREFIX_BLOCK = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX hr: <https://ontology.ea.example.org/hr#>
PREFIX ea: <https://ontology.ea.example.org/ea#>
PREFIX app: <https://ontology.ea.example.org/app#>
PREFIX sol: <https://ontology.ea.example.org/solution#>
PREFIX int: <https://ontology.ea.example.org/integration#>
PREFIX data: <https://ontology.ea.example.org/data#>
PREFIX gov: <https://ontology.ea.example.org/gov#>
PREFIX sec: <https://ontology.ea.example.org/security#>
PREFIX ai: <https://ontology.ea.example.org/ai#>
PREFIX agent: <https://ontology.ea.example.org/agent#>
PREFIX adv: <https://ontology.ea.example.org/advisor#>
PREFIX art: <https://ontology.ea.example.org/artifact#>
PREFIX nexus: <https://ontology.ea.example.org/nexus#>
PREFIX id: <https://ontology.ea.example.org/identity#>
PREFIX aiu: <urn:EA_AI_Intelligence:>
"""


@dataclass
class TestCase:
    suite: str
    test_id: str
    title: str
    query: str
    test_type: str = "select"
    expected_min_rows: int = 0
    severity: str = "warn"
    description: str = ""


@dataclass
class TestResult:
    suite: str
    test_id: str
    title: str
    status: str
    rows: int
    message: str
    elapsed_ms: int
    query: str
    sample: list[dict[str, Any]]


class StardogRunner:
    def __init__(self, endpoint: str, token: str, auth_scheme: str, verify_tls: bool, timeout: int):
        self.endpoint = endpoint.strip()
        self.token = token.strip()
        self.auth_scheme = auth_scheme.strip() or "Bearer"
        self.verify_tls = verify_tls
        self.timeout = timeout

    def _headers(self, accept: str = "application/sparql-results+json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "Content-Type": "application/sparql-query",
        }
        if self.token:
            headers["Authorization"] = f"{self.auth_scheme} {self.token}"
        return headers

    def run(self, query: str) -> tuple[dict[str, Any], int]:
        start = time.time()
        resp = requests.post(
            self.endpoint,
            data=query.encode("utf-8"),
            headers=self._headers(),
            verify=self.verify_tls,
            timeout=self.timeout,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        if not resp.ok:
            raise RuntimeError(f"Stardog HTTP {resp.status_code}: {resp.text[:1500]}")
        try:
            return resp.json(), elapsed_ms
        except Exception:
            raise RuntimeError(f"Non-JSON response from Stardog: {resp.text[:1500]}")


TESTS: list[TestCase] = [
    TestCase("Smoke", "SMOKE-01", "Database returns triples", f"{PREFIX_BLOCK}\nSELECT (COUNT(*) AS ?triples) WHERE {{ ?s ?p ?o . }}", expected_min_rows=1, severity="fail", description="Basic store sanity check."),
    TestCase("Smoke", "SMOKE-02", "Named graphs visible", f"{PREFIX_BLOCK}\nSELECT DISTINCT ?g WHERE {{ GRAPH ?g {{ ?s ?p ?o }} }} ORDER BY ?g LIMIT 100", expected_min_rows=0, description="Store / graph inventory."),
    TestCase("Smoke", "SMOKE-03", "Live manager predicate exists", f"{PREFIX_BLOCK}\nASK {{ aiu:manages_user a ?t . }}", test_type="ask", severity="fail", description="Protect against drift back to hr:managedBy."),
    TestCase("Smoke", "SMOKE-04", "Stale hr:managedBy usage check", f"{PREFIX_BLOCK}\nSELECT ?s ?o WHERE {{ ?s hr:managedBy ?o . }} LIMIT 20", expected_min_rows=0, description="Warn if stale predicate still has data or ontology triples."),
    TestCase("Smoke", "SMOKE-05", "Entities with ea:name but no rdfs:label", f"{PREFIX_BLOCK}\nSELECT ?s ?name WHERE {{ ?s ea:name ?name . FILTER NOT EXISTS {{ ?s rdfs:label ?label }} }} LIMIT 100", expected_min_rows=0, description="Rows that still need label backfill."),
    TestCase("Ontology", "ONT-01", "Ontology classes in enterprise namespaces", f"{PREFIX_BLOCK}\nSELECT DISTINCT ?class ?label WHERE {{ {{ ?class a owl:Class }} UNION {{ ?class a rdfs:Class }} FILTER(STRSTARTS(STR(?class), 'https://ontology.ea.example.org/') || STRSTARTS(STR(?class), 'urn:EA_AI_Intelligence:')) OPTIONAL {{ ?class rdfs:label ?label }} }} ORDER BY ?class LIMIT 300", expected_min_rows=1, severity="fail"),
    TestCase("Ontology", "ONT-02", "Properties missing domain or range", f"{PREFIX_BLOCK}\nSELECT DISTINCT ?prop ?label ?domain ?range WHERE {{ {{ ?prop a owl:ObjectProperty }} UNION {{ ?prop a owl:DatatypeProperty }} FILTER(STRSTARTS(STR(?prop), 'https://ontology.ea.example.org/') || STRSTARTS(STR(?prop), 'urn:EA_AI_Intelligence:')) OPTIONAL {{ ?prop rdfs:label ?label }} OPTIONAL {{ ?prop rdfs:domain ?domain }} OPTIONAL {{ ?prop rdfs:range ?range }} FILTER(!BOUND(?domain) || !BOUND(?range)) }} ORDER BY ?prop LIMIT 200", expected_min_rows=0),
    TestCase("Ontology", "ONT-03", "Properties still using schema.org domainIncludes/rangeIncludes", f"{PREFIX_BLOCK}\nSELECT DISTINCT ?prop ?label ?domain ?range WHERE {{ ?prop a ?ptype . FILTER(?ptype IN (owl:ObjectProperty, owl:DatatypeProperty)) OPTIONAL {{ ?prop rdfs:label ?label }} OPTIONAL {{ ?prop <http://schema.org/domainIncludes> ?domain }} OPTIONAL {{ ?prop <http://schema.org/rangeIncludes> ?range }} FILTER(BOUND(?domain) || BOUND(?range)) }} ORDER BY ?prop LIMIT 200", expected_min_rows=0),
    TestCase("HR", "HR-01", "Users discoverable by label", f"{PREFIX_BLOCK}\nSELECT ?user ?label WHERE {{ ?user a hr:User ; rdfs:label ?label . }} LIMIT 50", expected_min_rows=1, severity="fail", description="Smoke test question: can we find users by label?"),
    TestCase("HR", "HR-02", "Direct manager path uses live predicate", f"{PREFIX_BLOCK}\nSELECT ?manager ?managerLabel ?user ?userLabel WHERE {{ ?manager a hr:Manager ; aiu:manages_user ?user . OPTIONAL {{ ?manager rdfs:label ?managerLabel }} OPTIONAL {{ ?user rdfs:label ?userLabel }} }} LIMIT 50", expected_min_rows=1, description="Competency alignment for direct manager questions."),
    TestCase("HR", "HR-03", "Users without department", f"{PREFIX_BLOCK}\nSELECT ?user ?userLabel WHERE {{ ?user a hr:User ; rdfs:label ?userLabel . FILTER NOT EXISTS {{ ?user hr:hasDepartment ?dept }} }} LIMIT 100", expected_min_rows=0),
    TestCase("HR", "HR-04", "Departments and headcount", f"{PREFIX_BLOCK}\nSELECT ?deptLabel (COUNT(?user) AS ?headcount) WHERE {{ ?user a hr:User ; hr:hasDepartment ?dept . ?dept rdfs:label ?deptLabel . }} GROUP BY ?deptLabel ORDER BY DESC(?headcount) LIMIT 50", expected_min_rows=1),
    TestCase("EA / App", "EA-03", "L3 capabilities with no enabling app", f"{PREFIX_BLOCK}\nSELECT ?cap ?capLabel WHERE {{ ?cap a ea:BusinessCapabilityL3 . OPTIONAL {{ ?cap rdfs:label ?capLabel }} FILTER NOT EXISTS {{ ?app a app:Application ; ea:enablesBusinessCapability ?cap }} }} LIMIT 100", expected_min_rows=0, description="Competency question EA-03 from the catalog."),
    TestCase("EA / App", "APP-03", "Application lifecycle status inventory", f"{PREFIX_BLOCK}\nSELECT ?app ?appLabel ?lifecycle WHERE {{ ?app a app:Application . OPTIONAL {{ ?app rdfs:label ?appLabel }} OPTIONAL {{ ?app app:lifecycle ?lifecycle }} }} LIMIT 100", expected_min_rows=1, severity="fail", description="Competency question APP-03 from the catalog."),
    TestCase("EA / App", "APP-04", "Legacy / sunset / EOL applications", f"{PREFIX_BLOCK}\nSELECT ?appLabel ?lifecycle WHERE {{ ?app a app:Application ; rdfs:label ?appLabel . OPTIONAL {{ ?app app:lifecycle ?lifecycle }} FILTER(CONTAINS(LCASE(STR(?lifecycle)), 'retire') || CONTAINS(LCASE(STR(?lifecycle)), 'legacy') || CONTAINS(LCASE(STR(?lifecycle)), 'sunset') || CONTAINS(LCASE(STR(?lifecycle)), 'eol') || CONTAINS(LCASE(STR(?lifecycle)), 'end-of-life')) }} LIMIT 100", expected_min_rows=0),
    TestCase("EA / App", "APP-07", "Applications with no technical owner and no department owner", f"{PREFIX_BLOCK}\nSELECT ?app ?appLabel WHERE {{ ?app a app:Application . OPTIONAL {{ ?app rdfs:label ?appLabel }} FILTER NOT EXISTS {{ ?app app:techOwner ?owner }} FILTER NOT EXISTS {{ ?app app:ownedByDepartment ?dept }} }} LIMIT 100", expected_min_rows=0),
    TestCase("EA / App", "CROSS-APP-EA-02", "Applications enabling the most L3 capabilities", f"{PREFIX_BLOCK}\nSELECT ?appLabel (COUNT(DISTINCT ?cap) AS ?capabilityCount) WHERE {{ ?app a app:Application ; rdfs:label ?appLabel ; ea:enablesBusinessCapability ?cap . ?cap a ea:BusinessCapabilityL3 . }} GROUP BY ?appLabel ORDER BY DESC(?capabilityCount) LIMIT 25", expected_min_rows=0),
    TestCase("Data / AI", "DATA-10", "Datasets with no steward", f"{PREFIX_BLOCK}\nSELECT ?dataset ?label WHERE {{ ?dataset a data:Dataset . OPTIONAL {{ ?dataset rdfs:label ?label }} FILTER NOT EXISTS {{ ?dataset data:steward ?steward }} }} LIMIT 100", expected_min_rows=0),
    TestCase("Data / AI", "AI-12", "Agents with no governance policy", f"{PREFIX_BLOCK}\nSELECT ?agent ?label WHERE {{ ?agent a ai:Agent . OPTIONAL {{ ?agent rdfs:label ?label }} FILTER NOT EXISTS {{ ?agent ai:governedByPolicy ?policy }} }} LIMIT 100", expected_min_rows=0),
    TestCase("Data / AI", "OPS-03", "Critical findings still open", f"{PREFIX_BLOCK}\nSELECT ?finding ?severity ?status WHERE {{ ?finding a nexus:AgentFinding ; nexus:severity ?severity ; nexus:findingStatus ?status . FILTER(LCASE(STR(?severity)) = 'critical' && LCASE(STR(?status)) = 'open') }} LIMIT 100", expected_min_rows=0),
    TestCase("Data / AI", "CROSS-FULL-02", "At-risk L3 capabilities smoke check", f"{PREFIX_BLOCK}\nSELECT DISTINCT ?capLabel WHERE {{ ?cap a ea:BusinessCapabilityL3 ; rdfs:label ?capLabel . OPTIONAL {{ ?app a app:Application ; ea:enablesBusinessCapability ?cap ; rdfs:label ?appLabel . OPTIONAL {{ ?app app:lifecycle ?lifecycle }} }} OPTIONAL {{ ?solution sol:addressesCapability ?cap . }} OPTIONAL {{ ?dataset data:usedBySolution ?solution . FILTER NOT EXISTS {{ ?dataset data:steward ?steward }} }} FILTER( !BOUND(?app) || CONTAINS(LCASE(STR(?lifecycle)), 'legacy') || CONTAINS(LCASE(STR(?lifecycle)), 'sunset') || CONTAINS(LCASE(STR(?lifecycle)), 'retire') || !BOUND(?steward) ) }} LIMIT 100", expected_min_rows=0),
]


def payload_to_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "boolean" in payload:
        return [{"result": payload["boolean"]}]
    vars_ = payload.get("head", {}).get("vars", [])
    out = []
    for row in payload.get("results", {}).get("bindings", []):
        out.append({v: row.get(v, {}).get("value", "") for v in vars_})
    return out


def evaluate(test: TestCase, payload: dict[str, Any], elapsed_ms: int) -> TestResult:
    rows = payload_to_rows(payload)
    if test.test_type == "ask":
        ok = bool(payload.get("boolean", False))
        status = "PASS" if ok else ("FAIL" if test.severity == "fail" else "WARN")
        return TestResult(test.suite, test.test_id, test.title, status, 1 if ok else 0, "ASK returned true" if ok else "ASK returned false", elapsed_ms, test.query, rows)

    row_count = len(rows)
    if test.expected_min_rows == 0:
        # zero rows is good for anti-pattern checks
        if row_count == 0:
            status = "PASS"
            msg = "Returned 0 row(s) as expected"
        else:
            status = "FAIL" if test.severity == "fail" else "WARN"
            msg = f"Returned {row_count} row(s); expected 0"
    else:
        if row_count >= test.expected_min_rows:
            status = "PASS"
            msg = f"Returned {row_count} row(s)"
        else:
            status = "FAIL" if test.severity == "fail" else "WARN"
            msg = f"Returned {row_count} row(s), expected at least {test.expected_min_rows}"
    return TestResult(test.suite, test.test_id, test.title, status, row_count, msg, elapsed_ms, test.query, rows[:10])


def run_tests(runner: StardogRunner, tests: list[TestCase]) -> list[TestResult]:
    out = []
    for test in tests:
        try:
            payload, elapsed_ms = runner.run(test.query)
            out.append(evaluate(test, payload, elapsed_ms))
        except Exception as exc:
            out.append(TestResult(test.suite, test.test_id, test.title, "FAIL", 0, str(exc), 0, test.query, []))
    return out


def summary_df(results: list[TestResult]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "suite": r.suite,
            "test_id": r.test_id,
            "title": r.title,
            "status": r.status,
            "rows": r.rows,
            "elapsed_ms": r.elapsed_ms,
            "message": r.message,
        }
        for r in results
    ])


def main() -> None:
    st.title("NEXUS SPARQL Validation Suite")
    st.caption("Standalone app. No nexus package import required.")

    suites = sorted({t.suite for t in TESTS})
    with st.sidebar:
        st.header("Connection")
        endpoint = st.text_input("SPARQL endpoint", value=os.getenv("STARDOG_ENDPOINT", ""), placeholder="https://.../query")
        token = st.text_input("Token", value=os.getenv("STARDOG_TOKEN", ""), type="password")
        auth_scheme = st.text_input("Auth scheme", value=os.getenv("STARDOG_AUTH_SCHEME", "Bearer"))
        verify_tls = st.checkbox("Verify TLS", value=os.getenv("STARDOG_VERIFY_TLS", "false").lower() == "true")
        timeout = int(st.number_input("Timeout (seconds)", min_value=5, max_value=300, value=int(os.getenv("STARDOG_TIMEOUT", "30"))))
        selected_suites = st.multiselect("Suites", suites, default=suites)
        run_connection_test = st.button("Test connection", use_container_width=True)
        run_validation = st.button("Run validation", type="primary", use_container_width=True)

    tests = [t for t in TESTS if t.suite in selected_suites]

    st.subheader("Smoke test questions and checks")
    preview = pd.DataFrame([
        {
            "suite": t.suite,
            "test_id": t.test_id,
            "question / check": t.title,
            "description": t.description,
            "expected": f"0 rows" if t.test_type != "ask" and t.expected_min_rows == 0 else ("ASK = true" if t.test_type == "ask" else f">= {t.expected_min_rows} rows"),
            "severity": t.severity,
        }
        for t in tests
    ])
    st.dataframe(preview, width="stretch", hide_index=True)

    if run_connection_test:
        if not endpoint:
            st.error("Enter a Stardog /query endpoint first.")
        else:
            try:
                runner = StardogRunner(endpoint, token, auth_scheme, verify_tls, timeout)
                payload, elapsed_ms = runner.run(f"{PREFIX_BLOCK}\nSELECT (COUNT(*) AS ?triples) WHERE {{ ?s ?p ?o . }}")
                rows = payload_to_rows(payload)
                triples = rows[0].get("triples", "?") if rows else "?"
                st.success(f"Connected. Triple count returned in {elapsed_ms} ms: {triples}")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")

    if run_validation:
        if not endpoint:
            st.error("Enter a Stardog /query endpoint first.")
            return
        runner = StardogRunner(endpoint, token, auth_scheme, verify_tls, timeout)
        with st.spinner("Running validation suite..."):
            results = run_tests(runner, tests)

        df = summary_df(results)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Tests", len(results))
        col2.metric("Pass", int((df["status"] == "PASS").sum()))
        col3.metric("Warn", int((df["status"] == "WARN").sum()))
        col4.metric("Fail", int((df["status"] == "FAIL").sum()))

        st.subheader("Summary")
        st.dataframe(df, width="stretch", hide_index=True)
        st.download_button("Download summary CSV", df.to_csv(index=False).encode("utf-8"), file_name="nexus_validation_summary.csv", mime="text/csv")
        st.download_button("Download detailed JSON", json.dumps([asdict(r) for r in results], indent=2).encode("utf-8"), file_name="nexus_validation_results.json", mime="application/json")

        st.subheader("Details")
        for r in results:
            icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[r.status]
            with st.expander(f"{icon} {r.test_id} — {r.title} — {r.status}"):
                st.write(r.message)
                st.code(r.query, language="sparql")
                if r.sample:
                    st.dataframe(pd.DataFrame(r.sample), width="stretch", hide_index=True)
                else:
                    st.write("No sample rows")


if __name__ == "__main__":
    main()
