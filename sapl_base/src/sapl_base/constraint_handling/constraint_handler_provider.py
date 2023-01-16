from abc import ABC, abstractmethod
from typing import Any

from sapl_base.decision import Decision


class ConstraintHandlerProvider(ABC):
    """
    Baseclass of a ConstraintHandlerProvider
    """

    @abstractmethod
    def priority(self) -> int:
        """
        ConstraintHandlerProvider are sorted by the value of the priority, when the ConstraintHandlerBundle is created

        :return: value by which ConstraintHandlerProvider are sorted
        """
        return 0

    @abstractmethod
    def is_responsible(self, constraint) -> bool:
        """
        Determine if this ConstraintHandler is responsible for the provided constraint

        :param constraint: A constraint, which can be an Obligation or an Advice, for which the
        ConstraintHandlerProvider checks if it is responsible to handle it.
        :return: Is this ConstraintHandlerProvider responsible to handle the provided constraint
        """
        pass

    @abstractmethod
    def handle(self, argument):
        """
        Abstractmethod, which needs to be implemented by a ConstraintHandlerProvider
        :param argument: The argument, which is provided to the ConstraintHandler, when it is called. This argument can
        be an Exception, function, decision, or the result of the executed function.
        """
        pass


class ErrorConstraintHandlerProvider(ConstraintHandlerProvider, ABC):
    """
    A Class, which can be inherited to create a ConstraintHandlerProvider to handle Exceptions,
    which are thrown, when an error occurs while enforcing a decorated function or class
    """

    @abstractmethod
    def handle(self, exception: Exception) -> Exception:
        """
        Abstractmethod, which needs to be implemented by an ErrorConstraintHandlerProvider, which will be called by
        the ConstraintHandlerBundle if the ErrorConstraintHandlerProvider is responsible for a given constraint

        :param exception: Exception which should be handled
        :return: An Exception, which will be provided as Argument
        for the next ErrorConstraintHandlerProvider, or raised after when there is no next
        ErrorConstraintHandlerProvider
        """
        pass




class OnDecisionConstraintHandlerProvider(ConstraintHandlerProvider, ABC):
    """
    A Class, which can be inherited to create a ConstraintHandlerProvider which can handle a Decision,
    which is received from the PDP
    """

    @abstractmethod
    def handle(self, decision: Decision) -> None:
        """
        Abstractmethod, which needs to be implemented by an OnDecisionHandlerProvider, which will be called by
        the ConstraintHandlerBundle if the OnDecisionHandlerProvider is responsible for a given constraint

        :param decision: Decision which should be handled
        pass
        """





class FunctionArgumentsConstraintHandlerProvider(ConstraintHandlerProvider, ABC):
    """
    A Class, which can be inherited to create a ConstraintHandlerProvider to handle obligations and advices
    regarding the arguments, which with the enforced function will be called
    """

    @abstractmethod
    def handle(self, function_arguments: dict) -> dict:
        """
        Abstractmethod, which needs to be implemented by an FunctionArgumentsConstraintHandlerProvider, which will be
        called by the ConstraintHandlerBundle if the FunctionArgumentsConstraintHandlerProvider is responsible for a
        given constraint

        :param function_arguments: a dict containing the arguments, with which the enforced function will be called
        :return: a dict, with which the enforced function will be called
        """
        pass


class ResultConstraintHandlerProvider(ConstraintHandlerProvider, ABC):
    """
    A Class, which can be inherited to create a ConstraintHandlerProvider to handle obligations and advices regarding
    the result of the execution of the enforced function.
    """

    @abstractmethod
    def handle(self, result: Any) -> Any:
        """
        Abstractmethod, which needs to be implemented by an ResultConstraintHandlerProvider, which will be called by
        the ConstraintHandlerBundle if the ResultConstraintHandlerProvider is responsible for a given constraint

        :param result: the result of the enforced function, which was called
        :return: an object, which is treated as if it were the result of the execution of the enforced function
        """
        pass
