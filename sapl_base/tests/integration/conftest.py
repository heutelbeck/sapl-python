"""Integration test fixtures spawning a real SAPL Node container.

Each fixture starts a fresh `ghcr.io/heutelbeck/sapl-node` container
configured for a specific transport / auth combination. Tests
select the fixture they need; the container is stopped at fixture
teardown.

If the configured image is not present locally the entire integration
suite skips.
"""

from __future__ import annotations

import socket
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

SAPL_NODE_IMAGE = "ghcr.io/heutelbeck/sapl-node:4.1.0-SNAPSHOT"


def _docker_image_present(image: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _wait_for_pdp_ready(base_url: str, timeout_seconds: float = 60.0) -> None:
    """Poll the PDP until it accepts a decision request.

    A bound TCP port is not enough: the listening socket may open
    seconds before the decision endpoint is wired. Probe with a
    real POST to `/api/pdp/decide-once` and accept any HTTP
    response as "ready" (only transport errors mean "not yet").
    """
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_seconds
    body = b'{"subject":"_","action":"_","resource":"_"}'
    request = urllib.request.Request(
        f"{base_url}/api/pdp/decide-once",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2.0):
                return
        except urllib.error.HTTPError:
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise TimeoutError(
        f"SAPL Node at {base_url} did not accept a decide request within {timeout_seconds}s"
    )


@pytest.fixture(scope="session", autouse=True)
def _require_sapl_node_image() -> None:
    if not _docker_image_present(SAPL_NODE_IMAGE):
        pytest.skip(
            f"Integration tests require {SAPL_NODE_IMAGE}. "
            "Build it via "
            "`mvn -f sapl-policy-engine/sapl-node/pom.xml spring-boot:build-image -DskipTests`."
        )


def _start_sapl_node(
    policies_dir: Path,
    env: dict[str, str],
    http_port: int,
    rsocket_port: int = 0,
    extra_volumes: list[str] | None = None,
) -> str:
    """Start a SAPL Node container; return the container id."""
    args = [
        "docker", "run", "-d",
        "-p", f"127.0.0.1:{http_port}:8443",
    ]
    if rsocket_port:
        args.extend(["-p", f"127.0.0.1:{rsocket_port}:7000"])
    args.extend(["-v", f"{policies_dir}:/pdp/data:ro"])
    if extra_volumes:
        for mount in extra_volumes:
            args.extend(["-v", mount])
    for key, value in env.items():
        args.extend(["-e", f"{key}={value}"])
    args.append(SAPL_NODE_IMAGE)
    container_id = subprocess.check_output(args, text=True).strip()
    return container_id


def _stop_container(container_id: str) -> None:
    subprocess.run(["docker", "rm", "-f", container_id], check=False, capture_output=True)


@pytest.fixture
def permit_all_policies(tmp_path: Path) -> Path:
    """Tiny policy set: PERMIT everything. Just enough to drive an end-to-end decision."""
    policies = tmp_path / "policies"
    policies.mkdir()
    (policies / "pdp.json").write_text(
        '{"algorithm": {"votingMode": "PRIORITY_PERMIT", '
        '"defaultDecision": "DENY", "errorHandling": "ABSTAIN"}, '
        '"variables": {}}\n'
    )
    (policies / "permit-all.sapl").write_text(
        'policy "permit-all"\npermit\n'
    )
    return policies


@pytest.fixture
def sapl_node_http_noauth(
    permit_all_policies: Path,
) -> Generator[str, None, None]:
    """Run a SAPL Node with HTTP no-auth on a free port. Yields the base URL."""
    port = _free_port()
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
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


@pytest.fixture
def sapl_node_rsocket_basic(
    permit_all_policies: Path,
) -> Generator[tuple[str, int], None, None]:
    """SAPL Node with HTTP+RSocket basic auth. Yields (rsocket_host, rsocket_port)."""
    http_port = _free_port()
    rsocket_port = _free_port()
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env={
            "SERVER_SSL_ENABLED": "false",
            "SERVER_PORT": "8443",
            "SERVER_ADDRESS": "0.0.0.0",
            "IO_SAPL_NODE_ALLOWNOAUTH": "false",
            "IO_SAPL_NODE_ALLOWBASICAUTH": "true",
            "IO_SAPL_NODE_USERS_0_ID": "basic-tester",
            "IO_SAPL_NODE_USERS_0_PDPID": "default",
            "IO_SAPL_NODE_USERS_0_BASIC_USERNAME": BASIC_USER,
            "IO_SAPL_NODE_USERS_0_BASIC_SECRET": _argon2_hash(BASIC_SECRET),
            "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
            "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
        },
        http_port=http_port,
        rsocket_port=rsocket_port,
    )
    base_url = f"http://127.0.0.1:{http_port}"
    try:
        _wait_for_pdp_ready_with_basic(base_url, BASIC_USER, BASIC_SECRET, timeout_seconds=60.0)
        yield "127.0.0.1", rsocket_port
    finally:
        _stop_container(container_id)


