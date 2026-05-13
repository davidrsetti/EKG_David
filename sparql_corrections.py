"""
NEXUS v2.1 — SPARQL Query Corrections for enterprise_complete_no_orphans_v2.ttl
================================================================================
This file contains the corrected SPARQL query strings that must replace the
equivalent queries in each module. Copy the relevant section into each file.

Key changes applied throughout:
  1. ea:BusinessCapability          → ea:BusinessCapabilityL3
  2. ea:realisedBy                  → ea:enablesBusinessCapability  (direction: app → cap)
  3. agent:AIAgent                  → ai:Agent
  4. agent:AgentFinding             → nexus:AgentFinding
  5. agent:riskTier                 → ai:riskTier
  6. agent:platform / vendor etc.   → ai:agentPlatform / ai:agentVendor
  7. agent:hasTool                  → ai:hasTool
  8. agent:ownedBy/reviewDue        → ai:ownedBy / ai:reviewDue
  9. agent:affects/foundBy/etc.     → nexus:affects / nexus:foundBy / etc.
 10. agent:status                   → nexus:findingStatus
 11. agent:severity                 → nexus:severity
 12. sec:SecurityRole               → id:Role
 13. sec:AccessGrant                → id:Certification (app:hasCertification)
 14. iam:Certification              → id:Certification
 15. sec:lastCertified              → id:lastCertified
 16. sec:certificationDue           → id:certificationDue
 17. cmdb:Infrastructure            → infra:Infrastructure
 18. cmdb:connectsTo/subscribesTo   → int:Integration (int:sourceApplication/int:targetApplication)
 19. hr:department                  → hr:memberOfDepartment  (or hr:department alias from patch)
 20. data:DataAsset                 → data:DataProduct  (or data:Dataset)
 21. data:classification            → ea:dataProtectedByClassification → sec:classificationLevel
 22. data:owner                     → data:dataOwner
 23. sec:clearance                  → sec:clearance on ai:Agent
 24. All URI bases updated to https://ontology.ea.example.org/

Note: Properties added by enterprise_nexus_operations_patch.ttl are marked [PATCH].
"""

# ==============================================================================
# findings.py  — patch BASE and all property names
# ==============================================================================
FINDINGS_BASE = "https://nexus.platform/ops#"
FINDINGS_AI_BASE = "https://ontology.ea.example.org/ai#"

FINDINGS_INSERT = '''
PREFIX nexus: <https://nexus.platform/ops#>
PREFIX ai:    <https://ontology.ea.example.org/ai#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

INSERT DATA {{
    <{uri}> a nexus:AgentFinding ;
        rdfs:label              "{label}" ;
        nexus:foundBy           <{agent_uri}> ;
        nexus:foundAt           "{now}"^^xsd:dateTime ;
        nexus:affects           <{asset_uri}> ;
        nexus:severity          "{severity}" ;
        nexus:findingStatus     "{status}" ;
        nexus:findingDescription "{description}" .
}}
'''

FINDINGS_UPDATE_STATUS = '''
PREFIX nexus: <https://nexus.platform/ops#>

DELETE {{ <{finding_uri}> nexus:findingStatus ?old }}
INSERT {{
    <{finding_uri}> nexus:findingStatus "{new_status}" .
    {reviewer_triple}
}}
WHERE {{ <{finding_uri}> nexus:findingStatus ?old }}
'''


# ==============================================================================
# registry.py  — patch all agent: → ai: / nexus:
# ==============================================================================
REGISTRY_GET_AGENT = '''
SELECT ?label ?platform ?vendor ?riskTier ?clearanceLevel ?policy ?ownedBy ?reviewDue WHERE {{
    ?agent a ai:Agent ;
           rdfs:label ?label .
    FILTER(CONTAINS(LCASE(STR(?agent)), "{agent_id}") ||
           CONTAINS(LCASE(STR(?label)), "{agent_id}"))
    OPTIONAL {{ ?agent ai:agentPlatform   ?platform      }}
    OPTIONAL {{ ?agent ai:agentVendor     ?vendor        }}
    OPTIONAL {{ ?agent ai:riskTier        ?riskTier      }}
    OPTIONAL {{ ?agent sec:clearance      ?clearanceLevel }}
    OPTIONAL {{ ?agent ai:agentPolicy     ?policy        }}
    OPTIONAL {{ ?agent ai:ownedBy         ?owner .
                ?owner rdfs:label         ?ownedBy       }}
    OPTIONAL {{ ?agent ai:reviewDue       ?reviewDue     }}
}} LIMIT 1
'''

