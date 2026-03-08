# sapl-fastmcp

Policy-based authorization for FastMCP servers. Write access control rules as external SAPL policy files and enforce them at runtime through middleware or per-component `auth=` callbacks. Policies can be updated without code changes or redeployment.

## How It Works

Two enforcement approaches are available. The **middleware** approach intercepts every tool call, resource read, and prompt get through `SAPLMiddleware`, giving you a single enforcement point for the entire server. The **per-component** approach uses `auth=sapl()` on individual tools, resources, and prompts for fine-grained control with decorator overrides.

### Middleware

```python
from fastmcp import FastMCP
from sapl_fastmcp import SAPLMiddleware, configure_sapl, get_pdp_client, get_constraint_service

configure_sapl(base_url="https://localhost:8443")
mcp = FastMCP("my-server")
mcp.add_middleware(SAPLMiddleware(get_pdp_client(), get_constraint_service()))
```

### Per-Component Auth

```python
from fastmcp import FastMCP
from sapl_fastmcp import sapl, pre_enforce, configure_sapl

configure_sapl(base_url="https://localhost:8443")
mcp = FastMCP("my-server")

@mcp.tool(auth=sapl())
@pre_enforce(action="query", resource="patients")
def query_patients(department: str) -> list[dict]:
    return [{"id": "P-001", "name": "Jane Doe"}]
```

If the PDP permits, the tool runs. If not, access is denied. If the decision carries obligations (like access logging or result filtering), they are enforced automatically through registered constraint handlers.

## Getting Started

```bash
pip install sapl-fastmcp
```

For setup instructions, configuration options, and the constraint handler reference, see the [FastMCP documentation](https://sapl.io/docs/latest/6_10_PythonFastMCP/).

## Links

- [Full Documentation](https://sapl.io/docs/latest/)
- [FastMCP Integration](https://sapl.io/docs/latest/6_10_PythonFastMCP/)
- [Demo Application](https://github.com/heutelbeck/sapl-python-demos/tree/main/fastmcp_demo)
- [Report an Issue](https://github.com/heutelbeck/sapl-python/issues)

## License

Apache-2.0
