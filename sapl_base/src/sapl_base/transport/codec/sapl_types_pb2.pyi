from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

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
    __slots__ = ("null_value", "bool_value", "number_value", "text_value", "array_value", "object_value", "undefined_value", "error_value")
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
    def __init__(self, null_value: _Optional[_Union[NullValue, _Mapping]] = ..., bool_value: _Optional[bool] = ..., number_value: _Optional[str] = ..., text_value: _Optional[str] = ..., array_value: _Optional[_Union[ArrayValue, _Mapping]] = ..., object_value: _Optional[_Union[ObjectValue, _Mapping]] = ..., undefined_value: _Optional[bool] = ..., error_value: _Optional[_Union[ErrorValue, _Mapping]] = ...) -> None: ...

class NullValue(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ArrayValue(_message.Message):
    __slots__ = ("elements",)
    ELEMENTS_FIELD_NUMBER: _ClassVar[int]
    elements: _containers.RepeatedCompositeFieldContainer[Value]
    def __init__(self, elements: _Optional[_Iterable[_Union[Value, _Mapping]]] = ...) -> None: ...

class ObjectValue(_message.Message):
    __slots__ = ("fields",)
    class FieldsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: Value
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[Value, _Mapping]] = ...) -> None: ...
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    fields: _containers.MessageMap[str, Value]
    def __init__(self, fields: _Optional[_Mapping[str, Value]] = ...) -> None: ...

class ErrorValue(_message.Message):
    __slots__ = ("message", "arguments")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_FIELD_NUMBER: _ClassVar[int]
    message: str
    arguments: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, message: _Optional[str] = ..., arguments: _Optional[_Iterable[str]] = ...) -> None: ...

class AuthorizationSubscription(_message.Message):
    __slots__ = ("subject", "action", "resource", "environment", "secrets")
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
    def __init__(self, subject: _Optional[_Union[Value, _Mapping]] = ..., action: _Optional[_Union[Value, _Mapping]] = ..., resource: _Optional[_Union[Value, _Mapping]] = ..., environment: _Optional[_Union[Value, _Mapping]] = ..., secrets: _Optional[_Union[Value, _Mapping]] = ...) -> None: ...

class AuthorizationDecision(_message.Message):
    __slots__ = ("decision", "obligations", "advice", "resource")
    DECISION_FIELD_NUMBER: _ClassVar[int]
    OBLIGATIONS_FIELD_NUMBER: _ClassVar[int]
    ADVICE_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    decision: Decision
    obligations: ArrayValue
    advice: ArrayValue
    resource: Value
    def __init__(self, decision: _Optional[_Union[Decision, str]] = ..., obligations: _Optional[_Union[ArrayValue, _Mapping]] = ..., advice: _Optional[_Union[ArrayValue, _Mapping]] = ..., resource: _Optional[_Union[Value, _Mapping]] = ...) -> None: ...

class IdentifiableAuthorizationSubscription(_message.Message):
    __slots__ = ("subscription_id", "subscription")
    SUBSCRIPTION_ID_FIELD_NUMBER: _ClassVar[int]
    SUBSCRIPTION_FIELD_NUMBER: _ClassVar[int]
    subscription_id: str
    subscription: AuthorizationSubscription
    def __init__(self, subscription_id: _Optional[str] = ..., subscription: _Optional[_Union[AuthorizationSubscription, _Mapping]] = ...) -> None: ...

class IdentifiableAuthorizationDecision(_message.Message):
    __slots__ = ("subscription_id", "decision")
    SUBSCRIPTION_ID_FIELD_NUMBER: _ClassVar[int]
    DECISION_FIELD_NUMBER: _ClassVar[int]
    subscription_id: str
    decision: AuthorizationDecision
    def __init__(self, subscription_id: _Optional[str] = ..., decision: _Optional[_Union[AuthorizationDecision, _Mapping]] = ...) -> None: ...

class MultiAuthorizationSubscription(_message.Message):
    __slots__ = ("subscriptions",)
    SUBSCRIPTIONS_FIELD_NUMBER: _ClassVar[int]
    subscriptions: _containers.RepeatedCompositeFieldContainer[IdentifiableAuthorizationSubscription]
    def __init__(self, subscriptions: _Optional[_Iterable[_Union[IdentifiableAuthorizationSubscription, _Mapping]]] = ...) -> None: ...

class MultiAuthorizationDecision(_message.Message):
    __slots__ = ("decisions",)
    class DecisionsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: AuthorizationDecision
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[AuthorizationDecision, _Mapping]] = ...) -> None: ...
    DECISIONS_FIELD_NUMBER: _ClassVar[int]
    decisions: _containers.MessageMap[str, AuthorizationDecision]
    def __init__(self, decisions: _Optional[_Mapping[str, AuthorizationDecision]] = ...) -> None: ...