REGISTRY_LIST_AGENTS = '''
SELECT ?agent ?label ?platform ?riskTier ?ownedBy ?reviewDue WHERE {{
    ?agent a ai:Agent ;
           rdfs:label ?label .
    OPTIONAL {{ ?agent ai:agentPlatform  ?platform  }}
    OPTIONAL {{ ?agent ai:riskTier       ?riskTier  }}
    OPTIONAL {{ ?agent ai:scopedTo       ?domain    }}
    OPTIONAL {{ ?agent ai:ownedBy        ?owner .
                ?owner rdfs:label        ?ownedBy   }}
    OPTIONAL {{ ?agent ai:reviewDue      ?reviewDue }}
    {filter_block}
}} ORDER BY ?label LIMIT 100
'''

REGISTRY_GET_TOOLS = '''
SELECT ?tool ?toolLabel ?endpoint ?rateLimit ?requiredRole WHERE {{
    ?agent a ai:Agent ;
           rdfs:label ?agentLabel .
    FILTER(CONTAINS(LCASE(STR(?agentLabel)), "{agent_id}"))
    ?agent ai:hasTool ?tool .
    OPTIONAL {{ ?tool rdfs:label          ?toolLabel    }}
    OPTIONAL {{ ?tool ai:toolEndpoint     ?endpoint     }}
    OPTIONAL {{ ?tool ai:toolRateLimit    ?rateLimit    }}
    OPTIONAL {{ ?tool ai:requiresRole     ?requiredRole }}
}} ORDER BY ?toolLabel
'''


# ==============================================================================
# session.py  — patch all session: → nexus:
# ==============================================================================
SESSION_CREATE = '''
PREFIX nexus: <https://nexus.platform/ops#>
PREFIX hr:    <https://ontology.ea.example.org/hr#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

INSERT DATA {{
    <{session_uri}> a nexus:ConversationSession ;
        rdfs:label              "Session {session_id}" ;
        nexus:sessionUserId     "{user_id}" ;
        nexus:sessionUserRole   "{user_role}" ;
        nexus:sessionUserRef    <{user_uri}> ;
        nexus:startedAt         "{now}"^^xsd:dateTime ;
        nexus:turnCount         0 ;
        nexus:sessionStatus     "Active" .
}}
'''

SESSION_UPDATE = '''
PREFIX nexus: <https://nexus.platform/ops#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

DELETE {{ <{session_uri}> nexus:lastIntent  ?i ;
                          nexus:turnCount   ?t ;
                          nexus:lastActive  ?a ;
                          nexus:entityFocus ?f }}
INSERT {{
    <{session_uri}> nexus:lastIntent  "{intent}" ;
                    nexus:turnCount   {turn_count} ;
                    nexus:lastActive  "{now}"^^xsd:dateTime .
    {focus_triples}
}}
WHERE {{
    OPTIONAL {{ <{session_uri}> nexus:lastIntent  ?i }}
    OPTIONAL {{ <{session_uri}> nexus:turnCount   ?t }}
    OPTIONAL {{ <{session_uri}> nexus:lastActive  ?a }}
    OPTIONAL {{ <{session_uri}> nexus:entityFocus ?f }}
}}
'''

SESSION_GET_CONTEXT = '''
SELECT ?lastIntent ?turnCount ?entityFocus ?focusLabel WHERE {{
    <{session_uri}> nexus:sessionUserId ?userId .
    OPTIONAL {{ <{session_uri}> nexus:lastIntent  ?lastIntent  }}
    OPTIONAL {{ <{session_uri}> nexus:turnCount   ?turnCount   }}
    OPTIONAL {{ <{session_uri}> nexus:entityFocus ?entityFocus .
                ?entityFocus rdfs:label ?focusLabel }}
}}
'''


