"""End-to-end PEP integration test against a real SAPL Node.

A policy emits a `filterJsonContent` obligation; the
`ContentFilteringProvider` registered with the planner applies it
to the method's return value; the caller sees the redacted output.

This is the load-bearing proof that the connector + plan + planner
+ content filter migration all work end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sapl_base.pep import (
    AccessDeniedError,
    EnforcementPlanner,
    pre_enforce,
)
from sapl_base.pep.filters import ContentFilteringProvider
from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions
from sapl_base.types import AuthorizationSubscription

from tests.integration.conftest import (
    _free_port,
    _start_sapl_node,
    _stop_container,
    _wait_for_pdp_ready,
)


@pytest.fixture
def redact_ssn_policies(tmp_path: Path) -> Path:
    """Policy: PERMIT read action with a filterJsonContent obligation blackening $.ssn."""
    policies = tmp_path / "policies"
    policies.mkdir()
    (policies / "pdp.json").write_text(
        '{"algorithm": {"votingMode": "PRIORITY_PERMIT", '
        '"defaultDecision": "DENY", "errorHandling": "ABSTAIN"}, '
        '"variables": {}}\n'
    )
    (policies / "permit-read-redacted.sapl").write_text(
        'policy "permit-read-redacted"\n'
        'permit\n'
        '  action == "read";\n'
        'obligation\n'
        '  {\n'
        '    "type": "filterJsonContent",\n'
        '    "actions": [\n'
        '      {"type": "blacken", "path": "$.ssn", "discloseRight": 4}\n'
        '    ]\n'
        '  }\n'
    )
    return policies


@pytest.fixture
def sapl_node_for_pep_e2e(redact_ssn_policies: Path):
    port = _free_port()
    container_id = _start_sapl_node(
        policies_dir=redact_ssn_policies,
        env={
            "SERVER_SSL_ENABLED": "false",
            "SERVER_PORT": "8443",
            "SERVER_ADDRESS": "0.0.0.0",
            "IO_SAPL_NODE_ALLOWNOAUTH": "true",
            "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
            "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
        },
        http_port=port,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_pdp_ready(base_url, timeout_seconds=60.0)
        yield base_url
    finally:
        _stop_container(container_id)


@pytest.mark.asyncio
async def test_pre_enforce_with_content_filter_redacts_output(
    sapl_node_for_pep_e2e: str,
) -> None:
    """End-to-end: PDP returns PERMIT + filterJsonContent obligation, the
    provider applies it to the method's return value, the caller sees the
    redacted payload."""
    client = HttpPdpClient(HttpPdpClientOptions(base_url=sapl_node_for_pep_e2e))
    planner = EnforcementPlanner(providers=[ContentFilteringProvider()])

    async def _get_patient() -> dict[str, str]:
        return {"name": "Jane Doe", "ssn": "123-45-6789"}

    try:
        result = await pre_enforce(
            _get_patient,
            pdp_client=client,
            planner=planner,
            subscription=AuthorizationSubscription(
                subject="clinician", action="read", resource="patient"
            ),
        )
    finally:
        await client.close()

    assert result["name"] == "Jane Doe"
    assert result["ssn"].endswith("6789")
    assert result["ssn"].startswith("X")


@pytest.mark.asyncio
async def test_pre_enforce_denied_when_action_does_not_match(
    sapl_node_for_pep_e2e: str,
) -> None:
    """Wrong action -> the policy does not apply -> default deny -> AccessDeniedError."""
    client = HttpPdpClient(HttpPdpClientOptions(base_url=sapl_node_for_pep_e2e))
    planner = EnforcementPlanner(providers=[ContentFilteringProvider()])

    async def _delete_patient() -> dict[str, str]:
        return {"name": "Jane"}

    try:
        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                _delete_patient,
                pdp_client=client,
                planner=planner,
                subscription=AuthorizationSubscription(
                    subject="clinician", action="delete", resource="patient"
                ),
            )
    finally:
        await client.close()
