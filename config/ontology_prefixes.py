
"""
config/ontology_prefixes_v2.py — expanded prefix registry for NEXUS buildout.

Key additions:
- cmdb / itsm prefixes for ServiceNow and operational graph integration
- LIFECYCLE_STATUSES and RISK_TIERS constants used by advisor/APM code
- richer DOMAIN_HINTS for logical applications, instances, incidents, and changes
"""
BASE = "https://ontology.ea.example.org/"

PREFIXES: dict[str, str] = {
    "rdf":    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs":   "http://www.w3.org/2000/01/rdf-schema#",
    "owl":    "http://www.w3.org/2002/07/owl#",
    "xsd":    "http://www.w3.org/2001/XMLSchema#",
    "skos":   "http://www.w3.org/2004/02/skos/core#",
    "sh":     "http://www.w3.org/ns/shacl#",

    "ea":     f"{BASE}ea#",
    "hr":     f"{BASE}hr#",
    "org":    f"{BASE}org#",
    "app":    f"{BASE}app#",
    "sol":    f"{BASE}sol#",
    "prod":   f"{BASE}prod#",
    "arch":   f"{BASE}arch#",
    "intg":   f"{BASE}int#",
    "infra":  f"{BASE}infra#",
    "net":    f"{BASE}net#",
    "fw":     f"{BASE}fw#",
    "cost":   f"{BASE}cost#",
    "data":   f"{BASE}data#",
    "gov":    f"{BASE}gov#",
    "sec":    f"{BASE}sec#",
    "iam":    f"{BASE}iam#",
    "entra":  f"{BASE}entra#",
    "ai":     f"{BASE}ai#",
    "agent":  f"{BASE}agent#",
    "adv":    f"{BASE}advisor#",
    "art":    f"{BASE}artifact#",
    "kg":     f"{BASE}kg#",
    "doc":    f"{BASE}doc#",
    "ds":     f"{BASE}datasource#",
    "denodo": f"{BASE}denodo#",
    "nexus":  f"{BASE}nexus#",
    "audit":  f"{BASE}audit#",
    "session":f"{BASE}session#",

    # new
    "cmdb":   f"{BASE}cmdb#",
    "itsm":   f"{BASE}itsm#",
}

SPARQL_PREFIX_BLOCK: str = "\n".join(f"PREFIX {k}: <{v}>" for k, v in PREFIXES.items())

LIFECYCLE_STATUSES = ["Development", "Pilot", "Active", "Maintain", "Sunset", "Legacy", "Retire", "EOL"]
RISK_TIERS = ["Low", "Medium", "High", "Critical"]

DOMAIN_HINTS: dict[str, str] = {
    "people":         "hr:User · hr:managedBy · hr:department · hr:jobTitle",
    "organisation":   "org:Department · org:Organisation · ea:EABusinessDomain",
    "applications":   "app:LogicalApplication · app:ApplicationInstance · app:techOwner · app:runsOnPlatform · app:instanceOfLogicalApplication · ea:enablesBusinessCapability",
    "architecture":   "ea:BusinessCapabilityL1/L2/L3 · ea:TechnologyCapabilityL1/L2/L3 · arch:Archetype · ea:TechPattern · adv:ArchitectureDecision",
    "integration":    "intg:Integration · intg:IntegrationPattern · intg:hasSourceSystem · intg:hasTargetSystem · intg:usesProtocol",
    "infrastructure": "infra:Infrastructure · infra:TechnologyInstance · infra:hostsApplicationInstance · net:NetworkZone · fw:FirewallRule",
    "data":           "data:DataAsset · data:DataProduct · data:DataPipeline · data:classification · data:steward · data:lineageFrom",
    "governance":     "gov:Regulation · gov:Vendor · gov:Contract · gov:ChangeRequest · gov:RiskItem",
    "security":       "sec:SecurityRole · sec:AccessGrant · sec:riskLevel · iam:Certification · sec:governsApplication",
    "agents":         "agent:AIAgent · agent:AgentFinding · ai:Agent · ai:riskTier · ai:governedByPolicy",
    "advisor":        "adv:ArchitectureDecision · adv:ArchitectureOption · adv:ArchitectureRule · adv:RoadmapItem · adv:DuplicateRisk",
    "itsm":           "itsm:Incident · itsm:Problem · itsm:Change · itsm:ServiceRequest · itsm:affectsApplicationInstance · itsm:affectsTechnologyInstance",
    "cmdb":           "cmdb:ConfigurationItem · cmdb:BusinessService · cmdb:Environment · app:representedInCMDB",
}