# ==============================================================================
# context_provider.py  — patch all property names
# ==============================================================================
CONTEXT_RESOLVE = '''
SELECT ?entity ?label ?type ?domain ?classification ?owner ?ownerLabel ?steward ?stewardLabel WHERE {{
    ?entity rdfs:label ?label .
    FILTER(CONTAINS(LCASE(STR(?label)), "{entity_name}"))
    OPTIONAL {{ ?entity a ?type }}
    OPTIONAL {{ ?entity ea:domain          ?domain        }}
    OPTIONAL {{
        ?entity ea:dataProtectedByClassification ?cls .
        ?cls    sec:classificationLevel           ?classification
    }}
    OPTIONAL {{ ?entity app:techOwner      ?owner   . ?owner rdfs:label ?ownerLabel  }}
    OPTIONAL {{ ?entity data:dataOwner     ?owner   . ?owner rdfs:label ?ownerLabel  }}
    OPTIONAL {{ ?entity data:steward       ?steward . ?steward rdfs:label ?stewardLabel }}
}} LIMIT 1
'''

CONTEXT_POLICIES = '''
SELECT ?policy ?policyLabel ?regulation WHERE {{
    <{entity_uri}> (gov:regulatedBy | gov:governedBy | sec:governsApplication) ?policy .
    OPTIONAL {{ ?policy rdfs:label ?policyLabel }}
    OPTIONAL {{ ?policy a gov:Regulation . BIND(STR(?policy) AS ?regulation) }}
}} LIMIT 20
'''

CONTEXT_FINDINGS = '''
SELECT ?finding ?findingLabel ?severity ?status ?foundBy ?foundByLabel ?foundAt WHERE {{
    ?finding a nexus:AgentFinding ;
             nexus:affects <{entity_uri}> ;
             nexus:findingStatus ?status .
    FILTER(?status != "Resolved")
    OPTIONAL {{ ?finding rdfs:label         ?findingLabel }}
    OPTIONAL {{ ?finding nexus:severity     ?severity     }}
    OPTIONAL {{ ?finding nexus:foundAt      ?foundAt      }}
    OPTIONAL {{ ?finding nexus:foundBy      ?foundBy .
                ?foundBy rdfs:label         ?foundByLabel }}
}} ORDER BY DESC(?foundAt) LIMIT 10
'''

CONTEXT_ACCESS = '''
SELECT ?identity ?identityLabel ?role ?roleLabel ?certifiedOn ?certificationDue WHERE {{
    ?cert a id:Certification ;
          id:certificationFor  ?identity .
    OPTIONAL {{ ?cert id:certificationRole ?role  . ?role rdfs:label ?roleLabel }}
    OPTIONAL {{ ?identity rdfs:label ?identityLabel }}
    OPTIONAL {{ ?cert id:lastCertified    ?certifiedOn      }}
    OPTIONAL {{ ?cert id:certificationDue ?certificationDue }}
    FILTER EXISTS {{
        <{entity_uri}> (app:accessedByIdentity | ^id:linkedUser) ?identity
    }}
}} LIMIT 20
'''


# ==============================================================================
# sa_advisor.py  — all 6 SPARQL queries corrected
# ==============================================================================
SA_CAPABILITY_QUERY = '''
SELECT ?cap ?capLabel ?app ?appLabel ?lifecycle ?domain WHERE {{
    ?cap a ea:BusinessCapabilityL3 .
    OPTIONAL {{ ?cap rdfs:label  ?capLabel }}
    OPTIONAL {{ ?cap ea:domain   ?domain   }}
    OPTIONAL {{
        ?app a app:Application .
        ?app ea:enablesBusinessCapability ?cap .
        OPTIONAL {{ ?app rdfs:label    ?appLabel   }}
        OPTIONAL {{ ?app app:lifecycle ?lifecycle  }}
    }}
    {domain_filter}
}} ORDER BY ?capLabel LIMIT 300
'''

