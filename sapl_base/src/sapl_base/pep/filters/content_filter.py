"""Built-in JSON content filter constraint handlers.

Two providers:

- `ContentFilteringProvider` claims constraints of type
  `filterJsonContent` and schedules an OUTPUT-signal mapper at
  priority 0 that gates each element by the constraint's
  `conditions` and applies the configured `blacken` / `replace` /
  `delete` actions to a JSON-native copy of the value.
- `ContentFilterPredicateProvider` claims constraints of type
  `jsonContentFilterPredicate` and schedules an OUTPUT-signal
  mapper at priority 100 that returns `DROP` when the predicate
  fails (filtering the value out of the stream).

Payloads are round-tripped to native JSON containers before
filtering, so plain objects (dataclasses, pydantic models, ORM
entities) are redacted element-wise just like dicts and lists.

Path syntax: a JSONPath subset covering child access (`$.a.b`),
array indexing (`$.a[0]`), wildcards (`$.a[*]`) and recursive
descent (`$..name`).

Fail-closed: any redaction that cannot be applied (path absent at
enforcement time, non-textual blacken target, unknown action type,
missing replacement, oversized blacken, unevaluable condition)
raises `AccessDeniedError`, which turns the obligation into a
DENY. Sensitive data never reaches the caller when the redaction
could not be applied.

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
from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING, Any

import structlog

from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.enforce import OUTPUT
from sapl_base.pep.plan import DROP
from sapl_base.pep.provider import ScopedHandler

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

log = structlog.get_logger(__name__)


ERROR_ACTION_NOT_OBJECT = "An action in 'actions' is not an object."
ERROR_ACTION_TYPE_NOT_TEXTUAL = "An action's 'type' is not textual."
ERROR_BLACKEN_LENGTH_NOT_NUMBER = "'length' of 'blacken' action is not a non-negative number."
ERROR_BLACKEN_LENGTH_TOO_LARGE = "'blacken' action exceeds the maximum permitted blacken length."
ERROR_CONDITIONS_NOT_ARRAY = "'conditions' is not an array."
ERROR_CONDITION_INVALID = "Not a valid predicate condition."
ERROR_DISCLOSE_NEGATIVE = "An action's disclose count must not be negative."
ERROR_DISCLOSE_NOT_INTEGER = "An action's disclose count is not an integer."
ERROR_MISSING_ACTIONS = "filterJsonContent constraint missing 'actions' array"
ERROR_NO_REPLACEMENT = "The 'replace' action does not specify a 'replacement'."
ERROR_PATH_NOT_FOUND = "The path defined in the constraint is not present in the data."
ERROR_PATH_NOT_TEXTUAL = "The 'path' of an action is not textual."
ERROR_PROTOTYPE_POLLUTION = "Path segment matches a forbidden key."
ERROR_REDOS_PATTERN = "Potentially unsafe regex pattern rejected"
ERROR_REPLACEMENT_NOT_TEXTUAL = "'replacement' of 'blacken' action is not textual."
ERROR_TARGET_NOT_TEXTUAL = "The node identified by the path is not a text node."
ERROR_UNKNOWN_ACTION = "Unknown action type: '{}'."
ERROR_UNSUPPORTED_PATH = "Invalid or unsupported path syntax."


_BLACK_SQUARE = "█"
_BLACKEN_LENGTH_UNSET = -1
_MAX_BLACKEN = 1_000_000

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

_PATH_DESCENDANT = re.compile(r"\.\.([A-Za-z_][A-Za-z0-9_]*)")
_PATH_CHILD = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)")
_PATH_WILDCARD = re.compile(r"\[\*\]")
_PATH_INDEX = re.compile(r"\[(-?\d+)\]")
_PATH_BRACKET = re.compile(r"\[(['\"])(.*?)\1\]")

_CONTENT_FILTER_PRIORITY = 0
_FILTER_PREDICATE_PRIORITY = 100


class ContentFilteringProvider:
    """Claims `filterJsonContent` constraints and yields a content-redacting
    mapping handler scheduled at the OUTPUT signal."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "filterJsonContent":
            return ()
        actions = constraint.get("actions", [])
        if not isinstance(actions, list):
            log.error(ERROR_MISSING_ACTIONS)
            return ()
        conditions = constraint.get("conditions")
        return (
            ScopedHandler(
                signal=OUTPUT,
                priority=_CONTENT_FILTER_PRIORITY,
                shape="mapper",
                handler=_make_filter_handler(actions, conditions),
            ),
        )