@pytest.fixture
def sapl_node_rsocket_apikey(
    permit_all_policies: Path,
) -> Generator[tuple[str, int], None, None]:
    """SAPL Node with HTTP+RSocket API-key auth. Yields (rsocket_host, rsocket_port)."""
    http_port = _free_port()
    rsocket_port = _free_port()
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env={
            "SERVER_SSL_ENABLED": "false",
            "SERVER_PORT": "8443",
            "SERVER_ADDRESS": "0.0.0.0",
            "IO_SAPL_NODE_ALLOWNOAUTH": "false",
            "IO_SAPL_NODE_ALLOWAPIKEYAUTH": "true",
            "IO_SAPL_NODE_USERS_0_ID": "apikey-tester",
            "IO_SAPL_NODE_USERS_0_PDPID": "default",
            "IO_SAPL_NODE_USERS_0_APIKEYID": API_KEY_ID,
            "IO_SAPL_NODE_USERS_0_APIKEY": _argon2_hash(API_KEY_PLAIN),
            "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
            "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
        },
        http_port=http_port,
        rsocket_port=rsocket_port,
    )
    base_url = f"http://127.0.0.1:{http_port}"
    try:
        _wait_for_pdp_ready_with_bearer(base_url, API_KEY_PLAIN, timeout_seconds=60.0)
        yield "127.0.0.1", rsocket_port
    finally:
        _stop_container(container_id)


@pytest.fixture(scope="session")
def self_signed_tls_pair(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str | bytes]:
    """Generate a self-signed cert / key pair for localhost.

    The returned dict carries the PEM bytes (for in-process use
    via `TlsConfig`) and the filesystem paths (for mounting into
    the SAPL Node container).
    """
    cert_dir = tmp_path_factory.mktemp("sapl-tls")
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    subprocess.check_call(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        stderr=subprocess.DEVNULL,
    )
    cert_dir.chmod(0o755)
    cert_path.chmod(0o644)
    key_path.chmod(0o644)
    return {
        "cert_path": str(cert_path),
        "key_path": str(key_path),
        "dir": str(cert_dir),
        "cert_pem": cert_path.read_bytes(),
        "key_pem": key_path.read_bytes(),
    }


_TLS_ENV: dict[str, str] = {
    "SERVER_SSL_ENABLED": "true",
    "SERVER_SSL_BUNDLE": "saplbundle",
    "SPRING_SSL_BUNDLE_PEM_SAPLBUNDLE_KEYSTORE_CERTIFICATE": "/tls/cert.pem",
    "SPRING_SSL_BUNDLE_PEM_SAPLBUNDLE_KEYSTORE_PRIVATE_KEY": "/tls/key.pem",
    "SAPL_PDP_RSOCKET_SSL_BUNDLE": "saplbundle",
}


def _basic_auth_env() -> dict[str, str]:
    return {
        "IO_SAPL_NODE_ALLOWNOAUTH": "false",
        "IO_SAPL_NODE_ALLOWBASICAUTH": "true",
        "IO_SAPL_NODE_USERS_0_ID": "basic-tester",
        "IO_SAPL_NODE_USERS_0_PDPID": "default",
        "IO_SAPL_NODE_USERS_0_BASIC_USERNAME": BASIC_USER,
        "IO_SAPL_NODE_USERS_0_BASIC_SECRET": _argon2_hash(BASIC_SECRET),
    }


def _api_key_auth_env() -> dict[str, str]:
    return {
        "IO_SAPL_NODE_ALLOWNOAUTH": "false",
        "IO_SAPL_NODE_ALLOWAPIKEYAUTH": "true",
        "IO_SAPL_NODE_USERS_0_ID": "apikey-tester",
        "IO_SAPL_NODE_USERS_0_PDPID": "default",
        "IO_SAPL_NODE_USERS_0_APIKEYID": API_KEY_ID,
        "IO_SAPL_NODE_USERS_0_APIKEY": _argon2_hash(API_KEY_PLAIN),
    }