# Also pick up L1/L2 gaps (not just L3)
SA_CAPABILITY_QUERY_ALL_LEVELS = '''
SELECT ?cap ?capLabel ?app ?appLabel ?lifecycle ?domain WHERE {{
    {{ ?cap a ea:BusinessCapabilityL1 }} UNION
    {{ ?cap a ea:BusinessCapabilityL2 }} UNION
    {{ ?cap a ea:BusinessCapabilityL3 }}
    OPTIONAL {{ ?cap rdfs:label  ?capLabel }}
    OPTIONAL {{ ?cap ea:domain   ?domain   }}
    OPTIONAL {{
        ?app a app:Application .
        ?app ea:enablesBusinessCapability ?cap .
        OPTIONAL {{ ?app rdfs:label    ?appLabel   }}
        OPTIONAL {{ ?app app:lifecycle ?lifecycle  }}
    }}
    {domain_filter}
}} ORDER BY ?capLabel LIMIT 300
'''

SA_ORPHAN_QUERY = '''
SELECT DISTINCT ?app ?appLabel ?platform ?lifecycle ?domain WHERE {{
    ?app a app:Application .
    OPTIONAL {{ ?app rdfs:label     ?appLabel  }}
    OPTIONAL {{ ?app app:runsOnPlatform ?plat . ?plat rdfs:label ?platform }}
    OPTIONAL {{ ?app app:lifecycle  ?lifecycle }}
    OPTIONAL {{ ?app ea:domain      ?domain    }}
    FILTER NOT EXISTS {{ ?app app:techOwner ?owner }}
    FILTER NOT EXISTS {{ ?app app:ownedByDepartment ?dept }}
    {domain_filter}
}} LIMIT 100
'''

SA_HOTSPOT_QUERY = '''
SELECT ?app ?appLabel
       (COUNT(DISTINCT ?int_out) AS ?outboundCount)
       (COUNT(DISTINCT ?int_in)  AS ?inboundCount)
WHERE {{
    ?app a app:Application .
    OPTIONAL {{ ?app rdfs:label ?appLabel }}
    OPTIONAL {{ ?int_out a int:Integration ; int:sourceApplication ?app }}
    OPTIONAL {{ ?int_in  a int:Integration ; int:targetApplication ?app }}
    {domain_filter}
}} GROUP BY ?app ?appLabel
ORDER BY DESC(?outboundCount) LIMIT 20
'''

SA_TECHDEBT_QUERY = '''
SELECT ?app ?appLabel ?lifecycle ?platform ?owner ?ownerLabel ?domain WHERE {{
    ?app a app:Application .
    OPTIONAL {{ ?app rdfs:label   ?appLabel   }}
    OPTIONAL {{ ?app app:lifecycle ?lifecycle  }}
    OPTIONAL {{ ?app app:runsOnPlatform ?plat . ?plat rdfs:label ?platform }}
    OPTIONAL {{ ?app ea:domain    ?domain     }}
    OPTIONAL {{ ?app app:techOwner ?owner .   ?owner rdfs:label ?ownerLabel }}
    FILTER(
        CONTAINS(LCASE(STR(?lifecycle)), "retire")    ||
        CONTAINS(LCASE(STR(?lifecycle)), "legacy")    ||
        CONTAINS(LCASE(STR(?lifecycle)), "end-of-life") ||
        CONTAINS(LCASE(STR(?lifecycle)), "eol")       ||
        CONTAINS(LCASE(STR(?lifecycle)), "sunset")
    )
    {domain_filter}
}} LIMIT 100
'''

SA_GAP_QUERY = '''
SELECT ?cap ?capLabel ?domain ?strategicIntent WHERE {{
    ?cap a ea:BusinessCapabilityL3 .
    OPTIONAL {{ ?cap rdfs:label         ?capLabel       }}
    OPTIONAL {{ ?cap ea:domain          ?domain         }}
    OPTIONAL {{ ?cap ea:strategicIntent ?strategicIntent }}
    FILTER NOT EXISTS {{ ?app ea:enablesBusinessCapability ?cap }}
    {domain_filter}
}} LIMIT 100
'''

