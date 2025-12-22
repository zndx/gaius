# MetaAgent Lineage Cypher Fix

## Summary

Fixed the MetaAgent LineageAnalyst to correctly query the AGE graph for data lineage using Cypher. The fix involved:

1. **AGE Extension Access**: Removed `LOAD 'age'` from the lineage emitter - this command requires superuser privileges but is unnecessary when AGE is installed as an extension. Setting `search_path = ag_catalog, public` is sufficient.

2. **Lineage Population**: Created `scripts/populate_cloudera_lineage.py` to populate the AGE graph with Cloudera documentation provenance:
   - 10 Cloudera products synced (csa, csa-operator, cdw-runtime, etc.)
   - Source datasets (cloudera.source namespace) linked to KB outputs (gaius.kb namespace)
   - Uses `DatasetFacets` properly instead of raw dicts

3. **LineageAnalyst Prompt Enhancement**: Improved the system prompt to clearly explain data flow direction:
   - Sources (upstream) use `INPUT_TO` edge to reach Runs
   - Outputs (downstream) are created via `OUTPUTS` edge from Runs
   - Added clear examples showing "to find sources of X, match on target X"

## Files Modified

- `src/gaius/hx/lineage/emitter.py` - Removed `LOAD 'age'` requirement
- `src/gaius/agents/roles.py` - Enhanced LineageAnalyst prompt with data flow direction
- `scripts/populate_cloudera_lineage.py` - Fixed `DatasetFacets` usage

## Verification

Query: "What sources feed into the CSA docs?"

Generated Cypher:
```cypher
MATCH (s:Dataset)-[:INPUT_TO]->(:Run)-[:OUTPUTS]->(t:Dataset)
WHERE t.namespace = 'gaius.kb' AND t.name CONTAINS 'csa'
RETURN s.namespace AS source_namespace, s.name AS source_name, t.name AS target_name
```

Answer: "The CSA docs are fed by two primary sources: docs.cloudera.com/csa and docs.cloudera.com/csa-operator"

## AGE Graph Data

```
cloudera.source:docs.cloudera.com/csa → gaius.kb:current/cloudera/docs/csa
cloudera.source:docs.cloudera.com/csa-operator → gaius.kb:current/cloudera/docs/csa-operator
cloudera.source:docs.cloudera.com/cdw-runtime → gaius.kb:current/cloudera/docs/cdw-runtime
... (10 products total)
```

## Key Learning

The AGE extension doesn't require `LOAD 'age'` when installed via `CREATE EXTENSION`. Only the search path needs to be set. The `LOAD` command is for shared library loading and requires superuser privileges.