def _noauth_env() -> dict[str, str]:
    return {"IO_SAPL_NODE_ALLOWNOAUTH": "true"}


def _common_pdp_env(http_port_internal: int = 8443) -> dict[str, str]:
    return {
        "SERVER_PORT": str(http_port_internal),
        "SERVER_ADDRESS": "0.0.0.0",
        "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
        "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
    }


@pytest.fixture
def sapl_node_https_noauth(
    permit_all_policies: Path,
    self_signed_tls_pair: dict[str, str | bytes],
) -> Generator[tuple[str, bytes], None, None]:
    """SAPL Node with HTTPS + no-auth. Yields (https_base_url, ca_pem)."""
    port = _free_port()
    env = {**_common_pdp_env(), **_TLS_ENV, **_noauth_env()}
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env=env,
        http_port=port,
        extra_volumes=[f"{self_signed_tls_pair['dir']}:/tls:ro"],
    )
    base_url = f"https://127.0.0.1:{port}"
    cert_pem = self_signed_tls_pair["cert_pem"]
    assert isinstance(cert_pem, bytes)
    try:
        _wait_for_pdp_ready_https(base_url, cert_pem, timeout_seconds=60.0)
        yield base_url, cert_pem
    finally:
        _stop_container(container_id)


@pytest.fixture
def sapl_node_https_basic(
    permit_all_policies: Path,
    self_signed_tls_pair: dict[str, str | bytes],
) -> Generator[tuple[str, bytes], None, None]:
    """HTTPS + Basic Auth. Yields (https_base_url, ca_pem)."""
    port = _free_port()
    env = {**_common_pdp_env(), **_TLS_ENV, **_basic_auth_env()}
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env=env,
        http_port=port,
        extra_volumes=[f"{self_signed_tls_pair['dir']}:/tls:ro"],
    )
    base_url = f"https://127.0.0.1:{port}"
    cert_pem = self_signed_tls_pair["cert_pem"]
    assert isinstance(cert_pem, bytes)
    try:
        _wait_for_pdp_ready_https_with_basic(
            base_url, cert_pem, BASIC_USER, BASIC_SECRET, timeout_seconds=60.0
        )
        yield base_url, cert_pem
    finally:
        _stop_container(container_id)


@pytest.fixture
def sapl_node_https_apikey(
    permit_all_policies: Path,
    self_signed_tls_pair: dict[str, str | bytes],
) -> Generator[tuple[str, bytes], None, None]:
    """HTTPS + API-key Bearer auth. Yields (https_base_url, ca_pem)."""
    port = _free_port()
    env = {**_common_pdp_env(), **_TLS_ENV, **_api_key_auth_env()}
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env=env,
        http_port=port,
        extra_volumes=[f"{self_signed_tls_pair['dir']}:/tls:ro"],
    )
    base_url = f"https://127.0.0.1:{port}"
    cert_pem = self_signed_tls_pair["cert_pem"]
    assert isinstance(cert_pem, bytes)
    try:
        _wait_for_pdp_ready_https_with_bearer(
            base_url, cert_pem, API_KEY_PLAIN, timeout_seconds=60.0
        )
        yield base_url, cert_pem
    finally:
        _stop_container(container_id)


@pytest.fixture
def sapl_node_rsocket_tls_noauth(
    permit_all_policies: Path,
    self_signed_tls_pair: dict[str, str | bytes],
) -> Generator[tuple[str, int, bytes], None, None]:
    """SAPL Node with TLS on both HTTP and RSocket, no-auth.

    Yields `(rsocket_host, rsocket_port, ca_pem)`. HTTPS is used
    only for the readiness probe; tests exercise the RSocket port.
    """
    http_port = _free_port()
    rsocket_port = _free_port()
    env = {**_common_pdp_env(), **_TLS_ENV, **_noauth_env()}
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env=env,
        http_port=http_port,
        rsocket_port=rsocket_port,
        extra_volumes=[f"{self_signed_tls_pair['dir']}:/tls:ro"],
    )
    base_url = f"https://127.0.0.1:{http_port}"
    cert_pem = self_signed_tls_pair["cert_pem"]
    assert isinstance(cert_pem, bytes)
    try:
        _wait_for_pdp_ready_https(base_url, cert_pem, timeout_seconds=60.0)
        yield "127.0.0.1", rsocket_port, cert_pem
    finally:
        _stop_container(container_id)


