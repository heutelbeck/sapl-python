# sapl-flask

SAPL Policy Enforcement Point (PEP) integration for Flask. Provides decorator-based authorization for view functions backed by the SAPL PDP.

## Installation

```
pip install sapl-flask
```

## Quick Setup

Initialize the `SaplFlask` extension with your application and apply enforcement decorators to your routes:

```python
from flask import Flask
from sapl_flask.extension import SaplFlask
from sapl_flask.decorators import pre_enforce, post_enforce

app = Flask(__name__)
app.config["SAPL_BASE_URL"] = "https://localhost:8443"
app.config["SAPL_TOKEN"] = "pdp-secret"

sapl = SaplFlask(app)

@app.get("/patient/<patient_id>")
@pre_enforce(action="read", resource="patient")
def get_patient(patient_id):
    return {"id": patient_id, "name": "Alice"}

@app.get("/records")
@post_enforce(action="list", resource="records")
def list_records():
    return [{"id": 1, "classification": "PUBLIC"}, {"id": 2, "classification": "RESTRICTED"}]
```

`@pre_enforce` queries the PDP before the view executes. A DENY decision aborts the request with HTTP 403. `@post_enforce` runs the view first, then includes the return value in the PDP subscription so the PDP can filter or replace the response via obligations.

The application factory pattern is also supported:

```python
sapl = SaplFlask()

def create_app():
    app = Flask(__name__)
    app.config["SAPL_BASE_URL"] = "https://localhost:8443"
    app.config["SAPL_TOKEN"] = "pdp-secret"
    sapl.init_app(app)
    return app
```

## Configuration

All settings are read from `app.config`:

| Key | Default | Description |
|-----|---------|-------------|
| `SAPL_BASE_URL` | `https://localhost:8443` | PDP server URL |
| `SAPL_TOKEN` | None | Bearer token |
| `SAPL_USERNAME` | None | Basic auth username |
| `SAPL_PASSWORD` | None | Basic auth password |
| `SAPL_TIMEOUT` | `5.0` | Request timeout in seconds |
| `SAPL_ALLOW_INSECURE_CONNECTIONS` | `False` | Allow HTTP (non-TLS) connections |

## Streaming Enforcement

For Server-Sent Events routes:

```python
from sapl_flask.decorators import enforce_till_denied

@app.get("/stream/heartbeat")
@enforce_till_denied(action="subscribe", resource="heartbeat")
def heartbeat():
    def generator():
        import time
        while True:
            yield {"beat": True}
            time.sleep(1)
    return generator()
```

Available streaming strategies: `enforce_till_denied`, `enforce_drop_while_denied`, `enforce_recoverable_if_denied`.

## Documentation and Demo

- Documentation: [sapl.io/docs](https://sapl.io/docs/latest/8_1_PEPImplementationSpecification/)
- Minimal integration example: [sapl-python-demos/flask_demo](https://github.com/heutelbeck/sapl-python-demos/tree/main/flask_demo)
