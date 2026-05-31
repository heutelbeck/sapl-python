"""SAPL PEP core library for Python.

Public namespaces:

- `sapl_base.pep`: the PEP layer (planner, plan, signal taxonomy,
  boundary signals, one-shot enforcement, streaming pipeline,
  built-in JSON filter providers).
- `sapl_base.transport`: the connector to the SAPL Node (HTTP and
  RSocket PDP clients, TLS config, OAuth2 token provider).
- `sapl_base.types`: wire types (Decision enum, AuthorizationSubscription,
  AuthorizationDecision, multi variants, RESOURCE_ABSENT sentinel).

The wire-type re-exports below are kept as ergonomic top-level
shortcuts for consumers that just need to construct subscriptions or
inspect decisions. Everything else should be imported from its
submodule.
"""

from __future__ import annotations

from sapl_base.types import (
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
)

__all__ = [
    "AuthorizationDecision",
    "AuthorizationSubscription",
    "Decision",
    "MultiAuthorizationDecision",
    "MultiAuthorizationSubscription",
]
