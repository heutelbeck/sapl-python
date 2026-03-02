from __future__ import annotations

from typing import Any

import structlog

WARN_INSECURE_CONNECTION = "Insecure HTTP connection configured. TLS is strongly recommended for production use."

_REDACTED_KEYS = frozenset({"secrets", "password", "token"})


def configure_logging() -> None:
    """Configure structlog with secret-safe processors.

    Call once at application startup. Adds a processor that strips
    sensitive keys from log event dictionaries.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _redact_secrets_processor,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _redact_secrets_processor(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    for key in _REDACTED_KEYS:
        if key in event_dict:
            event_dict[key] = "**REDACTED**"
    return event_dict


def redact_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """Remove secrets field from data for logging."""
    return {key: value for key, value in data.items() if key not in _REDACTED_KEYS}


def truncate(text: str, max_length: int = 500) -> str:
    """Truncate text for logging error responses."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "...[truncated]"
