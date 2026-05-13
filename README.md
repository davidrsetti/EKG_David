# NEXUS clean code v2

This package is a cleaned, repo-structured version of your current NEXUS prototype plus the next-step guided SA buildout.

## What's included

- Existing graph chat pipeline
- Existing freeform SA diagram generator
- New guided, capability-first SA Advisor
- Expanded ontology prefixes for CMDB / ITSM
- Additive ontology extension for logical apps, instances, and operational impact

## Recommended file ownership

- Source-of-truth ontology:
  - `ontologies/ea-ontology-consolidated-v8.ttl`
  - `ontologies/nexus-ontology-patch-v1.ttl`
- Additive extension:
  - `ontologies/ea-ontology-itsm-cmdb-extension-v1.ttl`

## App tabs

1. Knowledge Graph Chat
2. Guided SA Advisor
3. Freeform SA Diagram

## Suggested next implementation order

1. Load the additive ITSM/CMDB TTL in Stardog after v8 and the patch
2. Replace your current code with this package structure, or use `flat_files/` for direct replacement
3. Validate the guided SA queries against your live graph
4. Add ServiceNow / CMDB loaders for incidents, changes, configuration items, and environments
5. Extend the artifact engine to consume the guided SA `archimate_prompt`

## Notes

This is a clean merge baseline. It is not yet validated against your live Stardog schema or live ServiceNow data."# EKG_David" 