SA_DATARISK_QUERY = '''
SELECT DISTINCT ?app ?appLabel ?classLevel ?findingLabel ?severity WHERE {{
    ?app a app:Application .
    OPTIONAL {{ ?app rdfs:label ?appLabel }}
    {{ ?app app:processes ?asset }} UNION
    {{ ?app app:stores    ?asset }} UNION
    {{ ?app app:accesses  ?asset }}
    ?asset ea:dataProtectedByClassification ?cls .
    ?cls   sec:classificationLevel ?classLevel .
    FILTER(?classLevel IN ("Restricted", "Confidential"))
    OPTIONAL {{
        ?finding a nexus:AgentFinding ;
                 nexus:affects         ?app ;
                 nexus:findingStatus   ?fStatus .
        FILTER(?fStatus != "Resolved")
        OPTIONAL {{ ?finding rdfs:label    ?findingLabel }}
        OPTIONAL {{ ?finding nexus:severity ?severity    }}
    }}
    {domain_filter}
}} LIMIT 50
'''


# ==============================================================================
# apm_agent.py  — 3 SPARQL queries corrected
# ==============================================================================
APM_APPS_QUERY = '''
SELECT ?app ?appLabel ?owner ?ownerLabel ?lifecycle ?platform ?domain ?strategicIntent
       (COUNT(DISTINCT ?cap)      AS ?capCount)
       (COUNT(DISTINCT ?int_out)  AS ?depCount)
       (COUNT(DISTINCT ?int_in)   AS ?conCount)
WHERE {{
    ?app a app:Application .
    OPTIONAL {{ ?app rdfs:label                   ?appLabel       }}
    OPTIONAL {{ ?app app:techOwner                ?owner .
                ?owner rdfs:label                 ?ownerLabel     }}
    OPTIONAL {{ ?app app:lifecycle                ?lifecycle      }}
    OPTIONAL {{ ?app app:runsOnPlatform           ?plat .
                ?plat rdfs:label                  ?platform       }}
    OPTIONAL {{ ?app ea:domain                    ?domain         }}
    OPTIONAL {{ ?app ea:strategicIntent           ?strategicIntent }}
    OPTIONAL {{ ?app ea:enablesBusinessCapability ?cap            }}
    OPTIONAL {{ ?int_out a int:Integration ; int:sourceApplication ?app }}
    OPTIONAL {{ ?int_in  a int:Integration ; int:targetApplication ?app }}
    {domain_filter}
}} GROUP BY ?app ?appLabel ?owner ?ownerLabel ?lifecycle ?platform ?domain ?strategicIntent
ORDER BY ?appLabel LIMIT 500
'''

APM_FINDINGS_QUERY = '''
SELECT ?app ?appLabel ?finding ?severity ?status WHERE {{
    ?finding a nexus:AgentFinding ;
             nexus:affects       ?app ;
             nexus:findingStatus ?status .
    FILTER(?status != "Resolved")
    ?app a app:Application .
    OPTIONAL {{ ?app     rdfs:label      ?appLabel }}
    OPTIONAL {{ ?finding nexus:severity  ?severity }}
    {domain_filter}
}} LIMIT 500
'''

APM_ASSETS_QUERY = '''
SELECT ?app ?appLabel ?asset ?classLevel WHERE {{
    ?app a app:Application .
    OPTIONAL {{ ?app rdfs:label ?appLabel }}
    {{ ?app app:processes ?asset }} UNION
    {{ ?app app:stores    ?asset }} UNION
    {{ ?app app:accesses  ?asset }}
    OPTIONAL {{
        ?asset ea:dataProtectedByClassification ?cls .
        ?cls   sec:classificationLevel          ?classLevel
    }}
    {domain_filter}
}} LIMIT 500
'''

