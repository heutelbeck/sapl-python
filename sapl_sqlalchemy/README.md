# sapl-sqlalchemy

SAPL signal source for SQLAlchemy. Contributes the `SQL_QUERY` signal and a
`sql:queryRewriting` constraint handler provider so a SAPL policy can shape the
relational queries an application issues, the same way `sapl-pymongo`
contributes `MONGO_QUERY` for MongoDB queries.

SQLAlchemy exposes a mutating query hook, the `do_orm_execute` event on the
`Session`. The cut point is therefore a listener on the ORM session that
discharges `SQL_QUERY` with the statement before it executes and applies the
rewritten statement. Registering the listener attaches to the `Session` class,
so it covers every session, including `AsyncSession` through its sync-session
proxy.

## Obligation

`SqlQueryRewritingProvider` handles the `sql:queryRewriting` obligation (and its
`relational:queryRewriting` alias), mirroring the Spring provider so the same
obligation narrows identically on every SAPL SQL PEP. Narrowing-only (criteria
and conditions are AND-merged into the user's WHERE, never widening it):

```json
{
  "type": "sql:queryRewriting",
  "criteria": [
    {"column": "tenant_id", "op": "=", "value": 7},
    {"or": [{"column": "owner_id", "op": "=", "value": "alice"},
            {"column": "public", "op": "=", "value": true}]}
  ],
  "conditions": ["status IN ('active', 'pending')"],
  "columns": ["id", "name"]
}
```

`criteria` ops: `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `like`, `notLike`,
`isNull`, `isNotNull`; `and` / `or` group nested criteria. `conditions` carries
raw SQL fragments for features the typed form cannot express (`BETWEEN`,
`EXISTS`, vendor functions), and `columns` narrows the projection. A statement
that cannot carry a WHERE clause, a raw `text()` statement, or a malformed
criterion fails closed.

## Usage

```python
from sapl_sqlalchemy import SqlQueryRewritingProvider, register_orm_listener

# At startup: register the ORM listener once (this also registers the shim with
# the planner, so a sql:queryRewriting obligation is admissible).
register_orm_listener()

# Register the provider with the EnforcementPlanner that backs your framework
# wrapper: providers=(SqlQueryRewritingProvider(),)

# In a @pre_enforce-protected handler, query through the ORM session as usual; a
# sql:queryRewriting obligation on the decision narrows the statement automatically.
```

## Off-session access

Execution that bypasses the ORM session (SQLAlchemy Core `engine.execute()`, a
raw DBAPI cursor) never triggers the event, so no filter is applied. Once the
listener is registered the obligation is accepted, so off-session access is left
unfiltered rather than denied: you own row-level security manually for that path.
