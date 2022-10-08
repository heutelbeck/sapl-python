from abc import ABC, abstractmethod
from typing import Any


class ConstraintHandlerProvider(ABC):
    """" BaseClass of a ConstraintHandler, which can be used as an Interface to create ConstraintHandler for the
    ConstraintHandlerService
    """

    @abstractmethod
    def priority(self) -> int:
        return 0

    @abstractmethod
    def is_responsible(self, constraint) -> bool:
        pass


class ErrorConstraintHandlerProvider(ConstraintHandlerProvider, ABC):

    @abstractmethod
    def handle(self, exception: Exception) -> None:
        pass


class OnDecisionConstraintHandlerProvider(ConstraintHandlerProvider, ABC):

    @abstractmethod
    def handle(self, decision) -> None:
        pass


class FunctionArgumentsConstraintHandlerProvider(ConstraintHandlerProvider, ABC):

    @abstractmethod
    def handle(self, function_arguments: dict) -> None:
        pass


class ResultConstraintHandlerProvider(ConstraintHandlerProvider, ABC):

    @abstractmethod
    def handle(self, result: Any) -> Any:
        pass
