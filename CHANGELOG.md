# Changelog

## 4.1.0

Brings the Python PEP libraries to the SAPL 4.1 enforcement model.
Constraint handling now uses a planner that binds handlers to lifecycle
signals. Adds the `SUSPEND` decision verb, the RSocket transport,
library-owned transaction rollback on post-write denial, and data-layer
query rewriting.

### Added

- **Planner-based constraint enforcement.** An enforcement planner binds
  constraint handlers to lifecycle signals, resolving which provider claims
  each obligation and failing closed on an unresolved, ambiguous, or
  inadmissible obligation.
- **`SUSPEND` decision verb** (new in SAPL 4.1.0). A streaming subscription
  pauses while suspended and resumes on the next `PERMIT`, rather than
  terminating.
- **RSocket transport** for the PDP client as an alternative to HTTP.
- **Library-owned transaction boundary.** A post-write denial rolls back the
  surrounding transaction: PostEnforce `DENY`, a PostEnforce output-obligation
  failure, and a PreEnforce output-obligation failure (permit before the
  method, but output obligations run after it writes). Opt in with
  `set_transaction_provider`; unset, the PEP owns no transaction.
- **Data-layer query rewriting.** A `sql:queryRewriting` or
  `mongo:queryRewriting` obligation narrows the queries an
  enforced method issues, fail-closed and narrowing-only. New packages
  `sapl-sqlalchemy` (SQLAlchemy) and `sapl-pymongo` (PyMongo), plus a Django
  ORM provider in `sapl-django`.

### Notes

- The query-rewriting obligation format is identical across every SAPL PEP
  for a backend, so the same obligation works unchanged on the Spring,
  NestJS, and Python integrations. See the Query Rewriting documentation.
