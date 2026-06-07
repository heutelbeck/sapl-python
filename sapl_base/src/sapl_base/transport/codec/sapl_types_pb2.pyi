from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class Decision(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    INDETERMINATE: _ClassVar[Decision]
    PERMIT: _ClassVar[Decision]
    DENY: _ClassVar[Decision]
    NOT_APPLICABLE: _ClassVar[Decision]
    SUSPEND: _ClassVar[Decision]
INDETERMINATE: Decision
PERMIT: Decision
DENY: Decision
NOT_APPLICABLE: Decision
SUSPEND: Decision

class Value(_message.Message):
    __slots__ = ("array_value", "bool_value", "error_value", "null_value", "number_value", "object_value", "text_value", "undefined_value")
    NULL_VALUE_FIELD_NUMBER: _ClassVar[int]
    BOOL_VALUE_FIELD_NUMBER: _ClassVar[int]
    NUMBER_VALUE_FIELD_NUMBER: _ClassVar[int]
    TEXT_VALUE_FIELD_NUMBER: _ClassVar[int]
    ARRAY_VALUE_FIELD_NUMBER: _ClassVar[int]
    OBJECT_VALUE_FIELD_NUMBER: _ClassVar[int]
    UNDEFINED_VALUE_FIELD_NUMBER: _ClassVar[int]
    ERROR_VALUE_FIELD_NUMBER: _ClassVar[int]
    null_value: NullValue
    bool_value: bool
    number_value: str
    text_value: str
    array_value: ArrayValue
    object_value: ObjectValue
    undefined_value: bool
    error_value: ErrorValue
    def __init__(self, null_value: NullValue | _Mapping | None = ..., bool_value: bool | None = ..., number_value: str | None = ..., text_value: str | None = ..., array_value: ArrayValue | _Mapping | None = ..., object_value: ObjectValue | _Mapping | None = ..., undefined_value: bool | None = ..., error_value: ErrorValue | _Mapping | None = ...) -> None: ...

class NullValue(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ArrayValue(_message.Message):
    __slots__ = ("elements",)
    ELEMENTS_FIELD_NUMBER: _ClassVar[int]
    elements: _containers.RepeatedCompositeFieldContainer[Value]
    def __init__(self, elements: _Iterable[Value | _Mapping] | None = ...) -> None: ...

class ObjectValue(_message.Message):
    __slots__ = ("fields",)
    class FieldsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: Value
        def __init__(self, key: str | None = ..., value: Value | _Mapping | None = ...) -> None: ...
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    fields: _containers.MessageMap[str, Value]
    def __init__(self, fields: _Mapping[str, Value] | None = ...) -> None: ...

class ErrorValue(_message.Message):
    __slots__ = ("arguments", "message")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_FIELD_NUMBER: _ClassVar[int]
    message: str
    arguments: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, message: str | None = ..., arguments: _Iterable[str] | None = ...) -> None: ...

class AuthorizationSubscription(_message.Message):
    __slots__ = ("action", "environment", "resource", "secrets", "subject")
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    ENVIRONMENT_FIELD_NUMBER: _ClassVar[int]
    SECRETS_FIELD_NUMBER: _ClassVar[int]
    subject: Value
    action: Value
    resource: Value
    environment: Value
    secrets: Value
    def __init__(self, subject: Value | _Mapping | None = ..., action: Value | _Mapping | None = ..., resource: Value | _Mapping | None = ..., environment: Value | _Mapping | None = ..., secrets: Value | _Mapping | None = ...) -> None: ...

class AuthorizationDecision(_message.Message):
    __slots__ = ("advice", "decision", "obligations", "resource")
    DECISION_FIELD_NUMBER: _ClassVar[int]
    OBLIGATIONS_FIELD_NUMBER: _ClassVar[int]
    ADVICE_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    decision: Decision
    obligations: ArrayValue
    advice: ArrayValue
    resource: Value
    def __init__(self, decision: Decision | str | None = ..., obligations: ArrayValue | _Mapping | None = ..., advice: ArrayValue | _Mapping | None = ..., resource: Value | _Mapping | None = ...) -> None: ...

class IdentifiableAuthorizationSubscription(_message.Message):
    __slots__ = ("subscription", "subscription_id")
    SUBSCRIPTION_ID_FIELD_NUMBER: _ClassVar[int]
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    subscription_id: str
    subscription: AuthorizationSubscription
    def __init__(self, subscription_id: str | None = ..., subscription: AuthorizationSubscription | _Mapping | None = ...) -> None: ...

class IdentifiableAuthorizationDecision(_message.Message):
    __slots__ = ("decision", "subscription_id")
    SUBSCRIPTION_ID_FIELD_NUMBER: _ClassVar[int]
    DECISION_FIELD_NUMBER: _ClassVar[int]
    subscription_id: str
    decision: AuthorizationDecision
    def __init__(self, subscription_id: str | None = ..., decision: AuthorizationDecision | _Mapping | None = ...) -> None: ...

class MultiAuthorizationSubscription(_message.Message):
    __slots__ = ("subscriptions",)
    SUBSCRIPTIONS_FIELD_NUMBER: _ClassVar[int]
    subscriptions: _containers.RepeatedCompositeFieldContainer[IdentifiableAuthorizationSubscription]
    def __init__(self, subscriptions: _Iterable[IdentifiableAuthorizationSubscription | _Mapping] | None = ...) -> None: ...

class MultiAuthorizationDecision(_message.Message):
    __slots__ = ("decisions",)
    class DecisionsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: AuthorizationDecision
        def __init__(self, key: str | None = ..., value: AuthorizationDecision | _Mapping | None = ...) -> None: ...
    DECISIONS_FIELD_NUMBER: _ClassVar[int]
    decisions: _containers.MessageMap[str, AuthorizationDecision]
    def __init__(self, decisions: _Mapping[str, AuthorizationDecision] | None = ...) -> None: ...
