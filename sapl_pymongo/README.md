# sapl-pymongo

SAPL signal source for PyMongo. Contributes the `MONGO_QUERY` signal and a
`mongo:queryRewriting` constraint handler provider so a SAPL policy can shape
the MongoDB queries an application issues, the same way `sapl-sqlalchemy`
contributes `SQL_QUERY` for relational queries.

PyMongo's driver-monitoring API is observe-only, so there is no central mutating
query hook. The cut point is therefore a thin proxy over the collection's
query-issuing methods (`find`, `find_one`, `aggregate`, `count_documents`,
`update_*`, `delete_*`). Each wrapped call discharges `MONGO_QUERY` with the
structured query (a filter mapping or an aggregation pipeline) before delegating
to the driver. A synchronous proxy backs the blocking enforcement path (Flask,
sync Django); an asynchronous proxy backs the async path (FastAPI, Tornado,
async Django).

## Obligation

`MongoDbQueryRewritingProvider` handles the `mongo:queryRewriting` obligation,
mirroring the Spring provider so the same obligation narrows identically on every SAPL
Mongo PEP. Two shapes, combinable, narrowing-only (criteria and conditions are AND-merged
into the user's filter, never widening it):

```json
{
  "type": "mongo:queryRewriting",
  "criteria": [
    {"column": "tenantId", "op": "=", "value": 7},
    {"or": [{"column": "ownerId", "op": "=", "value": "alice"},
            {"column": "public", "op": "=", "value": true}]}
  ],
  "conditions": ["{\"age\": {\"$gte\": 18}}"]
}
```

`criteria` ops: `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `isNull`, `isNotNull`; `and` / `or`
group nested criteria. `conditions` carries raw filter fragments for operators the typed
form cannot express (`$regex`, `$exists`, `$geoWithin`); for cross-PEP portability the
strings must be double-quoted (extended) JSON. An aggregation pipeline cannot be expressed
by this contract, so a pipeline intercept fails closed, as does a malformed condition.

## Usage

```python
from sapl_pymongo import MongoDbQueryRewritingProvider, wrap_collection

# At startup: wrap each collection once (this also registers the shim with the planner).
widgets = wrap_collection(database["widgets"])

# Register the provider with the EnforcementPlanner that backs your framework wrapper.
# providers=(MongoDbQueryRewritingProvider(),)

# In a @pre_enforce-protected handler, query the wrapped collection as usual; a
# mongo:queryRewriting obligation on the decision narrows the filter automatically.
```
