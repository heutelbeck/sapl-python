# sapl-tornado

Policy-based authorization for Tornado. Write access control rules as external SAPL policy files and enforce them at runtime through decorators like `@pre_enforce` and `@post_enforce`. Policies can be updated without code changes or redeployment.

## How It Works

Your application decorates handler methods with enforcement decorators. SAPL intercepts the call, sends an authorization subscription to the Policy Decision Point (PDP), and enforces the decision, including any obligations or advice the policy attaches.

```python
class PatientHandler(tornado.web.RequestHandler):
    @pre_enforce(action="read", resource="patient")
    async def get(self, patient_id):
        return {"id": patient_id, "name": "Jane Doe", "ssn": "123-45-6789"}
```

```
policy "permit doctors to read patient data"
permit
  action == "read"
where
  "DOCTOR" in subject.roles;
```

If the PDP permits, the handler runs. If not, HTTP 403 is returned. If the decision carries obligations (like access logging or field redaction), they are enforced automatically through registered constraint handlers.

## What You Get

SAPL goes beyond simple permit/deny. Decisions can carry obligations that must be fulfilled, advice that should be attempted, and resource transformations that modify return values before they reach the caller. The library handles all of this transparently.

For SSE endpoints, streaming decorators (`@enforce_till_denied`, `@enforce_drop_while_denied`, `@enforce_recoverable_if_denied`) maintain a live connection to the PDP, so access rights update in real time as policies, attributes, or the environment change. Built-in constraint handlers cover JSON field redaction and collection filtering. Writing custom handlers follows a simple registration pattern with `register_constraint_handler`.

## Getting Started

```bash
pip install sapl-tornado
```

```python
import tornado.ioloop
import tornado.web
from sapl_tornado.config import SaplConfig
from sapl_tornado.dependencies import configure_sapl, cleanup_sapl

configure_sapl(SaplConfig(base_url="https://localhost:8443"))

app = tornado.web.Application([...])
app.listen(8888)
tornado.ioloop.IOLoop.current().start()
```

For setup instructions, configuration options, the constraint handler reference, and the full API, see the [Tornado documentation](https://sapl.io/docs/latest/6_9_PythonTornado/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [Tornado Integration](https://sapl.io/docs/latest/6_9_PythonTornado/)
- [Demo Application](https://github.com/heutelbeck/sapl-python-demos/tree/main/tornado_demo)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