@pytest.fixture
def sapl_node_rsocket_tls_basic(
    permit_all_policies: Path,
    self_signed_tls_pair: dict[str, str | bytes],
) -> Generator[tuple[str, int, bytes], None, None]:
    """RSocket+TLS + Basic auth."""
    http_port = _free_port()
    rsocket_port = _free_port()
    env = {**_common_pdp_env(), **_TLS_ENV, **_basic_auth_env()}
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env=env,
        http_port=http_port,
        rsocket_port=rsocket_port,
        extra_volumes=[f"{self_signed_tls_pair['dir']}:/tls:ro"],
    )
    base_url = f"https://127.0.0.1:{http_port}"
    cert_pem = self_signed_tls_pair["cert_pem"]
    assert isinstance(cert_pem, bytes)
    try:
        _wait_for_pdp_ready_https_with_basic(
            base_url, cert_pem, BASIC_USER, BASIC_SECRET, timeout_seconds=60.0
        )
        yield "127.0.0.1", rsocket_port, cert_pem
    finally:
        _stop_container(container_id)


@pytest.fixture
def sapl_node_rsocket_tls_apikey(
    permit_all_policies: Path,
    self_signed_tls_pair: dict[str, str | bytes],
) -> Generator[tuple[str, int, bytes], None, None]:
    """RSocket+TLS + API-key auth."""
    http_port = _free_port()
    rsocket_port = _free_port()
    env = {**_common_pdp_env(), **_TLS_ENV, **_api_key_auth_env()}
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env=env,
        http_port=http_port,
        rsocket_port=rsocket_port,
        extra_volumes=[f"{self_signed_tls_pair['dir']}:/tls:ro"],
    )
    base_url = f"https://127.0.0.1:{http_port}"
    cert_pem = self_signed_tls_pair["cert_pem"]
    assert isinstance(cert_pem, bytes)
    try:
        _wait_for_pdp_ready_https_with_bearer(
            base_url, cert_pem, API_KEY_PLAIN, timeout_seconds=60.0
        )
        yield "127.0.0.1", rsocket_port, cert_pem
    finally:
        _stop_container(container_id)


def _wait_for_pdp_ready_https_with_basic(
    base_url: str, ca_pem: bytes, username: str, secret: str, timeout_seconds: float
) -> None:
    import base64
    encoded = base64.b64encode(f"{username}:{secret}".encode()).decode()
    _wait_for_pdp_ready_https_with_header(
        base_url, ca_pem, f"Basic {encoded}", timeout_seconds
    )


def _wait_for_pdp_ready_https_with_bearer(
    base_url: str, ca_pem: bytes, token: str, timeout_seconds: float
) -> None:
    _wait_for_pdp_ready_https_with_header(
        base_url, ca_pem, f"Bearer {token}", timeout_seconds
    )


def _wait_for_pdp_ready_https_with_header(
    base_url: str, ca_pem: bytes, authorization: str, timeout_seconds: float
) -> None:
    import ssl as _ssl
    import urllib.error
    import urllib.request

    ctx = _ssl.create_default_context()
    ctx.load_verify_locations(cadata=ca_pem.decode())
    body = b'{"subject":"_","action":"_","resource":"_"}'
    request = urllib.request.Request(
        f"{base_url}/api/pdp/decide-once",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": authorization},
        method="POST",
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2.0, context=ctx):
                return
        except urllib.error.HTTPError as error:
            if error.code != 401 and error.code != 403:
                return
            time.sleep(0.5)
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise TimeoutError(f"SAPL Node at {base_url} did not accept authenticated HTTPS within {timeout_seconds}s")


def _wait_for_pdp_ready_https(base_url: str, ca_pem: bytes, timeout_seconds: float) -> None:
    """Like `_wait_for_pdp_ready` but tolerates a self-signed cert via a CA bundle."""
    import ssl
    import urllib.error
    import urllib.request

    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=ca_pem.decode())
    body = b'{"subject":"_","action":"_","resource":"_"}'
    request = urllib.request.Request(
        f"{base_url}/api/pdp/decide-once",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2.0, context=ctx):
                return
        except urllib.error.HTTPError:
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise TimeoutError(f"SAPL Node at {base_url} did not accept HTTPS request within {timeout_seconds}s")


