"""Shared TLS configuration for both HTTP and RSocket transports.

Callers pass PEM **contents** (str or bytes), not file paths. Load
from disk with `Path.read_bytes()` if needed; this library never
opens files for the caller.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TlsConfig:
    """TLS material for connecting to a SAPL Node over HTTPS or RSocket+TLS.

    All fields are optional. Pass only what is needed:
    - `ca` alone: validate the server cert against this CA bundle.
    - `cert` + `key`: enable mutual TLS.
    - `server_name`: override SNI / certificate validation hostname
      (RSocket only; HTTP derives it from the URL).
    - `reject_unauthorized=False`: skip server cert validation
      entirely. Use only in tests with self-signed certs.
    """

    ca: bytes | str | None = None
    cert: bytes | str | None = None
    key: bytes | str | None = None
    server_name: str | None = None
    reject_unauthorized: bool = True
