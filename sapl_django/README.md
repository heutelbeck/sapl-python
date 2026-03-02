# sapl-django

SAPL Policy Enforcement Point (PEP) integration for Django 5. Provides decorator-based authorization for views backed by the SAPL PDP.

## Installation

```
pip install sapl-django
```

## Quick Setup

### 1. Configure settings

Add `sapl_django` to `INSTALLED_APPS` and provide the PDP connection settings:

```python
INSTALLED_APPS = [
    "sapl_django",
    ...
]

MIDDLEWARE = [
    "sapl_django.middleware.SaplRequestMiddleware",
    ...
]

SAPL_CONFIG = {
    "base_url": "https://localhost:8443",
    "token": "pdp-secret",
}
```

`SaplRequestMiddleware` propagates the current request via context variables so the subscription builder can read the request subject and action automatically.

### 2. Protect views

```python
from django.http import JsonResponse
from sapl_django.decorators import pre_enforce, post_enforce

@pre_enforce(action="read", resource="patient")
async def get_patient(request, patient_id):
    return JsonResponse({"id": patient_id, "name": "Alice"})

@post_enforce(action="list", resource="records")
async def list_records(request):
    return JsonResponse([{"id": 1}, {"id": 2}], safe=False)
```

`@pre_enforce` queries the PDP before the view executes. A DENY decision raises `django.core.exceptions.PermissionDenied`. `@post_enforce` runs the view first, then includes the return value in the PDP subscription for filtering or replacement.

## Streaming Enforcement

For streaming views using Django's `StreamingHttpResponse`:

```python
from sapl_django.decorators import enforce_till_denied

@enforce_till_denied(action="subscribe", resource="heartbeat")
async def heartbeat(request):
    async def generator():
        import asyncio
        while True:
            yield {"beat": True}
            await asyncio.sleep(1)
    return generator()
```

Available streaming strategies: `enforce_till_denied`, `enforce_drop_while_denied`, `enforce_recoverable_if_denied`.

## Documentation and Demo

- Documentation: [sapl.io/docs](https://sapl.io/docs/latest/8_1_PEPImplementationSpecification/)
- Demo with medical records domain, JWT, and async views: [sapl-python-demos/django_demo](https://github.com/heutelbeck/sapl-python-demos/tree/main/django_demo)
