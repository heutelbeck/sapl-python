from __future__ import annotations

import os
import ssl
import subprocess

import pytest

from sapl_base.transport.http_pdp_client import _build_ssl_context
from sapl_base.transport.tls_config import TlsConfig


@pytest.fixture(scope="module")
def self_signed_ca_pem() -> bytes:
    """Generate a throw-away self-signed CA PEM for tests.

    Real production deployments load real CA bundles; this fixture
    only exercises that `load_verify_locations(cadata=...)` accepts
    well-formed PEM contents.
    """
    return subprocess.check_output(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            "/dev/null",
            "-out",
            "/dev/stdout",
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=test-ca",
        ],
        stderr=subprocess.DEVNULL,
    )


def test_no_inputs_yields_default_verifying_context() -> None:
    ctx, temp_files = _build_ssl_context(TlsConfig())
    try:
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        assert temp_files == []
    finally:
        pass


def test_reject_unauthorized_false_disables_verification() -> None:
    ctx, _ = _build_ssl_context(TlsConfig(reject_unauthorized=False))
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_ca_pem_string_loads_into_context(self_signed_ca_pem: bytes) -> None:
    ctx, _ = _build_ssl_context(TlsConfig(ca=self_signed_ca_pem.decode()))
    assert any(cert for cert in ctx.get_ca_certs())


def test_ca_pem_bytes_loads_into_context(self_signed_ca_pem: bytes) -> None:
    ctx, _ = _build_ssl_context(TlsConfig(ca=self_signed_ca_pem))
    assert any(cert for cert in ctx.get_ca_certs())


def test_cert_and_key_write_temp_pem_with_restrictive_mode() -> None:
    cert_pem, key_pem = _generate_self_signed_cert_pair()
    ctx, temp_files = _build_ssl_context(TlsConfig(cert=cert_pem, key=key_pem))
    try:
        assert isinstance(ctx, ssl.SSLContext)
        assert len(temp_files) == 1
        mode = os.stat(temp_files[0]).st_mode & 0o777
        assert mode == 0o600
    finally:
        for path in temp_files:
            os.unlink(path)


def _generate_self_signed_cert_pair() -> tuple[bytes, bytes]:
    cert_out = subprocess.check_output(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            "/dev/stdout",
            "-out",
            "/dev/stdout",
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=test",
        ],
        stderr=subprocess.DEVNULL,
    )
    key_end = cert_out.index(b"-----END PRIVATE KEY-----") + len(b"-----END PRIVATE KEY-----\n")
    return cert_out[key_end:], cert_out[:key_end]
