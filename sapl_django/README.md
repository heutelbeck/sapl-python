# sapl-django

Policy-based authorization for Django. Write access control rules as external SAPL policy files and enforce them at runtime through decorators like `@pre_enforce` and `@post_enforce`. Policies can be updated without code changes or redeployment.

## How It Works

Your application decorates views with enforcement decorators. SAPL intercepts the call, sends an authorization subscription to the Policy Decision Point (PDP), and enforces the decision, including any obligations or advice the policy attaches.

```python
@pre_enforce(action="read", resource="patient")
async def get_patient(request, patient_id):
    return JsonResponse({"id": patient_id, "name": "Jane Doe", "ssn": "123-45-6789"})
```

```
policy "permit doctors to read patient data"
permit
  action == "read"
where
  "DOCTOR" in subject.roles;
```

If the PDP permits, the view runs. If not, `PermissionDenied` is raised. If the decision carries obligations (like access logging or field redaction), they are enforced automatically through registered constraint handlers.

## What You Get

SAPL goes beyond simple permit/deny. Decisions can carry obligations that must be fulfilled, advice that should be attempted, and resource transformations that modify return values before they reach the caller. The library handles all of this transparently.

For streaming views, streaming decorators (`@enforce_till_denied`, `@enforce_drop_while_denied`, `@enforce_recoverable_if_denied`) maintain a live connection to the PDP, so access rights update in real time as policies, attributes, or the environment change. Built-in constraint handlers cover JSON field redaction and collection filtering. Writing custom handlers follows a simple registration pattern via Django app configuration.

## Getting Started

```bash
pip install sapl-django
```

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
}
```

For setup instructions, configuration options, the constraint handler reference, and the full API, see the [Django documentation](https://sapl.io/docs/latest/6_6_PythonDjango/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [Django Integration](https://sapl.io/docs/latest/6_6_PythonDjango/)
- [Demo Application](https://github.com/heutelbeck/sapl-python-demos/tree/main/django_demo)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
