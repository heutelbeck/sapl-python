# sapl-tornado

Policy-based authorization for Tornado. Write access control rules as external SAPL policy files and enforce them at runtime through decorators like `@pre_enforce` and `@post_enforce`. Policies can be updated without code changes or redeployment.

Built on [sapl-base](https://pypi.org/project/sapl-base/) and the SAPL 4.1 enforcement model: planner-driven constraint handling, the `SUSPEND` decision verb, an optional RSocket transport, and transaction rollback on post-write denial. Data-layer query rewriting is available via [sapl-sqlalchemy](https://pypi.org/project/sapl-sqlalchemy/) (SQL) and [sapl-pymongo](https://pypi.org/project/sapl-pymongo/) (MongoDB).

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
  action == "read";
  "DOCTOR" in subject.roles
```

If the PDP permits, the handler runs. If not, HTTP 403 is returned. If the decision carries obligations (like access logging or field redaction), they are enforced automatically through registered constraint handlers.

## What You Get

SAPL goes beyond simple permit/deny. Decisions can carry obligations that must be fulfilled, advice that should be attempted, and resource transformations that modify return values before they reach the caller. The library handles all of this transparently.

For SSE endpoints, the single `stream_enforce` decorator maintains a live connection to the PDP, so access rights update in real time as policies, attributes, or the environment change. Built-in constraint handlers cover JSON field redaction and collection filtering. Writing custom handlers follows a simple registration pattern with `register_provider`.

## Database Transactions

If you configure a transaction provider, a denial that lands after the handler has written to the database rolls the transaction back. Three triggers cause a rollback: a `post_enforce` DENY, a `post_enforce` output-obligation failure, and a `pre_enforce` output-obligation failure (the pre-decision permits, but its output obligations run after the method writes). A clean permit commits. It is opt-in: with no provider set, the PEP owns no transaction.

With an async SQLAlchemy session, pass `session.begin()` directly:

```python
from sapl_tornado.dependencies import set_transaction_provider

set_transaction_provider(lambda: get_current_session().begin())
```

The factory should resolve the current request's session. For a sync session or `transaction.atomic`, wrap it with `from_sync_context` from `sapl_base.pep`.

## Getting Started

```bash
pip install sapl-tornado
```

```python
import tornado.ioloop
import tornado.web
from sapl_tornado import SaplConfig
from sapl_tornado.dependencies import configure_sapl, cleanup_sapl

configure_sapl(SaplConfig(base_url="https://localhost:8443"))

app = tornado.web.Application([...])
app.listen(8888)
tornado.ioloop.IOLoop.current().start()
```

For setup instructions, configuration options, the constraint handler reference, and the full API, see the [Tornado documentation](https://sapl.io/docs/latest/6_8_Tornado/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [Tornado Integration](https://sapl.io/docs/latest/6_8_Tornado/)
- [Demo Application](https://github.com/heutelbeck/sapl-python-demos/tree/main/tornado_demo)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
