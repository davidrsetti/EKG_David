# NEXUS v2.1 — Ontology Alignment Guide
## `enterprise_complete_no_orphans_v2.ttl` (v7.0.0) → Code

---

## HOW TO APPLY THESE CHANGES

### Step 1 — Load the TTL patch into Stardog
```bash
# Load both files into the same Stardog database
stardog data add --named-graph "https://ontology.ea.example.org/" \
  nexus enterprise_complete_no_orphans_v2.ttl

stardog data add --named-graph "https://nexus.platform/ops" \
  nexus enterprise_nexus_operations_patch.ttl
```

### Step 2 — Replace config file
```
nexus/config/ontology_prefixes.py  ← ontology_prefixes.py (from this delivery)
```

### Step 3 — Replace SPARQL strings in each module
Use the strings in `sparql_corrections.py` as drop-in replacements.
Each section is labelled with its target file.

### Step 4 — Update BASE constants in findings.py and session.py
```python
# findings.py
BASE      = "https://nexus.platform/ops#"        # was http://nexus.enterprise.com/
AGENT_URI = "https://ontology.ea.example.org/ai#" # for agent URIs

# session.py
SESSION = "https://nexus.platform/ops#"           # was http://nexus.enterprise.com/session#
```

### Step 5 — Run validation
```bash
stardog query nexus "SELECT (COUNT(*) AS ?c) WHERE { ?s a ai:Agent }"
stardog query nexus "SELECT (COUNT(*) AS ?c) WHERE { ?s a app:Application }"
stardog query nexus "SELECT (COUNT(*) AS ?c) WHERE { ?s a ea:BusinessCapabilityL3 }"
```

---

## FULL GAP ANALYSIS

### Category 1 — CRITICAL: Namespace URI changes (everything breaks without these)

| Component | Old URI | New URI |
|-----------|---------|---------|
| HR domain | `http://nexus.enterprise.com/hr#` | `https://ontology.ea.example.org/hr#` |
| App domain | `http://nexus.enterprise.com/app#` | `https://ontology.ea.example.org/app#` |
| EA domain | `http://nexus.enterprise.com/ea#` | `https://ontology.ea.example.org/ea#` |
| Data domain | `http://nexus.enterprise.com/data#` | `https://ontology.ea.example.org/data#` |
| Security domain | `http://nexus.enterprise.com/sec#` | `https://ontology.ea.example.org/security#` |
| Gov domain | `http://nexus.enterprise.com/gov#` | `https://ontology.ea.example.org/gov#` |
| Agent ops | `http://nexus.enterprise.com/agent#` | SPLIT: `ai:` for EA + `nexus:` for ops |
| Session | `http://nexus.enterprise.com/session#` | `https://nexus.platform/ops#` |

---

### Category 2 — CRITICAL: Class renames

| Old term (code) | New term (model) | Notes |
|-----------------|------------------|-------|
| `ea:BusinessCapability` | `ea:BusinessCapabilityL3` | Model has L1/L2/L3 hierarchy. L3 is the leaf for capability-app links. Use `(ea:BusinessCapabilityL1 \| L2 \| L3)` for full hierarchy queries |
| `ea:TechnologyCapability` | `ea:TechnologyCapabilityL3` | Same L1/L2/L3 pattern |
| `agent:AIAgent` | `ai:Agent` | Entire AI domain moved to `ai:` prefix |
| `agent:AgentFinding` | `nexus:AgentFinding` | Operational class, added in patch TTL |
| `cmdb:Infrastructure` | `infra:Infrastructure` | Full infra domain: Compute, Storage, LoadBalancer, ContainerCluster |
| `org:Department` | `hr:Department` | No separate `org:` namespace; departments live in HR |
| `data:DataAsset` | `data:DataProduct` or `data:Dataset` | Model distinguishes product (logical) vs dataset (physical) |
| `sec:SecurityRole` | `id:Role` | All identity concepts in `id:` domain |
| `iam:Certification` | `id:Certification` | Added by patch TTL |

---

### Category 3 — CRITICAL: Property renames

