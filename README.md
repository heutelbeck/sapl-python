# SAPL Python PEP Libraries

Policy Enforcement Point (PEP) implementations for Python web frameworks, built on the [SAPL](https://sapl.io) authorization engine.

## Packages

| Package | Description | PyPI |
|---------|-------------|------|
| sapl-base | Core PEP library | [sapl-base](https://pypi.org/project/sapl-base/) |
| sapl-fastapi | FastAPI integration | [sapl-fastapi](https://pypi.org/project/sapl-fastapi/) |
| sapl-django | Django integration | [sapl-django](https://pypi.org/project/sapl-django/) |
| sapl-flask | Flask integration | [sapl-flask](https://pypi.org/project/sapl-flask/) |

## Quick Start

Install the package for your framework:

```
pip install sapl-fastapi
pip install sapl-django
pip install sapl-flask
```

Connect to a SAPL PDP and protect an endpoint:

```python
# FastAPI example
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from sapl_fastapi.config import SaplConfig
from sapl_fastapi.dependencies import configure_sapl, cleanup_sapl
from sapl_fastapi.decorators import pre_enforce

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_sapl(SaplConfig(base_url="https://localhost:8443", token="secret"))
    yield
    await cleanup_sapl()

app = FastAPI(lifespan=lifespan)

@app.get("/data")
@pre_enforce(action="read", resource="data")
async def get_data(request: Request):
    return {"data": "sensitive"}
```

On a DENY decision, the endpoint returns HTTP 403. Obligations attached to PERMIT decisions are executed automatically by the constraint engine.

## Requirements

- Python 3.12+
- A running SAPL PDP server (see [sapl.io](https://sapl.io) for setup)

## Development

Clone the repository and install all packages in editable mode:

```
git clone https://github.com/heutelbeck/sapl-python.git
cd sapl-python
python -m venv .venv
source .venv/bin/activate
pip install -e sapl_base -e sapl_fastapi -e sapl_django -e sapl_flask
```

Run tests for a specific package:

```
cd sapl_base && pytest
cd sapl_fastapi && pytest
cd sapl_django && pytest
cd sapl_flask && pytest
```

## License

Apache 2.0

## Documentation

Full documentation is available at [sapl.io/docs](https://sapl.io/docs/latest/8_1_PEPImplementationSpecification/).
