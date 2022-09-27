from sapl_base.constraint_handler import ConstraintHandler


class ConstraintHandlerBundle:
    # TODO Use a Dictionary instead of an array to distinguish which handler shall be called at what stage
    # TODO async handling of Constraints
    obligation_handler = []
    advice_handler = []

    def _handle_obligation(self):
        pass

    def _handle_advices(self):
        pass

    def handle_constraints(self):
        pass

    def handle_constraints_with_value(self, *args,**kwargs):
        pass