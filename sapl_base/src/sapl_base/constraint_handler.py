from abc import ABC, abstractmethod


class ConstraintHandler(ABC):
    # TODO create async def handle function
    """"
    BaseClass of a ConstraintHandler, which can be used as an Interface to create ConstraintHandler for the ConstraintHandlerService
    """

    @abstractmethod
    def is_responsible(self, constraint):
        pass

    @abstractmethod
    def can_handle(self, constraint):
        pass

    @abstractmethod
    def handle(self, constraint, *args, **kwargs):
        pass
