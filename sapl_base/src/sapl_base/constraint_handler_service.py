from sapl_base.constraint_handler import ConstraintHandler
from sapl_base.constraint_handler_bundle import ConstraintHandlerBundle
from sapl_base.sapl_util import NoHandlerException


class ConstraintHandlerService:
    # TODO Search project for classes which inherit from ConstraintHandler and add them to the
    #  ConstraintHandlerService instead of registering all ConstraintHandler manually

    _handlers = []

    def _get_responsible_handler(self, constraint):
        """
        Gathers all ConstraintHandler, which are responsible for the given constraint
        :param constraint: Constraint, which shall be handled by any ConstraintHandler
        :return: A list of ConstraintHandler, which are responsible for the given Constraint
        """
        responsible_handler = []
        handler: ConstraintHandler
        for handler in self._handlers:
            if handler.is_responsible(constraint):
                responsible_handler.append(handler)
        return responsible_handler

    @staticmethod
    def _get_capable_handler(constraint, handlers):
        """
        Gathers all ConstraintHandler, which are capable to handle the given constraint
        :param constraint: Constraint, which shall be handled by any ConstraintHandler
        :return: A list of ConstraintHandler, which are capable to handle the given Constraint
        """
        capable_handler = []
        handler: ConstraintHandler
        for handler in handlers:
            if handler.can_handle(constraint):
                capable_handler.append(handler)
        return capable_handler

    def register_handler(self, constraint_handler):
        """
        Registers a ConstraintHandler at the Service, which can handle Constraints of an Authorization_Decision
        :param constraint_handler: ConstraintHandler
        """
        if isinstance(constraint_handler, ConstraintHandler):
            self._handlers.append(constraint_handler)
        else:
            raise NoHandlerException

    def _gather_constraint_handler(self, constraints, is_obligations=True):
        """
        Gathers all ConstraintHandler, which are capable of handling all given Constraints.

        Throws an Exception, when no ConstraintHandler is capable of handling an Obligation.

        :param constraints: All Obligations, or Advices, which need to be handled
        :param is_obligations: Are the given constraints obligations, or advices?
        :return: List of ConstraintHandler, which are capable of handling the given Obligations or advices
        """
        constraint_handler = []
        for constraint in constraints:
            responsible_handler = self._get_responsible_handler(constraint)
            capable_handler = self._get_capable_handler(constraint, responsible_handler)
            if is_obligations and not capable_handler:
                raise Exception

            constraint_handler.append(capable_handler)
        return constraint_handler

    def create_constraint_handler_bundle(self, decision) -> ConstraintHandlerBundle:
        """
        Trys to create a ConstraintHandlerBundle and checks if all obligations can be handled.

        :param decision: Given Authorization_Decision, which can contain constrains
        :return: ConstraintHandlerBundle which can handle the Constraints
        """
        bundle = ConstraintHandlerBundle()
        if hasattr(decision, "obligations"):
            bundle.obligation_handler = self._gather_constraint_handler(decision.obligations)
        if hasattr(decision, "advices"):
            bundle.advices_handler = self._gather_constraint_handler(decision.advices, False)
        return bundle


constraint_handler_service = ConstraintHandlerService()
