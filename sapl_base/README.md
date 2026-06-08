# sapl-base

Core SAPL Policy Enforcement Point (PEP) library for Python. Provides the async PDP client, constraint enforcement engine, and enforcement primitives used by the framework integrations ([sapl-flask](https://pypi.org/project/sapl-flask/), [sapl-django](https://pypi.org/project/sapl-django/), [sapl-fastapi](https://pypi.org/project/sapl-fastapi/)).

Implements the SAPL 4.1 enforcement model: a planner that binds constraint handlers to lifecycle signals, the `SUSPEND` decision verb, an optional RSocket transport, and a library-owned transaction boundary that rolls back on post-write denial.

## How It Works

Your application sends authorization subscriptions to the Policy Decision Point (PDP) and enforces the decision. The PDP evaluates SAPL policies and returns permit/deny decisions with optional obligations, advice, and resource transformations.

```python
from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions
from sapl_base.types import AuthorizationSubscription

client = HttpPdpClient(HttpPdpClientOptions(base_url="https://localhost:8443"))
decision = await client.decide_once(AuthorizationSubscription(
    subject={"user": "alice", "roles": ["DOCTOR"]},
    action="read",
    resource="patient-record",
))
print(decision.decision)  # PERMIT, DENY, INDETERMINATE, NOT_APPLICABLE, or SUSPEND
```

```
policy "permit doctors to read patient data"
permit
  action == "read";
  "DOCTOR" in subject.roles
```

For streaming decisions that update as policies change:

```python
async for decision in client.decide(subscription):
    print(decision.decision)
```

## What You Get

- Async HTTP client for all PDP REST endpoints (`decide-once`, `decide`, `multi-decide`, `multi-decide-all`, `multi-decide-all-once`)
- Streaming SSE subscriptions with automatic reconnect and exponential backoff
- Constraint enforcement via a single `ConstraintHandlerProvider`, returning `ScopedHandler` entries whose shape is a runner (no value), a consumer (observes a value), or a mapper (transforms a value)
- Built-in content filtering via `filterJsonContent` (blacken, delete, replace)
- Pre-enforce and post-enforce primitives for request/response authorization
- Streaming enforcement through a single `stream_enforce` decorator backed by the `run_pipeline` engine
- Bearer token and HTTP basic auth support; HTTPS by default

Most applications should use a framework integration instead of this package directly.

## Database Transactions

One-shot enforcement can own a transaction boundary. When you configure a transaction provider, `pre_enforce` and `post_enforce` wrap the protected call plus enforcement in it, so a denial that lands after a DB write rolls the write back. The three triggers are a `post_enforce` DENY, a `post_enforce` output-obligation failure, and a `pre_enforce` output-obligation failure (the pre-decision permits, but its output obligations run after the method writes). A clean permit commits. This is opt-in: with no provider, the PEP owns no transaction and behaviour is unchanged.

A provider is a zero-arg factory returning an async context manager that commits on clean exit and rolls back on a propagated exception, exactly the semantics of SQLAlchemy `AsyncSession.begin()` and Django `transaction.atomic()`. The framework integrations expose `set_transaction_provider(provider)`. For a sync transaction boundary (sync SQLAlchemy `session.begin` or Django `transaction.atomic`), wrap it with `from_sync_context`:

```python
from sapl_base.pep import from_sync_context
```

The provider factory should resolve the current request's session or transaction.

## Getting Started

```bash
pip install sapl-base
```

For the decision-verb semantics and the unified enforcement model, see the [SAPL documentation](https://sapl.io/docs/latest/2_3_AuthorizationDecisions/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [Authorization Decisions](https://sapl.io/docs/latest/2_3_AuthorizationDecisions/)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
