# sapl-django

Policy-based authorization for Django. Write access control rules as external SAPL policy files and enforce them at runtime through decorators like `@pre_enforce` and `@post_enforce`. Policies can be updated without code changes or redeployment.

Built on [sapl-base](https://pypi.org/project/sapl-base/) and the SAPL 4.1 enforcement model: planner-driven constraint handling, the `SUSPEND` decision verb, an optional RSocket transport, and transaction rollback on post-write denial. Data-layer query rewriting is available via [sapl-sqlalchemy](https://pypi.org/project/sapl-sqlalchemy/) (SQL) and [sapl-pymongo](https://pypi.org/project/sapl-pymongo/) (MongoDB).

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
  action == "read";
  "DOCTOR" in subject.roles
```

If the PDP permits, the view runs. If not, `PermissionDenied` is raised. If the decision carries obligations (like access logging or field redaction), they are enforced automatically through registered constraint handlers.

## What You Get

SAPL goes beyond simple permit/deny. Decisions can carry obligations that must be fulfilled, advice that should be attempted, and resource transformations that modify return values before they reach the caller. The library handles all of this transparently.

For streaming views, the single `stream_enforce` decorator maintains a live connection to the PDP, so access rights update in real time as policies, attributes, or the environment change. Built-in constraint handlers cover JSON field redaction and collection filtering. Writing custom handlers follows a simple registration pattern with `register_provider`.

## Database Transactions

If you configure a transaction provider, a denial that lands after the view has written to the database rolls the transaction back. Three triggers cause a rollback: a `post_enforce` DENY, a `post_enforce` output-obligation failure, and a `pre_enforce` output-obligation failure (the pre-decision permits, but its output obligations run after the method writes). A clean permit commits. It is opt-in: with no provider set, the PEP owns no transaction.

`transaction.atomic` is synchronous, so wrap it with `from_sync_context`:

```python
from django.db import transaction
from sapl_base.pep import from_sync_context
from sapl_django.config import set_transaction_provider

set_transaction_provider(from_sync_context(transaction.atomic))
```

A sync SQLAlchemy `session.begin` is wrapped the same way: `from_sync_context(lambda: get_current_session().begin())`.

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

For setup instructions, configuration options, the constraint handler reference, and the full API, see the [Django documentation](https://sapl.io/docs/latest/6_5_Django/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [Django Integration](https://sapl.io/docs/latest/6_5_Django/)
- [Demo Application](https://github.com/heutelbeck/sapl-python-demos/tree/main/django_demo)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