| Old property | New property | Direction change? |
|-------------|--------------|-------------------|
| `ea:realisedBy` | `ea:enablesBusinessCapability` | ✅ YES — was `?cap ea:realisedBy ?app`, now `?app ea:enablesBusinessCapability ?cap` |
| `hr:department` | `hr:memberOfDepartment` | No, but patch adds `hr:department` as alias |
| `hr:manager` | `hr:managedBy` | No |
| `data:classification` | `ea:dataProtectedByClassification` then `sec:classificationLevel` | Now a 2-hop: `?asset ea:dataProtectedByClassification ?cls . ?cls sec:classificationLevel ?level` |
| `data:owner` | `data:dataOwner` | Added by patch TTL |
| `agent:riskTier` | `ai:riskTier` | Added by patch TTL |
| `agent:platform` | `ai:agentPlatform` | Added by patch TTL |
| `agent:hasTool` | `ai:hasTool` | Added by patch TTL |
| `agent:ownedBy` | `ai:ownedBy` | Added by patch TTL |
| `agent:reviewDue` | `ai:reviewDue` | Added by patch TTL |
| `agent:affects` | `nexus:affects` | Added by patch TTL |
| `agent:foundBy` | `nexus:foundBy` | Added by patch TTL |
| `agent:foundAt` | `nexus:foundAt` | Added by patch TTL |
| `agent:severity` | `nexus:severity` | Added by patch TTL |
| `agent:status` | `nexus:findingStatus` | Added by patch TTL |
| `sec:grantsAccessTo` | `id:grantsPermission` (or `sec:grantsAccessTo` via patch) | Patch adds `sec:grantsAccessTo` as alias |
| `sec:lastCertified` | `id:lastCertified` | Added by patch TTL |
| `sec:certificationDue` | `id:certificationDue` | Added by patch TTL |
| `app:runsOnPlatform` | Model property → `ea:Platform` | Use for platform type queries |

---

### Category 4 — Integration queries: `app:dependsOn` → `int:Integration`

The model does **not** have a direct `app:dependsOn` property. Integrations are
first-class objects. The patch adds `app:dependsOn` as a shortcut, but the
**canonical query pattern** for integration diagrams and hotspot analysis is:

```sparql
# Count inbound connections to ?app
SELECT ?app (COUNT(?int_in) AS ?inbound) WHERE {
    ?int_in a int:Integration ;
            int:targetApplication ?app .
} GROUP BY ?app

# Find all apps that PaymentService depends on
SELECT ?dep ?depLabel WHERE {
    ?int a int:Integration ;
         int:sourceApplication ?src ;
         int:targetApplication ?dep .
    ?src rdfs:label ?srcLabel .
    FILTER(CONTAINS(LCASE(STR(?srcLabel)), "paymentservice"))
    OPTIONAL { ?dep rdfs:label ?depLabel }
}
```

Both `sa_advisor.py` (hotspot query) and `artifact_creator.py` (integration diagram,
dependency map, C4 context) have been updated to use this pattern.

---

### Category 5 — APM: TIME model via `sol:Disposition`

The model has a native `sol:Disposition` class with `sol:dispositionValue`.
The patch pre-creates the 4 TIME instances and adds `app:hasDisposition`.

**New preferred APM query** — check if an app already has a manual TIME override:
```sparql
SELECT ?app ?appLabel ?dispositionValue WHERE {
    ?app a app:Application .
    OPTIONAL { ?app rdfs:label ?appLabel }
    OPTIONAL {
        ?app app:hasDisposition ?disp .
        ?disp sol:dispositionValue ?dispositionValue
    }
}
```
The APM agent algorithm still scores apps from scratch when no explicit disposition
exists, but respects a pre-set `app:hasDisposition` triple as an override.

---

### Category 6 — SA Advisor: native `adv:` domain

The model has a full `adv:` (advisor) domain with:
- `adv:ArchitectureDecision` + `adv:ArchitectureOption` — existing decisions to query
- `adv:DuplicateRisk` — explicit duplicate capability records (links to `sol:Solution`)
- `adv:RoadmapItem` — existing roadmap commitments
- `adv:ArchitecturalPrinciple` + `adv:ArchitecturalRule` — guardrails for recommendations

The SA Advisor queries should check for **pre-existing** ADRs and roadmap items
to avoid recommending what is already decided:
```sparql
# Check if there's already a decommission decision for an app
SELECT ?app ?decision WHERE {
    ?decision a adv:ArchitectureDecision ;
              adv:resultsInSolution ?sol .
    ?sol sol:usesApplication ?app .
    OPTIONAL { ?decision adv:optionVerdict ?verdict }
    FILTER(CONTAINS(LCASE(STR(?verdict)), "decommission"))
}
```

