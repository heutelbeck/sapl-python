# sapl-flask

Policy-based authorization for Flask. Write access control rules as external SAPL policy files and enforce them at runtime through decorators like `@pre_enforce` and `@post_enforce`. Policies can be updated without code changes or redeployment.

## How It Works

Your application decorates view functions with enforcement decorators. SAPL intercepts the call, sends an authorization subscription to the Policy Decision Point (PDP), and enforces the decision, including any obligations or advice the policy attaches.

```python
@app.get("/patient/<patient_id>")
@pre_enforce(action="read", resource="patient")
def get_patient(patient_id):
    return {"id": patient_id, "name": "Jane Doe", "ssn": "123-45-6789"}
```

```
policy "permit doctors to read patient data"
permit
  action == "read";
  "DOCTOR" in subject.roles
```

If the PDP permits, the view runs. If not, HTTP 403 is returned. If the decision carries obligations (like access logging or field redaction), they are enforced automatically through registered constraint handlers.

## What You Get

SAPL goes beyond simple permit/deny. Decisions can carry obligations that must be fulfilled, advice that should be attempted, and resource transformations that modify return values before they reach the caller. The library handles all of this transparently.

For SSE endpoints, the single `stream_enforce` decorator maintains a live connection to the PDP, so access rights update in real time as policies, attributes, or the environment change. Built-in constraint handlers cover JSON field redaction and collection filtering. Writing custom handlers follows a simple registration pattern with `register_provider` on the `SaplFlask` extension.

## Database Transactions

If you configure a transaction provider, a denial that lands after the view has written to the database rolls the transaction back. Three triggers cause a rollback: a `post_enforce` DENY, a `post_enforce` output-obligation failure, and a `pre_enforce` output-obligation failure (the pre-decision permits, but its output obligations run after the method writes). A clean permit commits. It is opt-in: with no provider set, the PEP owns no transaction.

`set_transaction_provider` is a method on the extension. Flask views are synchronous, so wrap a sync session or `transaction.atomic` with `from_sync_context`:

```python
from sapl_base.pep import from_sync_context

sapl = SaplFlask(app)
sapl.set_transaction_provider(from_sync_context(lambda: get_current_session().begin()))
```

The factory should resolve the current request's session. With an async SQLAlchemy session you can pass the async scope directly: `sapl.set_transaction_provider(lambda: get_current_session().begin())`.

## Getting Started

```bash
pip install sapl-flask
```

```python
from flask import Flask
from sapl_flask.extension import SaplFlask
from sapl_flask.decorators import pre_enforce

app = Flask(__name__)
app.config["SAPL_BASE_URL"] = "https://localhost:8443"

sapl = SaplFlask(app)
```

For setup instructions, configuration options, the constraint handler reference, and the full API, see the [Flask documentation](https://sapl.io/docs/latest/6_6_Flask/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [Flask Integration](https://sapl.io/docs/latest/6_6_Flask/)
- [Demo Application](https://github.com/heutelbeck/sapl-python-demos/tree/main/flask_demo)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
