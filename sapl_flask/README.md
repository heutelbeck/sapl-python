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
  action == "read"
where
  "DOCTOR" in subject.roles;
```

If the PDP permits, the view runs. If not, HTTP 403 is returned. If the decision carries obligations (like access logging or field redaction), they are enforced automatically through registered constraint handlers.

## What You Get

SAPL goes beyond simple permit/deny. Decisions can carry obligations that must be fulfilled, advice that should be attempted, and resource transformations that modify return values before they reach the caller. The library handles all of this transparently.

For SSE endpoints, streaming decorators (`@enforce_till_denied`, `@enforce_drop_while_denied`, `@enforce_recoverable_if_denied`) maintain a live connection to the PDP, so access rights update in real time as policies, attributes, or the environment change. Built-in constraint handlers cover JSON field redaction and collection filtering. Writing custom handlers follows a simple registration pattern with the `SaplFlask` extension.

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

For setup instructions, configuration options, the constraint handler reference, and the full API, see the [Flask documentation](https://sapl.io/docs/latest/6_7_PythonFlask/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [Flask Integration](https://sapl.io/docs/latest/6_7_PythonFlask/)
- [Demo Application](https://github.com/heutelbeck/sapl-python-demos/tree/main/flask_demo)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
