import json


class AuthorizationSubscription:
    """
    Build the authorization subscription for the SAPL-Server in json-format
    """

    def __init__(self, subject=None, action=None, resource=None,
                 environment=None,
                 subscription_id: int = None):
        if not (isinstance(subscription_id, int) or subscription_id is None):
            raise TypeError(
                f"subscription_id must be an int, was {subscription_id} type of {subscription_id.__class__}")
        if subject is not None:
            self.subject = subject
        if action is not None:
            self.action = action
        if resource is not None:
            self.resource = resource
        if environment is not None:
            self.environment = environment
        if subscription_id is not None:
            self.subscription_id = subscription_id
        else:
            self.subscription_id = id(self)

    def __repr__(self):
        """
        representation of an AuthorizationSubscription,
        eval will convert it to an object
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
        representation of an AuthorizationSubscription,
        eval will convert it to an object
        """
        representative = ",".join(element + "=" + repr(self.__dict__.get(element)) for element in self.__dict__)
        return f"{type(self).__name__}({representative})"

    def __str__(self):
        """
        Sting representation returns this object in json format as a string
        """
        return json.dumps(self.__dict__, indent=2, skipkeys=True, default=lambda o: str(o))