@pytest.fixture
def sapl_node_dual_transport_noauth(
    permit_all_policies: Path,
) -> Generator[tuple[str, str, int], None, None]:
    """SAPL Node with both HTTP and RSocket published, no-auth.

    Yields `(http_base_url, rsocket_host, rsocket_port)`. Both ports
    back the same PDP; HTTP is the readiness probe target.
    """
    http_port = _free_port()
    rsocket_port = _free_port()
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env={
            "SERVER_SSL_ENABLED": "false",
            "SERVER_PORT": "8443",
            "SERVER_ADDRESS": "0.0.0.0",
            "IO_SAPL_NODE_ALLOWNOAUTH": "true",
            "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
            "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
        },
        http_port=http_port,
        rsocket_port=rsocket_port,
    )
    base_url = f"http://127.0.0.1:{http_port}"
    try:
        _wait_for_pdp_ready(base_url, timeout_seconds=60.0)
        yield base_url, "127.0.0.1", rsocket_port
    finally:
        _stop_container(container_id)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


MOCK_OAUTH2_IMAGE = "ghcr.io/navikt/mock-oauth2-server:2.1.0"
OAUTH_NETWORK_ALIAS = "mock-oauth"
OAUTH_REALM = "default"
OAUTH_CLIENT_ID = "sapl-pdp-test"
OAUTH_CLIENT_SECRET = "test-secret"


@pytest.fixture
def docker_network() -> Generator[str, None, None]:
    """Create an isolated Docker network for this test's container set."""
    import secrets
    name = f"sapl-test-{secrets.token_hex(4)}"
    subprocess.check_call(
        ["docker", "network", "create", name],
        stdout=subprocess.DEVNULL,
    )
    try:
        yield name
    finally:
        subprocess.run(
            ["docker", "network", "rm", name],
            check=False,
            capture_output=True,
        )


@pytest.fixture
def mock_oauth2_server(
    docker_network: str,
) -> Generator[tuple[str, str, int], None, None]:
    """Start mock-oauth2-server on the shared docker network.

    Yields `(internal_issuer_url, host_for_python, host_port)`:
    - `internal_issuer_url`: the issuer URL the SAPL Node uses,
      via the docker-network alias (`http://mock-oauth:8080/default`).
    - `host_for_python` + `host_port`: how Python on the host
      reaches the same mock server. Python must set the `Host`
      header to `mock-oauth:8080` so the iss claim mock-oauth2-server
      emits matches what the SAPL Node expects.
    """
    host_port = _free_port()
    args = [
        "docker", "run", "-d",
        "--network", docker_network,
        "--network-alias", OAUTH_NETWORK_ALIAS,
        "-p", f"127.0.0.1:{host_port}:8080",
        MOCK_OAUTH2_IMAGE,
    ]
    container_id = subprocess.check_output(args, text=True).strip()
    internal_issuer = f"http://{OAUTH_NETWORK_ALIAS}:8080/{OAUTH_REALM}"
    try:
        _wait_for_mock_oauth_ready(host_port, OAUTH_NETWORK_ALIAS, timeout_seconds=30.0)
        yield internal_issuer, "127.0.0.1", host_port
    finally:
        _stop_container(container_id)


def _wait_for_mock_oauth_ready(host_port: int, host_header: str, timeout_seconds: float) -> None:
    import urllib.error
    import urllib.request

    discovery_url = (
        f"http://127.0.0.1:{host_port}/{OAUTH_REALM}/.well-known/openid-configuration"
    )
    request = urllib.request.Request(
        discovery_url, headers={"Host": f"{host_header}:8080"}
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2.0):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise TimeoutError(f"mock-oauth2-server did not respond within {timeout_seconds}s")