---

### Category 7 — Artifact Creator: `art:` domain writeback

The model has a native `art:EAArtifact` hierarchy. After generating a diagram,
the Artifact Creator should **write it back** as a graph triple so it becomes
discoverable and auditable:

```python
# In artifact_creator.py after successful generation:
def persist_diagram(result: DiagramResult, db) -> str:
    uri = f"https://nexus.platform/ops#diagram_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    sparql = f"""
    PREFIX art:   <https://ontology.ea.example.org/artifact#>
    PREFIX nexus: <https://nexus.platform/ops#>
    PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
    INSERT DATA {{
        <{uri}> a art:ApplicationDiagram ;
            rdfs:label      "{result.title}" ;
            art:diagramType "{result.diagram_type}" ;
            art:entityScope "{result.entity}" ;
            art:format      "{result.fmt}" ;
            art:nodeCount   {result.node_count} ;
            art:edgeCount   {result.edge_count} ;
            art:generatedAt "{now}"^^xsd:dateTime ;
            {'art:mermaidSource "' + result.content.replace('"', '\\"') + '" ;' if result.fmt == 'mermaid' else ''}
            {'art:dotSource     "' + result.content.replace('"', '\\"') + '" ;' if result.fmt == 'dot' else ''}
            nexus:findingStatus "Active" .
    }}
    """
    db.update(sparql)
    return uri
```

---

## WHAT THE PATCH TTL ADDS (summary)

| Section | Classes/Properties added | Used by |
|---------|--------------------------|---------|
| A — Agent Findings | `nexus:AgentFinding` + 7 properties | `findings.py`, `context_provider.py`, all advisors |
| B — Sessions | `nexus:ConversationSession` + 9 properties | `session.py` |
| C — Certifications | `id:Certification` + 6 properties | `context_provider.py`, security queries |
| D — Governance | `gov:Regulation`, `gov:BusinessTerm`, `gov:DataPolicy`, `gov:DataQualityRule` + properties | `context_provider.py`, `clarifier.py` |
| E — Data bridging | `data:steward`, `data:dataOwner`, `data:lineageFrom`, `data:containsPII` | `context_provider.py`, `artifact_creator.py` |
| F — App bridging | `app:techOwner`, `app:lifecycle`, `app:dependsOn`, `app:processes/stores/accesses`, `app:hostingEnv`, `ea:strategicIntent`, `ea:domain` | All modules |
| G — AI ops | `ai:riskTier`, `ai:agentPlatform`, `ai:AgentTool`, `ai:ownedBy`, `ai:reviewDue`, `ai:hasTool`, `ai:agentReads/Writes` | `registry.py`, `guard.py` |
| H — Security bridging | `sec:grantsAccessTo`, `sec:hasAccess`, `hr:department` alias | `context_provider.py`, `artifact_creator.py` |
| I — TIME model | `sol:Tolerate/Invest/Migrate/Eliminate` individuals, `app:hasDisposition` | `apm_agent.py` |
| J — Advisor shortcuts | `adv:affectsApplication`, `adv:roadmapForApplication`, roadmap properties | `sa_advisor.py` |
| K — Artifact writeback | `art:generatedBy/At`, `art:mermaidSource`, `art:dotSource`, etc. | `artifact_creator.py` |

---

## WHAT YOU DO NOT NEED TO CHANGE

- `guard.py` logic — the classification clearance map uses string values, not URIs
- `auth.py` — JWT handling is application-level, not graph-level  
- `middleware.py` — rate limiting is application-level
- `pii_scanner.py` — regex patterns are application-level
- `answer_engine.py` — uses OpenAI, not SPARQL
- `clarifier.py` — the LLM system prompt will automatically pick up the updated `DOMAIN_HINTS`
- `nl_to_sparql.py` — the LLM will use updated prefixes from `SPARQL_PREFIX_BLOCK`
- `ontology.py` — fetches classes/properties live from graph; no hardcoded names
- `settings.py` — configuration only

The two things to manually update in `guard.py`:
```python
# Line ~195: HR dept scope filter
dept_filter = (
    f'\n  OPTIONAL {{ ?person hr:memberOfDepartment ?dept }}'         # was hr:department
    f'\n  FILTER(!BOUND(?dept) || STR(?dept) = "https://ontology.ea.example.org/hr#{user_department}")'
)
```