APM_APP_DETAIL_QUERY = '''
SELECT ?app ?appLabel ?owner ?ownerLabel ?lifecycle ?platform ?vendor
       ?domain ?strategicIntent ?hostingEnv
       (COUNT(DISTINCT ?cap)      AS ?capCount)
       (COUNT(DISTINCT ?int_out)  AS ?depCount)
       (COUNT(DISTINCT ?int_in)   AS ?conCount)
       (COUNT(DISTINCT ?finding)  AS ?findingCount)
WHERE {{
    ?app a app:Application .
    OPTIONAL {{ ?app rdfs:label                   ?appLabel       }}
    FILTER(CONTAINS(LCASE(STR(?appLabel)), "{app_name}"))
    OPTIONAL {{ ?app app:techOwner                ?owner .
                ?owner rdfs:label                 ?ownerLabel     }}
    OPTIONAL {{ ?app app:lifecycle                ?lifecycle      }}
    OPTIONAL {{ ?app app:runsOnPlatform           ?plat .
                ?plat rdfs:label                  ?platform       }}
    OPTIONAL {{ ?app app:vendor                   ?vendor         }}
    OPTIONAL {{ ?app ea:domain                    ?domain         }}
    OPTIONAL {{ ?app ea:strategicIntent           ?strategicIntent }}
    OPTIONAL {{ ?app app:hostingEnv               ?hostingEnv     }}
    OPTIONAL {{ ?app ea:enablesBusinessCapability ?cap            }}
    OPTIONAL {{ ?int_out a int:Integration ; int:sourceApplication ?app }}
    OPTIONAL {{ ?int_in  a int:Integration ; int:targetApplication ?app }}
    OPTIONAL {{
        ?finding a nexus:AgentFinding ;
                 nexus:affects       ?app ;
                 nexus:findingStatus "Open"
    }}
}} GROUP BY ?app ?appLabel ?owner ?ownerLabel ?lifecycle ?platform
           ?vendor ?domain ?strategicIntent ?hostingEnv
LIMIT 1
'''


# ==============================================================================
# artifact_creator.py  — all 7 diagram SPARQL queries corrected
# ==============================================================================

# dependency_map — use int:Integration instead of app:dependsOn (preferred)
# app:dependsOn kept as fallback (added in patch TTL)
ARTIFACT_DEPENDENCY_ENTITY = '''
SELECT DISTINCT ?app ?appLabel ?dep ?depLabel WHERE {{
    ?app a app:Application ;
         rdfs:label ?appLabel .
    FILTER(CONTAINS(LCASE(STR(?appLabel)), "{entity}"))
    {{
        ?int a int:Integration ;
             int:sourceApplication ?app ;
             int:targetApplication ?dep .
    }} UNION {{
        ?app app:dependsOn ?dep .
    }}
    ?dep a app:Application .
    OPTIONAL {{ ?dep rdfs:label ?depLabel }}
}} LIMIT {max_nodes}
'''

ARTIFACT_DEPENDENCY_ALL = '''
SELECT DISTINCT ?app ?appLabel ?dep ?depLabel WHERE {{
    {{
        ?int a int:Integration ;
             int:sourceApplication ?app ;
             int:targetApplication ?dep .
        ?app a app:Application . ?dep a app:Application .
        OPTIONAL {{ ?app rdfs:label ?appLabel }}
        OPTIONAL {{ ?dep rdfs:label ?depLabel }}
    }} UNION {{
        ?app a app:Application ;
             app:dependsOn ?dep .
        ?dep a app:Application .
        OPTIONAL {{ ?app rdfs:label ?appLabel }}
        OPTIONAL {{ ?dep rdfs:label ?depLabel }}
    }}
    {domain_clause}
}} LIMIT {max_nodes}
'''

ARTIFACT_CAPABILITY_MAP = '''
SELECT ?cap ?capLabel ?app ?appLabel ?lifecycle ?domain WHERE {{
    {{ ?cap a ea:BusinessCapabilityL1 }} UNION
    {{ ?cap a ea:BusinessCapabilityL2 }} UNION
    {{ ?cap a ea:BusinessCapabilityL3 }}
    OPTIONAL {{ ?cap rdfs:label  ?capLabel }}
    OPTIONAL {{ ?cap ea:domain   ?domain   }}
    {entity_clause}
    OPTIONAL {{
        ?app a app:Application ;
             ea:enablesBusinessCapability ?cap .
        OPTIONAL {{ ?app rdfs:label    ?appLabel   }}
        OPTIONAL {{ ?app app:lifecycle ?lifecycle  }}
    }}
    {domain_clause}
}} LIMIT {max_nodes}
'''

