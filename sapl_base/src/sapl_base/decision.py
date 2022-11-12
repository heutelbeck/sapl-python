class Decision:
    """
    Class to represent a response from a policy decision point
    """
    obligations: list
    advice: list
    decision: str

    def __init__(self, decision_dict: dict):
        self.decision = decision_dict["decision"]

        self.obligations = decision_dict.get("obligations")
        if not self.obligations:
            self.obligations = []

        self.advice = decision_dict.get("advice")
        if not self.advice:
            self.advice = []

    @classmethod
    def deny_decision(cls):
        """
        create a Decision with denied permission
        :return:
        """
        return Decision({"decision": "DENY"})

    @classmethod
    def indeterminate_decision(cls):
        """
    create a Decision with an indeterminate decision
        :return:
        """
        return Decision({"decision": "INDETERMINATE"})

    @classmethod
    def permit_decision(cls):
        """
        create a Decision with permitted permission
        :return:
        """
        return Decision({"decision": "PERMIT"})
