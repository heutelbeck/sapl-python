# sapl-fastapi

Policy-based authorization for FastAPI. Write access control rules as external SAPL policy files and enforce them at runtime through decorators like `@pre_enforce` and `@post_enforce`. Policies can be updated without code changes or redeployment.

## How It Works

Your application decorates endpoints with enforcement decorators. SAPL intercepts the call, sends an authorization subscription to the Policy Decision Point (PDP), and enforces the decision, including any obligations or advice the policy attaches.

```python
@app.get("/patient/{patient_id}")
@pre_enforce(action="read", resource="patient")
async def get_patient(request: Request, patient_id: str):
    return {"id": patient_id, "name": "Jane Doe", "ssn": "123-45-6789"}
```

```
policy "permit doctors to read patient data"
permit
  action == "read";
  "DOCTOR" in subject.roles
```

If the PDP permits, the endpoint runs. If not, HTTP 403 is returned. If the decision carries obligations (like access logging or field redaction), they are enforced automatically through registered constraint handlers.

## What You Get

SAPL goes beyond simple permit/deny. Decisions can carry obligations that must be fulfilled, advice that should be attempted, and resource transformations that modify return values before they reach the caller. The library handles all of this transparently.

For SSE endpoints, the single `stream_enforce` decorator maintains a live connection to the PDP, so access rights update in real time as policies, attributes, or the environment change. Built-in constraint handlers cover JSON field redaction and collection filtering. Writing custom handlers follows a simple registration pattern with `register_provider`.

## Database Transactions

If you configure a transaction provider, a denial that lands after the endpoint has written to the database rolls the transaction back. Three triggers cause a rollback: a `post_enforce` DENY, a `post_enforce` output-obligation failure, and a `pre_enforce` output-obligation failure (the pre-decision permits, but its output obligations run after the method writes). A clean permit commits. It is opt-in: with no provider set, the PEP owns no transaction.

With an async SQLAlchemy session, pass `session.begin()` directly:

```python
from sapl_fastapi.dependencies import set_transaction_provider

set_transaction_provider(lambda: get_current_session().begin())
```

The factory should resolve the current request's session, for example a request-scoped `AsyncSession` held in a contextvar. For a sync session or `transaction.atomic`, wrap it with `from_sync_context` from `sapl_base.pep`.

## Getting Started

```bash
pip install sapl-fastapi
```

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sapl_fastapi import SaplConfig
from sapl_fastapi.dependencies import configure_sapl, cleanup_sapl

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_sapl(SaplConfig(base_url="https://localhost:8443"))
    yield
    await cleanup_sapl()

app = FastAPI(lifespan=lifespan)
```

For setup instructions, configuration options, the constraint handler reference, and the full API, see the [FastAPI documentation](https://sapl.io/docs/latest/6_7_FastAPI/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [FastAPI Integration](https://sapl.io/docs/latest/6_7_FastAPI/)
- [Demo Application](https://github.com/heutelbeck/sapl-python-demos/tree/main/fastapi_demo)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