@pytest.fixture
def sapl_node_rsocket_oauth2(
    permit_all_policies: Path,
    docker_network: str,
    mock_oauth2_server: tuple[str, str, int],
) -> Generator[tuple[int, str, int], None, None]:
    """SAPL Node with HTTP+RSocket OAuth2 on the docker network.

    Yields `(rsocket_port, oauth_host, oauth_port)`. RSocket is on
    the docker network's host port (binds to 127.0.0.1:<rsocket_port>);
    the OAuth2 token is fetched from the same mock as the HTTP variant.
    """
    internal_issuer, oauth_host, oauth_port = mock_oauth2_server
    http_port = _free_port()
    rsocket_port = _free_port()
    container_id = _start_sapl_node_on_network(
        policies_dir=permit_all_policies,
        env={
            "SERVER_SSL_ENABLED": "false",
            "SERVER_PORT": "8443",
            "SERVER_ADDRESS": "0.0.0.0",
            "IO_SAPL_NODE_ALLOWNOAUTH": "false",
            "IO_SAPL_NODE_ALLOWOAUTH2AUTH": "true",
            "IO_SAPL_NODE_DEFAULTPDPID": "default",
            "SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUERURI": internal_issuer,
            "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
            "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
        },
        http_port=http_port,
        network=docker_network,
        rsocket_port=rsocket_port,
    )
    base_url = f"http://127.0.0.1:{http_port}"
    try:
        _wait_for_pdp_ready_with_bearer(
            base_url, _fetch_oauth_token(oauth_host, oauth_port), timeout_seconds=60.0
        )
        yield rsocket_port, oauth_host, oauth_port
    finally:
        _stop_container(container_id)


@pytest.fixture
def sapl_node_http_oauth2(
    permit_all_policies: Path,
    docker_network: str,
    mock_oauth2_server: tuple[str, str, int],
) -> Generator[tuple[str, str, int], None, None]:
    """SAPL Node configured to validate JWTs from the mock-oauth2-server.

    Yields `(sapl_base_url, oauth_host_for_python, oauth_host_port)`.
    """
    internal_issuer, oauth_host, oauth_port = mock_oauth2_server
    port = _free_port()
    container_id = _start_sapl_node_on_network(
        policies_dir=permit_all_policies,
        env={
            "SERVER_SSL_ENABLED": "false",
            "SERVER_PORT": "8443",
            "SERVER_ADDRESS": "0.0.0.0",
            "IO_SAPL_NODE_ALLOWNOAUTH": "false",
            "IO_SAPL_NODE_ALLOWOAUTH2AUTH": "true",
            "IO_SAPL_NODE_DEFAULTPDPID": "default",
            "SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUERURI": internal_issuer,
            "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
            "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
        },
        http_port=port,
        network=docker_network,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_pdp_ready_with_bearer(base_url, _fetch_oauth_token(oauth_host, oauth_port), timeout_seconds=60.0)
        yield base_url, oauth_host, oauth_port
    finally:
        _stop_container(container_id)


def _start_sapl_node_on_network(
    policies_dir: Path,
    env: dict[str, str],
    http_port: int,
    network: str,
    rsocket_port: int = 0,
) -> str:
    args = [
        "docker", "run", "-d",
        "--network", network,
        "-p", f"127.0.0.1:{http_port}:8443",
    ]
    if rsocket_port:
        args.extend(["-p", f"127.0.0.1:{rsocket_port}:7000"])
    args.extend(["-v", f"{policies_dir}:/pdp/data:ro"])
    for key, value in env.items():
        args.extend(["-e", f"{key}={value}"])
    args.append(SAPL_NODE_IMAGE)
    return subprocess.check_output(args, text=True).strip()


def _fetch_oauth_token(oauth_host: str, oauth_port: int) -> str:
    """Fetch a JWT from mock-oauth2-server with a Host-header override.

    The Host header makes the mock issuer derive the `iss` claim from
    the docker-network alias rather than `127.0.0.1`, so the token
    the SAPL Node receives carries the issuer it discovered via
    OIDC discovery on the same alias.
    """
    import urllib.parse
    import urllib.request

    token_url = f"http://{oauth_host}:{oauth_port}/{OAUTH_REALM}/token"
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "scope": "openid",
        }
    ).encode()
    request = urllib.request.Request(
        token_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": f"{OAUTH_NETWORK_ALIAS}:8080",
        },
    )
    import json
    with urllib.request.urlopen(request, timeout=5.0) as response:
        payload = json.loads(response.read())
    return payload["access_token"]


BASIC_USER = "test-user"
BASIC_SECRET = "test-secret"