ARTIFACT_DATA_LINEAGE_UP = '''
SELECT ?asset ?assetLabel ?upstream ?upstreamLabel ?classLevel WHERE {{
    ?asset a data:Dataset .
    OPTIONAL {{ ?asset rdfs:label ?assetLabel }}
    {anchor}
    ?asset (data:lineageFrom){{1,{depth}}} ?upstream .
    OPTIONAL {{ ?upstream rdfs:label ?upstreamLabel }}
    OPTIONAL {{
        ?asset ea:dataProtectedByClassification ?cls .
        ?cls   sec:classificationLevel          ?classLevel
    }}
}} LIMIT {limit}
'''

ARTIFACT_DATA_LINEAGE_DOWN = '''
SELECT ?asset ?assetLabel ?downstream ?downstreamLabel WHERE {{
    ?asset a data:Dataset .
    OPTIONAL {{ ?asset rdfs:label ?assetLabel }}
    {anchor}
    ?downstream (data:lineageFrom){{1,{depth}}} ?asset .
    OPTIONAL {{ ?downstream rdfs:label ?downstreamLabel }}
}} LIMIT {limit}
'''

ARTIFACT_AGENT_ECOSYSTEM = '''
SELECT ?agent ?agentLabel ?riskTier ?platform ?tool ?toolLabel ?asset ?assetLabel ?classLevel WHERE {{
    ?agent a ai:Agent .
    OPTIONAL {{ ?agent rdfs:label         ?agentLabel }}
    OPTIONAL {{ ?agent ai:riskTier        ?riskTier   }}
    OPTIONAL {{ ?agent ai:agentPlatform   ?platform   }}
    OPTIONAL {{ ?agent ai:hasTool         ?tool .
                ?tool  rdfs:label         ?toolLabel  }}
    OPTIONAL {{
        {{ ?agent ai:agentReads  ?asset }} UNION
        {{ ?agent ai:agentWrites ?asset }} UNION
        {{ ?agent ai:accessesApplication ?appx .
          {{ ?appx app:processes ?asset }} UNION
          {{ ?appx app:stores    ?asset }} }}
        OPTIONAL {{ ?asset rdfs:label ?assetLabel }}
        OPTIONAL {{
            ?asset ea:dataProtectedByClassification ?cls .
            ?cls   sec:classificationLevel          ?classLevel
        }}
    }}
    {entity_clause}
}} LIMIT {max_nodes}
'''

ARTIFACT_C4_CONTEXT = '''
SELECT ?app ?appLabel ?owner ?ownerLabel ?dep ?depLabel ?capability ?capLabel ?user ?userLabel WHERE {{
    ?app a app:Application .
    OPTIONAL {{ ?app rdfs:label ?appLabel }}
    FILTER(CONTAINS(LCASE(STR(?appLabel)), "{entity}"))
    OPTIONAL {{ ?app app:techOwner  ?owner     . ?owner rdfs:label ?ownerLabel }}
    OPTIONAL {{
        ?int a int:Integration ;
             int:sourceApplication ?app ;
             int:targetApplication ?dep .
        ?dep a app:Application .
        OPTIONAL {{ ?dep rdfs:label ?depLabel }}
    }}
    OPTIONAL {{
        ?app ea:enablesBusinessCapability ?capability .
        OPTIONAL {{ ?capability rdfs:label ?capLabel }}
    }}
    OPTIONAL {{
        ?user a hr:User ;
              sec:hasAccess ?app .
        OPTIONAL {{ ?user rdfs:label ?userLabel }}
    }}
}} LIMIT {max_nodes}
'''

