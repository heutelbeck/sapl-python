# sapl-fastapi

SAPL Policy Enforcement Point (PEP) integration for FastAPI. Provides decorator-based authorization for endpoints and streaming routes backed by the SAPL PDP.

## Installation

```
pip install sapl-fastapi
```

## Quick Setup

Configure SAPL in your application lifespan and apply enforcement decorators to your routes:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from sapl_fastapi.config import SaplConfig
from sapl_fastapi.dependencies import configure_sapl, cleanup_sapl
from sapl_fastapi.decorators import pre_enforce, post_enforce

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_sapl(SaplConfig(
        base_url="https://localhost:8443",
        token="pdp-secret",
    ))
    yield
    await cleanup_sapl()

app = FastAPI(lifespan=lifespan)

@app.get("/patient/{patient_id}")
@pre_enforce(action="read", resource="patient")
async def get_patient(request: Request, patient_id: str):
    return {"id": patient_id, "name": "Alice", "ssn": "123-45-6789"}

@app.get("/records")
@post_enforce(action="list", resource="records")
async def list_records(request: Request):
    return [{"id": 1, "classification": "PUBLIC"}, {"id": 2, "classification": "RESTRICTED"}]
```

`@pre_enforce` queries the PDP before the endpoint executes. If the decision is DENY, HTTP 403 is returned. If PERMIT, any obligations (such as content filtering) are enforced automatically before the response is sent.

`@post_enforce` runs the endpoint first, then includes the return value in the PDP subscription. The PDP can filter or replace the response via obligations.

## Streaming Enforcement

For Server-Sent Events routes, use the streaming decorators:

```python
from sapl_fastapi.decorators import enforce_till_denied, enforce_drop_while_denied

@app.get("/stream/heartbeat")
@enforce_till_denied(action="subscribe", resource="heartbeat")
async def heartbeat(request: Request):
    async def generator():
        import asyncio
        while True:
            yield {"beat": True}
            await asyncio.sleep(1)
    return generator()
```

Available streaming strategies:

- `enforce_till_denied` - stream terminates permanently on first DENY
- `enforce_drop_while_denied` - items are silently dropped during DENY, stream resumes on PERMIT
- `enforce_recoverable_if_denied` - DENY/PERMIT transitions trigger optional callbacks; stream continues

## Documentation and Demo

- Documentation: [sapl.io/docs](https://sapl.io/docs/latest/8_1_PEPImplementationSpecification/)
- Full-featured demo with JWT, streaming, and all constraint types: [sapl-python-demos/fastapi_demo](https://github.com/heutelbeck/sapl-python-demos/tree/main/fastapi_demo)
