from __future__ import annotations

from dataclasses import dataclass

from sapl_base.pdp_client import PdpConfig


@dataclass(frozen=True, slots=True)
class SaplConfig:
    """SAPL PEP configuration for Tornado applications. REQ-MODULE-1."""

    base_url: str = "https://localhost:8443"
    token: str | None = None
    username: str | None = None
    password: str | None = None
    timeout: float = 5.0
    allow_insecure_connections: bool = False
    streaming_max_retries: int = 0
    streaming_retry_base_delay: float = 1.0
    streaming_retry_max_delay: float = 30.0

    def to_pdp_config(self) -> PdpConfig:
        """Convert to PdpConfig for the base library."""
        return PdpConfig(
            base_url=self.base_url,
            token=self.token,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            allow_insecure_connections=self.allow_insecure_connections,
            streaming_max_retries=self.streaming_max_retries,
            streaming_retry_base_delay=self.streaming_retry_base_delay,
            streaming_retry_max_delay=self.streaming_retry_max_delay,
        )
