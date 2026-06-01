# sapl-base

Core SAPL Policy Enforcement Point (PEP) library for Python. Provides the async PDP client, constraint enforcement engine, and enforcement primitives used by the framework integrations ([sapl-flask](https://pypi.org/project/sapl-flask/), [sapl-django](https://pypi.org/project/sapl-django/), [sapl-fastapi](https://pypi.org/project/sapl-fastapi/)).

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
