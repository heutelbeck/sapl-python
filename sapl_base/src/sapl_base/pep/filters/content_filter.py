"""Built-in JSON content filter constraint handlers.

Two providers:

- `ContentFilteringProvider` claims constraints of type
  `filterJsonContent` and schedules an OUTPUT-signal mapper at
  priority 0 that applies the configured `blacken` / `replace` /
  `delete` actions to a deep clone of the value.
- `ContentFilterPredicateProvider` claims constraints of type
  `jsonContentFilterPredicate` and schedules an OUTPUT-signal
  mapper at priority 100 that returns `DROP` when the predicate
  fails (filtering the value out of the stream).

Path syntax: simple dot-notation only (`$.field.nested`). Array
indexing, wildcards, and recursive descent are not supported.

Security:

- Prototype-pollution defence: path segments matching keys like
  `__proto__`, `__class__`, `__dict__`, `__globals__`,
  `__builtins__`, `__subclasses__` are rejected.
- ReDoS guard on the `=~` operator: patterns longer than 200
  characters or containing nested quantifiers / excessive
  alternation are rejected. Unsafe patterns fail-closed (the
  condition evaluates to False).
"""

from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING, Any

import structlog

from sapl_base.logging_utils import truncate
from sapl_base.pep.enforce import OUTPUT
from sapl_base.pep.plan import DROP
from sapl_base.pep.provider import ScopedHandler

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

log = structlog.get_logger(__name__)


ERROR_INVALID_FILTER_ACTION = "Invalid filter action type"
ERROR_INVALID_PATH = "Invalid or unsupported path syntax"
ERROR_MISSING_ACTIONS = "filterJsonContent constraint missing 'actions' array"
ERROR_PROTOTYPE_POLLUTION = "Path segment matches forbidden key, skipping action"
ERROR_REDOS_PATTERN = "Potentially unsafe regex pattern rejected"
WARN_PATH_NOT_FOUND = "Path not found in object during content filtering"


_MAX_REGEX_LENGTH = 200
_REDOS_PATTERNS = re.compile(
    r"\([^)]*[+*][^)]*\)[+*?]"
    r"|(\([^)]*\|[^)]*\)){3,}"
)

_FORBIDDEN_KEYS = frozenset(
    {
        "__proto__",
        "__class__",
        "__dict__",
        "__globals__",
        "__builtins__",
        "__subclasses__",
    }
)

_UNSUPPORTED_PATH = re.compile(r"\[|\]|\*|\.\.")
_VALID_PATH = re.compile(r"^\$(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")
_MAX_SAFE_REPR = 200

_CONTENT_FILTER_PRIORITY = 0
_FILTER_PREDICATE_PRIORITY = 100


class ContentFilteringProvider:
    """Claims `filterJsonContent` constraints and yields a deep-clone mapping
    handler scheduled at the OUTPUT signal."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "filterJsonContent":
            return ()
        actions = constraint.get("actions", [])
        if not isinstance(actions, list):
            log.error(ERROR_MISSING_ACTIONS, constraint=_safe_repr(constraint))
            return ()
        return (
            ScopedHandler(
                signal=OUTPUT,
                priority=_CONTENT_FILTER_PRIORITY,
                shape="mapper",
                handler=_make_filter_handler(actions),
            ),
        )


class ContentFilterPredicateProvider:
    """Claims `jsonContentFilterPredicate` constraints and yields a
    drop-or-keep mapping handler scheduled at the OUTPUT signal."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "jsonContentFilterPredicate":
            return ()
        conditions = constraint.get("conditions", [])
        if not isinstance(conditions, list):
            conditions = []
        return (
            ScopedHandler(
                signal=OUTPUT,
                priority=_FILTER_PREDICATE_PRIORITY,
                shape="mapper",
                handler=_make_predicate_handler(conditions),
            ),
        )


def _make_filter_handler(actions: list[Any]) -> Callable[[Any], Any]:
    def _filter_single(obj: Any) -> Any:
        result = obj
        for action in actions:
            result = _apply_action(result, action)
        return result

    def _handler(value: Any) -> Any:
        cloned = copy.deepcopy(value)
        if isinstance(cloned, list):
            return [_filter_single(element) for element in cloned]
        return _filter_single(cloned)

    return _handler


def _make_predicate_handler(conditions: list[Any]) -> Callable[[Any], Any]:
    def _handler(value: Any) -> Any:
        if isinstance(value, list):
            return [
                element for element in value
                if all(_evaluate_condition(element, cond) for cond in conditions)
            ]
        if all(_evaluate_condition(value, cond) for cond in conditions):
            return value
        return DROP

    return _handler


