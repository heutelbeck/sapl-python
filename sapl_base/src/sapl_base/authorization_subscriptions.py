import json


class AuthorizationSubscription:
    """
    AuthorizationSubscriptions are sent to the PolicyDecisionPoint and based on their data a Decision is returned.
    """

    def __init__(self, subject, action, resource, environment=None,
                 subscription_id: int = None):
        """
        Create an AuthorizationSubscription Object with the given arguments

        :param subject: Subject, which describes for whom a Decision shall be made. This can be the logged in User for example
        :param action:  For which action shall a Decision be made? This can be a Requesttype like GET or POST for example
        :param resource: The resources for which a Decision shall be made. This can be for example the parameter of a GET request
        :param environment: Optional argument, which describes the environment. This can be for example the current time or location
        :param subscription_id: ID for the object. If no ID is provided an ID is created
        """
        if not (isinstance(subscription_id, int) or subscription_id is None):
            raise TypeError(
                f"subscription_id must be an int, was {subscription_id} type of {subscription_id.__class__}")

        self.subject = subject if subject else {}
        self.action = action if action else {}
        self.resource = resource if resource else {}

        if environment is not None:
            self.environment = environment
        if subscription_id is not None:
            self.subscription_id = subscription_id
        else:
            self.subscription_id = id(self)

    def __repr__(self):
        """
        representative of the object.
        """
        dictionary = self.__dict__.copy()
        representative = ",".join(element + "=" + repr(dictionary.get(element)) for element in dictionary)
        return f"{type(self).__name__}({representative})"

    def __str__(self):
        """
        Sting representation returns this object in json format as a string
        """
        dictionary = self.__dict__.copy()
        dictionary.pop("subscription_id")
        return json.dumps(dictionary, indent=2, skipkeys=True, default=lambda o: str(o))


class MultiSubscription:
    """
    Multiple AuthorizationSubscriptions can be gathered in a MultiSubscription, which can be sent to a
    PolicyDecisionPoint.The PDP will create individuell Decisions for each AuthorizationSubscription, but only one
    request is needed for all Decisions.
    """

    def __init__(
            self, subject=None, action=None, resource=None,
            environment=None,
            authorization_subscriptions=None,
    ):
        if subject is not None:
            self.subject = subject
        if action is not None:
            self.action = action
        if resource is not None:
            self.resource = resource
        if environment is not None:
            self.environment = environment

        self.authorization_subscriptions = authorization_subscriptions

    def __repr__(self):
        """
        representative of the object.
        """
        representative = ",".join(element + "=" + repr(self.__dict__.get(element)) for element in self.__dict__)
        return f"{type(self).__name__}({representative})"

    def __str__(self):
        """
        Sting representation returns this object in json format as a string
        """
        return json.dumps(self.__dict__, indent=2, skipkeys=True, default=lambda o: str(o))