@pytest.fixture
def sapl_node_http_basic(
    permit_all_policies: Path,
) -> Generator[str, None, None]:
    """Run a SAPL Node accepting only HTTP Basic Auth."""
    port = _free_port()
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env={
            "SERVER_SSL_ENABLED": "false",
            "SERVER_PORT": "8443",
            "SERVER_ADDRESS": "0.0.0.0",
            "IO_SAPL_NODE_ALLOWNOAUTH": "false",
            "IO_SAPL_NODE_ALLOWBASICAUTH": "true",
            "IO_SAPL_NODE_USERS_0_ID": "basic-tester",
            "IO_SAPL_NODE_USERS_0_PDPID": "default",
            "IO_SAPL_NODE_USERS_0_BASIC_USERNAME": BASIC_USER,
            "IO_SAPL_NODE_USERS_0_BASIC_SECRET": _argon2_hash(BASIC_SECRET),
            "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
            "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
        },
        http_port=port,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_pdp_ready_with_basic(base_url, BASIC_USER, BASIC_SECRET, timeout_seconds=60.0)
        yield base_url
    finally:
        _stop_container(container_id)


API_KEY_PLAIN = "sapl_test_apikey-abc123"
API_KEY_ID = "test"


@pytest.fixture
def sapl_node_http_apikey(
    permit_all_policies: Path,
) -> Generator[str, None, None]:
    """Run a SAPL Node accepting only API-key Bearer auth."""
    port = _free_port()
    container_id = _start_sapl_node(
        policies_dir=permit_all_policies,
        env={
            "SERVER_SSL_ENABLED": "false",
            "SERVER_PORT": "8443",
            "SERVER_ADDRESS": "0.0.0.0",
            "IO_SAPL_NODE_ALLOWNOAUTH": "false",
            "IO_SAPL_NODE_ALLOWAPIKEYAUTH": "true",
            "IO_SAPL_NODE_USERS_0_ID": "apikey-tester",
            "IO_SAPL_NODE_USERS_0_PDPID": "default",
            "IO_SAPL_NODE_USERS_0_APIKEYID": API_KEY_ID,
            "IO_SAPL_NODE_USERS_0_APIKEY": _argon2_hash(API_KEY_PLAIN),
            "IO_SAPL_PDP_EMBEDDED_PDPCONFIGTYPE": "DIRECTORY",
            "IO_SAPL_PDP_EMBEDDED_POLICIESPATH": "/pdp/data",
        },
        http_port=port,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_pdp_ready_with_bearer(base_url, API_KEY_PLAIN, timeout_seconds=60.0)
        yield base_url
    finally:
        _stop_container(container_id)


def _argon2_hash(plaintext: str) -> str:
    """Argon2id-hash a plaintext secret for the SAPL Node user store.

    Matches Spring's `Argon2PasswordEncoder.defaultsForSpringSecurity_v5_8()`:
    argon2id, memory=16384, iterations=3, parallelism=1, hash length=32,
    salt length=16. Output is the raw argon2 string (no `{id}` prefix).
    """
    try:
        from argon2 import PasswordHasher
        from argon2.low_level import Type
    except ImportError:
        pytest.skip("argon2-cffi not installed; needed for SAPL Node auth ITs")
    hasher = PasswordHasher(
        time_cost=3,
        memory_cost=16384,
        parallelism=1,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )
    return hasher.hash(plaintext)


def _wait_for_pdp_ready_with_basic(
    base_url: str, username: str, secret: str, timeout_seconds: float
) -> None:
    import base64

    encoded = base64.b64encode(f"{username}:{secret}".encode()).decode()
    _wait_for_pdp_ready_with_header(
        base_url, f"Basic {encoded}", timeout_seconds=timeout_seconds
    )


def _wait_for_pdp_ready_with_bearer(
    base_url: str, token: str, timeout_seconds: float
) -> None:
    _wait_for_pdp_ready_with_header(
        base_url, f"Bearer {token}", timeout_seconds=timeout_seconds
    )


def _wait_for_pdp_ready_with_header(
    base_url: str, authorization: str, timeout_seconds: float
) -> None:
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_seconds
    body = b'{"subject":"_","action":"_","resource":"_"}'
    request = urllib.request.Request(
        f"{base_url}/api/pdp/decide-once",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": authorization},
        method="POST",
    )
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2.0):
                return
        except urllib.error.HTTPError as error:
            if error.code != 401 and error.code != 403:
                return
            time.sleep(0.5)
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise TimeoutError(
        f"SAPL Node at {base_url} did not accept an authenticated decide "
        f"request within {timeout_seconds}s"
    )