ARTIFACT_ORG_OWNERSHIP = '''
SELECT ?owner ?ownerLabel ?dept ?deptLabel ?app ?appLabel ?asset ?assetLabel WHERE {{
    ?owner a hr:User .
    OPTIONAL {{ ?owner rdfs:label          ?ownerLabel }}
    OPTIONAL {{ ?owner hr:memberOfDepartment ?dept .
                ?dept  rdfs:label           ?deptLabel  }}
    OPTIONAL {{
        ?app a app:Application ;
             app:techOwner ?owner .
        OPTIONAL {{ ?app rdfs:label ?appLabel }}
        OPTIONAL {{ ?app ea:domain  ?domain   }}
        {domain_clause}
    }}
    OPTIONAL {{
        ?asset a data:Dataset ;
               data:dataOwner ?owner .
        OPTIONAL {{ ?asset rdfs:label ?assetLabel }}
    }}
    {person_filter}
}} LIMIT {max_nodes}
'''

ARTIFACT_INTEGRATION_MAP = '''
SELECT DISTINCT ?app ?appLabel ?dep ?depLabel ?intMethod ?domain WHERE {{
    ?int a int:Integration ;
         int:sourceApplication ?app ;
         int:targetApplication ?dep .
    ?app a app:Application .
    ?dep a app:Application .
    OPTIONAL {{ ?app rdfs:label          ?appLabel  }}
    OPTIONAL {{ ?dep rdfs:label          ?depLabel  }}
    OPTIONAL {{ ?int int:integrationMethod ?intMethod }}
    OPTIONAL {{ ?app ea:domain           ?domain    }}
    {anchor_clause}
    {domain_clause}
}} LIMIT {max_nodes}
'''


# ==============================================================================
# main.py  — health check queries corrected
# ==============================================================================
HEALTH_CHECKS = {
    "total_triples":         "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }",
    "total_people":          "SELECT (COUNT(*) AS ?count) WHERE { ?s a hr:User }",
    "total_apps":            "SELECT (COUNT(*) AS ?count) WHERE { ?s a app:Application }",
    "total_data_datasets":   "SELECT (COUNT(*) AS ?count) WHERE { ?s a data:Dataset }",
    "total_data_products":   "SELECT (COUNT(*) AS ?count) WHERE { ?s a data:DataProduct }",
    "total_ai_agents":       "SELECT (COUNT(*) AS ?count) WHERE { ?s a ai:Agent }",
    "total_capabilities_l3": "SELECT (COUNT(*) AS ?count) WHERE { ?s a ea:BusinessCapabilityL3 }",
    "total_solutions":       "SELECT (COUNT(*) AS ?count) WHERE { ?s a sol:Solution }",
    "total_integrations":    "SELECT (COUNT(*) AS ?count) WHERE { ?s a int:Integration }",
    "open_findings":         "SELECT (COUNT(*) AS ?count) WHERE { ?s a nexus:AgentFinding ; nexus:findingStatus 'Open' }",
    "orphaned_apps":         "SELECT (COUNT(*) AS ?count) WHERE { ?s a app:Application . FILTER NOT EXISTS { ?s app:techOwner ?o } FILTER NOT EXISTS { ?s app:ownedByDepartment ?d } }",
    "unstewardedd_datasets": "SELECT (COUNT(*) AS ?count) WHERE { ?s a data:Dataset . FILTER NOT EXISTS { ?s data:steward ?w } }",
    "capability_gaps_l3":    "SELECT (COUNT(*) AS ?count) WHERE { ?s a ea:BusinessCapabilityL3 . FILTER NOT EXISTS { ?a ea:enablesBusinessCapability ?s } }",
    "overdue_certs":         "SELECT (COUNT(*) AS ?count) WHERE { ?s a id:Certification ; id:certificationStatus 'Overdue' }",
}


# ==============================================================================
# guard.py  — HR dept filter corrected
# ==============================================================================
GUARD_HR_DEPT_FILTER = """
  OPTIONAL {{ ?person hr:memberOfDepartment ?dept }}
  FILTER(!BOUND(?dept) || STR(?dept) = "https://ontology.ea.example.org/hr#{department}")
"""