def _parse_path(path: Any) -> list[str] | None:
    if not isinstance(path, str):
        log.error(ERROR_INVALID_PATH, path=_safe_repr(path))
        return None
    if _UNSUPPORTED_PATH.search(path):
        log.error(ERROR_INVALID_PATH, path=path, reason="unsupported syntax")
        return None
    if not _VALID_PATH.match(path):
        log.error(ERROR_INVALID_PATH, path=path, reason="does not match expected format")
        return None
    segments = path.split(".")[1:]
    for segment in segments:
        if segment in _FORBIDDEN_KEYS:
            log.error(ERROR_PROTOTYPE_POLLUTION, path=path, segment=segment)
            return None
    return segments


def _navigate_to_parent(obj: Any, segments: list[str]) -> tuple[Any, str] | None:
    current = obj
    for segment in segments[:-1]:
        if not isinstance(current, dict) or segment not in current:
            log.warning(WARN_PATH_NOT_FOUND, segment=segment)
            return None
        current = current[segment]
    last_key = segments[-1]
    if not isinstance(current, dict):
        log.warning(WARN_PATH_NOT_FOUND, segment=last_key)
        return None
    return current, last_key


def _safe_repr(obj: Any) -> str:
    return truncate(repr(obj), _MAX_SAFE_REPR)


def _apply_action(obj: Any, action: Any) -> Any:
    if not isinstance(action, dict):
        log.error(ERROR_INVALID_FILTER_ACTION, action=_safe_repr(action))
        return obj
    action_type = action.get("type")
    if not isinstance(action_type, str):
        log.error(ERROR_INVALID_FILTER_ACTION, action=_safe_repr(action))
        return obj
    segments = _parse_path(action.get("path"))
    if segments is None:
        return obj
    if action_type == "blacken":
        return _apply_blacken(obj, segments, action)
    if action_type == "replace":
        return _apply_replace(obj, segments, action)
    if action_type == "delete":
        return _apply_delete(obj, segments)
    log.error(ERROR_INVALID_FILTER_ACTION, action_type=action_type)
    return obj


def _apply_blacken(obj: Any, segments: list[str], action: dict[str, Any]) -> Any:
    nav = _navigate_to_parent(obj, segments)
    if nav is None:
        return obj
    parent, key = nav
    if key not in parent:
        log.warning(WARN_PATH_NOT_FOUND, segment=key)
        return obj
    current_value = parent[key]
    if not isinstance(current_value, str):
        log.warning(WARN_PATH_NOT_FOUND, segment=key, reason="value is not a string")
        return obj
    replacement = action.get("replacement", "X")
    disclose_left = int(action.get("discloseLeft", 0))
    disclose_right = int(action.get("discloseRight", 0))
    parent[key] = _blacken_value(current_value, replacement, disclose_left, disclose_right)
    return obj


def _apply_replace(obj: Any, segments: list[str], action: dict[str, Any]) -> Any:
    nav = _navigate_to_parent(obj, segments)
    if nav is None:
        return obj
    parent, key = nav
    if key not in parent:
        log.warning(WARN_PATH_NOT_FOUND, segment=key)
        return obj
    parent[key] = action.get("replacement")
    return obj


def _apply_delete(obj: Any, segments: list[str]) -> Any:
    nav = _navigate_to_parent(obj, segments)
    if nav is None:
        return obj
    parent, key = nav
    parent.pop(key, None)
    return obj


def _blacken_value(
    value: str,
    replacement: str,
    disclose_left: int,
    disclose_right: int,
) -> str:
    length = len(value)
    if length == 0:
        return value
    if disclose_left + disclose_right >= length:
        return value
    left = value[:disclose_left]
    right = value[length - disclose_right:] if disclose_right > 0 else ""
    middle_len = length - disclose_left - disclose_right
    return left + (replacement * middle_len) + right


def _is_safe_regex(pattern: Any) -> bool:
    if not isinstance(pattern, str):
        return False
    if len(pattern) > _MAX_REGEX_LENGTH:
        return False
    return not _REDOS_PATTERNS.search(pattern)


def _resolve_value(element: Any, path: Any) -> tuple[Any, bool]:
    segments = _parse_path(path)
    if segments is None:
        return None, False
    current = element
    for segment in segments:
        if not isinstance(current, dict) or segment not in current:
            return None, False
        current = current[segment]
    return current, True


def _evaluate_condition(element: Any, condition: Any) -> bool:
    if not isinstance(condition, dict):
        return False
    path = condition.get("path")
    operator = condition.get("operator")
    expected = condition.get("value")

    actual, found = _resolve_value(element, path)
    if not found:
        return False

    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator == ">=":
        return actual >= expected
    if operator == "<=":
        return actual <= expected
    if operator == ">":
        return actual > expected
    if operator == "<":
        return actual < expected
    if operator == "=~":
        if not isinstance(expected, str):
            return False
        if not _is_safe_regex(expected):
            log.error(ERROR_REDOS_PATTERN, pattern=_safe_repr(expected))
            return False
        if not isinstance(actual, str):
            return False
        try:
            return bool(re.search(expected, actual))
        except re.error:
            return False
    return False
