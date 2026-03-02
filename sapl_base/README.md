# sapl-base

Core SAPL Policy Enforcement Point (PEP) library for Python. Provides the async PDP client, constraint enforcement engine, and enforcement primitives used by the framework integrations ([sapl-flask](https://pypi.org/project/sapl-flask/), [sapl-django](https://pypi.org/project/sapl-django/), [sapl-fastapi](https://pypi.org/project/sapl-fastapi/)).

## How It Works

Your application sends authorization subscriptions to the Policy Decision Point (PDP) and enforces the decision. The PDP evaluates SAPL policies and returns permit/deny decisions with optional obligations, advice, and resource transformations.

```python
from sapl_base.pdp_client import PdpClient, PdpConfig
from sapl_base.types import AuthorizationSubscription

client = PdpClient(PdpConfig(base_url="https://localhost:8443"))
decision = await client.decide_once(AuthorizationSubscription(
    subject={"user": "alice", "roles": ["DOCTOR"]},
    action="read",
    resource="patient-record",
))
print(decision.decision)  # PERMIT, DENY, INDETERMINATE, or NOT_APPLICABLE
```

```
policy "permit doctors to read patient data"
permit
  action == "read"
where
  "DOCTOR" in subject.roles;
```

For streaming decisions that update as policies change:

```python
async for decision in client.decide(subscription):
    print(decision.decision)
```

## What You Get

- Async HTTP client for all PDP REST endpoints (`decide-once`, `decide`, `multi-decide-once`, `multi-decide`, `multi-decide-all-once`, `multi-decide-all`)
- Streaming SSE subscriptions with automatic reconnect and exponential backoff
- Constraint enforcement engine with seven handler types (runnable, consumer, mapping, filter predicate, error handler, error mapping, method invocation)
- Built-in content filtering via `filterJsonContent` (blacken, delete, replace)
- Pre-enforce and post-enforce primitives for request/response authorization
- Three streaming enforcement strategies: enforce-till-denied, enforce-drop-while-denied, enforce-recoverable-if-denied
- Bearer token and HTTP basic auth support; HTTPS by default

Most applications should use a framework integration instead of this package directly.

## Getting Started

```bash
pip install sapl-base
```

For the PEP implementation specification and constraint handler reference, see the [PEP documentation](https://sapl.io/docs/latest/8_1_PEPImplementationSpecification/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [PEP Implementation Specification](https://sapl.io/docs/latest/8_1_PEPImplementationSpecification/)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
