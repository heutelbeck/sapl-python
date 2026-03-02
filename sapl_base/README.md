# sapl-base

Core SAPL Policy Enforcement Point (PEP) library for Python. Provides the PDP client, constraint enforcement engine, and enforcement primitives used by the framework-specific integrations.

## Installation

```
pip install sapl-base
```

## Features

- Async HTTP client for the SAPL PDP REST API (`decide-once`, `decide`, `multi-decide-once`, `multi-decide`, `multi-decide-all-once`, `multi-decide-all`)
- Streaming SSE subscriptions with automatic reconnect and exponential backoff
- Constraint enforcement engine with seven constraint handler types (runnable, consumer, mapping, filter predicate, error handler, error mapping, method invocation)
- Built-in content filtering via `filterJsonContent` (blacken, delete, replace)
- Pre-enforce and post-enforce primitives for request/response authorization
- Three streaming enforcement strategies: enforce-till-denied, enforce-drop-while-denied, enforce-recoverable-if-denied
- Bearer token and HTTP basic auth support; HTTPS by default

## Quick Example

```python
import asyncio
from sapl_base.pdp_client import PdpClient, PdpConfig
from sapl_base.types import AuthorizationSubscription

async def main():
    config = PdpConfig(
        base_url="https://localhost:8443",
        token="pdp-secret",
    )
    client = PdpClient(config)

    subscription = AuthorizationSubscription(
        subject={"user": "alice"},
        action="read",
        resource="patient-record",
    )

    decision = await client.decide_once(subscription)
    print(decision.decision)  # PERMIT, DENY, INDETERMINATE, or NOT_APPLICABLE

    await client.close()

asyncio.run(main())
```

For streaming decisions that update as policies change:

```python
async for decision in client.decide(subscription):
    print(decision.decision)
    # Decisions arrive whenever the PDP re-evaluates (e.g. policy reload)
```

## Documentation

Full documentation: [sapl.io/docs](https://sapl.io/docs/latest/8_1_PEPImplementationSpecification/)