class ContentFilterPredicateProvider:
    """Claims `jsonContentFilterPredicate` constraints and yields a
    drop-or-keep mapping handler scheduled at the OUTPUT signal."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "jsonContentFilterPredicate":
            return ()
        conditions = constraint.get("conditions")
        return (
            ScopedHandler(
                signal=OUTPUT,
                priority=_FILTER_PREDICATE_PRIORITY,
                shape="mapper",
                handler=_make_predicate_handler(conditions),
            ),
        )


def _make_filter_handler(actions: list[Any], conditions: Any) -> Callable[[Any], Any]:
    def _filter_single(element: Any) -> Any:
        native = _to_native(element)
        if not _conditions_match(native, conditions):
            return native
        for action in actions:
            _apply_action(native, action)
        return native

    def _handler(value: Any) -> Any:
        if isinstance(value, list):
            return [_filter_single(element) for element in value]
        return _filter_single(value)

    return _handler


def _make_predicate_handler(conditions: Any) -> Callable[[Any], Any]:
    def _handler(value: Any) -> Any:
        if isinstance(value, list):
            return [element for element in value if _conditions_match(_to_native(element), conditions)]
        if _conditions_match(_to_native(value), conditions):
            return value
        return DROP

    return _handler


def _to_native(value: Any) -> Any:
    """Project a payload onto JSON-native containers, cloning as it goes.

    Dicts and lists are rebuilt so mutation never touches the caller's
    objects. Dataclasses, pydantic models and plain objects become
    dicts so JSONPath traversal and redaction apply to them too.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {key: _to_native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_native(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _to_native(getattr(value, field.name)) for field in fields(value)}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_native(model_dump())
    if hasattr(value, "__dict__"):
        return {key: _to_native(item) for key, item in vars(value).items()}
    return value


def _parse_path(path: Any) -> tuple[list[tuple[Any, ...]], bool]:
    """Tokenise a JSONPath-subset string into navigation steps.

    Returns the steps and whether the path is definite (no wildcard or
    recursive descent). Raises `AccessDeniedError` on unsupported syntax
    or a forbidden segment.
    """
    if not isinstance(path, str) or not path.startswith("$"):
        raise AccessDeniedError(ERROR_UNSUPPORTED_PATH)
    steps: list[tuple[Any, ...]] = []
    definite = True
    position = 1
    while position < len(path):
        descendant = _PATH_DESCENDANT.match(path, position)
        if descendant:
            _reject_forbidden(descendant.group(1))
            steps.append(("descendant", descendant.group(1)))
            definite = False
            position = descendant.end()
            continue
        child = _PATH_CHILD.match(path, position)
        if child:
            _reject_forbidden(child.group(1))
            steps.append(("child", child.group(1)))
            position = child.end()
            continue
        if _PATH_WILDCARD.match(path, position):
            steps.append(("wildcard",))
            definite = False
            position += len("[*]")
            continue
        index = _PATH_INDEX.match(path, position)
        if index:
            steps.append(("index", int(index.group(1))))
            position = index.end()
            continue
        bracket = _PATH_BRACKET.match(path, position)
        if bracket:
            _reject_forbidden(bracket.group(2))
            steps.append(("child", bracket.group(2)))
            position = bracket.end()
            continue
        raise AccessDeniedError(ERROR_UNSUPPORTED_PATH)
    if not steps:
        raise AccessDeniedError(ERROR_UNSUPPORTED_PATH)
    return steps, definite


def _reject_forbidden(segment: str) -> None:
    if segment in _FORBIDDEN_KEYS:
        raise AccessDeniedError(ERROR_PROTOTYPE_POLLUTION)


def _resolve_slots(root: Any, steps: list[tuple[Any, ...]]) -> list[tuple[Any, Any]]:
    """Return `(container, key)` slots whose `container[key]` matches `steps`."""
    results: list[tuple[Any, Any]] = []

    def walk(node: Any, depth: int) -> None:
        if depth == len(steps):
            return
        last = depth == len(steps) - 1
        kind = steps[depth][0]
        if kind == "child":
            name = steps[depth][1]
            if isinstance(node, dict) and name in node:
                results.append((node, name)) if last else walk(node[name], depth + 1)
        elif kind == "index":
            index = steps[depth][1]
            if isinstance(node, list) and -len(node) <= index < len(node):
                results.append((node, index)) if last else walk(node[index], depth + 1)
        elif kind == "wildcard":
            if isinstance(node, list):
                for position in range(len(node)):
                    results.append((node, position)) if last else walk(node[position], depth + 1)
            elif isinstance(node, dict):
                for key in list(node.keys()):
                    results.append((node, key)) if last else walk(node[key], depth + 1)
        elif kind == "descendant":
            _walk_descendant(node, steps[depth][1], last, depth, results, walk)

    walk(root, 0)
    return results


def _walk_descendant(
    node: Any,
    name: str,
    last: bool,
    depth: int,
    results: list[tuple[Any, Any]],
    walk: Callable[[Any, int], None],
) -> None:
    if isinstance(node, dict):
        for key, item in list(node.items()):
            if key == name:
                results.append((node, key)) if last else walk(item, depth + 1)
            _walk_descendant(item, name, last, depth, results, walk)
    elif isinstance(node, list):
        for item in node:
            _walk_descendant(item, name, last, depth, results, walk)


def _apply_action(root: Any, action: Any) -> None:
    if not isinstance(action, dict):
        raise AccessDeniedError(ERROR_ACTION_NOT_OBJECT)
    path = action.get("path")
    if not isinstance(path, str):
        raise AccessDeniedError(ERROR_PATH_NOT_TEXTUAL)
    action_type = action.get("type")
    if not isinstance(action_type, str):
        raise AccessDeniedError(ERROR_ACTION_TYPE_NOT_TEXTUAL)
    steps, definite = _parse_path(path)
    slots = _resolve_slots(root, steps)
    if definite and not slots:
        raise AccessDeniedError(ERROR_PATH_NOT_FOUND)
    normalized = action_type.strip().lower()
    if normalized == "delete":
        for parent, key in slots:
            _delete_slot(parent, key)
    elif normalized == "blacken":
        for parent, key in slots:
            parent[key] = _blacken_value(parent[key], action)
    elif normalized == "replace":
        if "replacement" not in action:
            raise AccessDeniedError(ERROR_NO_REPLACEMENT)
        for parent, key in slots:
            parent[key] = copy.deepcopy(action["replacement"])
    else:
        raise AccessDeniedError(ERROR_UNKNOWN_ACTION.format(normalized))


def _delete_slot(parent: Any, key: Any) -> None:
    if isinstance(parent, dict):
        parent.pop(key, None)
    elif isinstance(parent, list) and isinstance(key, int) and -len(parent) <= key < len(parent):
        del parent[key]


def _blacken_value(value: Any, action: dict[str, Any]) -> str:
    if not isinstance(value, str):
        raise AccessDeniedError(ERROR_TARGET_NOT_TEXTUAL)
    replacement = _replacement_string(action)
    disclose_left = _disclose_count(action, "discloseLeft")
    disclose_right = _disclose_count(action, "discloseRight")
    blacken_length = _blacken_length(action)
    if disclose_left + disclose_right >= len(value):
        return value
    replaced_chars = len(value) - disclose_left - disclose_right
    final_length = replaced_chars if blacken_length == _BLACKEN_LENGTH_UNSET else blacken_length
    if len(replacement) * final_length > _MAX_BLACKEN:
        raise AccessDeniedError(ERROR_BLACKEN_LENGTH_TOO_LARGE)
    left = value[:disclose_left] if disclose_left > 0 else ""
    right = value[disclose_left + replaced_chars:] if disclose_right > 0 else ""
    return left + (replacement * final_length) + right


def _replacement_string(action: dict[str, Any]) -> str:
    replacement = action.get("replacement")
    if replacement is None:
        return _BLACK_SQUARE
    if not isinstance(replacement, str):
        raise AccessDeniedError(ERROR_REPLACEMENT_NOT_TEXTUAL)
    return replacement


def _disclose_count(action: dict[str, Any], key: str) -> int:
    raw = action.get(key)
    if raw is None:
        return 0
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise AccessDeniedError(ERROR_DISCLOSE_NOT_INTEGER)
    if isinstance(raw, float) and not raw.is_integer():
        raise AccessDeniedError(ERROR_DISCLOSE_NOT_INTEGER)
    count = int(raw)
    if count < 0:
        raise AccessDeniedError(ERROR_DISCLOSE_NEGATIVE)
    return count


def _blacken_length(action: dict[str, Any]) -> int:
    raw = action.get("length")
    if raw is None:
        return _BLACKEN_LENGTH_UNSET
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
        raise AccessDeniedError(ERROR_BLACKEN_LENGTH_NOT_NUMBER)
    if raw > _MAX_BLACKEN:
        raise AccessDeniedError(ERROR_BLACKEN_LENGTH_TOO_LARGE)
    return int(raw)


def _conditions_match(element: Any, conditions: Any) -> bool:
    if conditions is None:
        return True
    if not isinstance(conditions, list):
        raise AccessDeniedError(ERROR_CONDITIONS_NOT_ARRAY)
    return all(_evaluate_condition(element, condition) for condition in conditions)


def _value_at_path(element: Any, steps: list[tuple[Any, ...]]) -> Any:
    slots = _resolve_slots(element, steps)
    if not slots:
        raise AccessDeniedError(ERROR_PATH_NOT_FOUND)
    parent, key = slots[0]
    return parent[key]


def _is_safe_regex(pattern: Any) -> bool:
    if not isinstance(pattern, str):
        return False
    if len(pattern) > _MAX_REGEX_LENGTH:
        return False
    return not _REDOS_PATTERNS.search(pattern)


def _evaluate_condition(element: Any, condition: Any) -> bool:
    if not isinstance(condition, dict):
        raise AccessDeniedError(ERROR_CONDITION_INVALID)
    path = condition.get("path")
    operator = condition.get("operator")
    if not isinstance(operator, str) or "value" not in condition:
        raise AccessDeniedError(ERROR_CONDITION_INVALID)
    expected = condition.get("value")
    steps, _definite = _parse_path(path)
    actual = _value_at_path(element, steps)

    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator in (">=", "<=", ">", "<"):
        return _compare(operator, actual, expected)
    if operator == "=~":
        return _regex_match(actual, expected)
    return False


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    try:
        if operator == ">=":
            return actual >= expected
        if operator == "<=":
            return actual <= expected
        if operator == ">":
            return actual > expected
        return actual < expected
    except TypeError:
        return False


def _regex_match(actual: Any, expected: Any) -> bool:
    if not isinstance(expected, str):
        return False
    if not _is_safe_regex(expected):
        log.error(ERROR_REDOS_PATTERN)
        return False
    if not isinstance(actual, str):
        return False
    try:
        return bool(re.search(expected, actual))
    except re.error:
        return False
