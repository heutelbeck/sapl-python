"""Transport layer for the SAPL PDP client.

A transport-agnostic `PdpClient` Protocol plus HTTP and RSocket
implementations. Both transports share `TlsConfig` for TLS
material and the `TokenProvider` Protocol for dynamic bearer auth.
"""

from sapl_base.transport.constants import (
    DEFAULT_RETRY_BASE_DELAY_SECONDS,
    DEFAULT_RETRY_MAX_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_SSE_BUFFER_BYTES,
    PDP_API_PREFIX,
    PdpRoute,
    RETRY_ESCALATION_THRESHOLD,
)
from sapl_base.transport.http_pdp_client import HttpPdpClient, HttpPdpClientOptions
from sapl_base.transport.oauth2 import (
    AuthlibOAuth2TokenProvider,
    OAuth2TokenProviderOptions,
    TokenProvider,
)
from sapl_base.transport.pdp_client import PdpClient
from sapl_base.transport.rsocket_pdp_client import (
    DEFAULT_RSOCKET_PORT,
    INITIAL_REQUEST_N,
    RsocketPdpClient,
    RsocketPdpClientOptions,
)
from sapl_base.transport.tls_config import TlsConfig

__all__ = [
    "AuthlibOAuth2TokenProvider",
    "DEFAULT_RETRY_BASE_DELAY_SECONDS",
    "DEFAULT_RETRY_MAX_DELAY_SECONDS",
    "DEFAULT_RSOCKET_PORT",
    "DEFAULT_TIMEOUT_SECONDS",
    "HttpPdpClient",
    "HttpPdpClientOptions",
    "INITIAL_REQUEST_N",
    "MAX_SSE_BUFFER_BYTES",
    "OAuth2TokenProviderOptions",
    "PDP_API_PREFIX",
    "PdpClient",
    "PdpRoute",
    "RETRY_ESCALATION_THRESHOLD",
    "RsocketPdpClient",
    "RsocketPdpClientOptions",
    "TlsConfig",
    "TokenProvider",
]
