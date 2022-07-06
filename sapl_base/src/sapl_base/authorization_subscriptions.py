import json

import logging


class AuthorizationSubscription:
    """
    Build the authorization subscription for the SAPL-Server in json-format
    """

    def __init__(self, subject: dict | list = None, action: dict | list = None, resource: dict | list = None,
                 environment: dict | list = None,
                 subscription_id: int = None):

        self.subject = subject
        self.action = action
        self.resource = resource
        self.environment = environment
        if subscription_id is not None:
            self.subscription_id = subscription_id
        else:
            self.subscription_id = id(self)

    def __repr__(self):
        """
        representation of python object AuthorizationSubscription,
        usually eval will convert it back to that object
        """
        dictionary = self._clean_dict()
        representative = ",".join(element + "=" + repr(dictionary.get(element)) for element in dictionary)
        return f"{type(self).__name__}({representative})"

    def __eq__(self, other):
        try:
            return (self.subject == other.subject) and (
                    self.action == other.action) and (
                           self.resource == other.resource) and (
                           self.environment == other.environment) and (
                           self.subscription_id == other.subscription_id)
        except AttributeError:
            return False
        except Exception as e:
            logging.exception(e)
            return False

    def __str__(self):
        """
        The Method __str__ gives back a json of the AuthorizationSubscription
        """
        dictionary = self._clean_dict()
        dictionary.pop("subscription_id")
        return json.dumps(dictionary, indent=2, skipkeys=True, default=lambda o: str(o))

    def _clean_dict(self):
        dictionary = self.__dict__.copy()
        for element in self.__dict__:
            if self.__dict__.get(element) is None:
                dictionary.pop(element)
        return dictionary


class MultiSubscription:
    def __init__(
            self, subject: dict | list = None, action: dict | list = None, resource: dict | list = None,
            environment: dict | list = None,
            authorization_subscriptions: dict | list = None,
    ):

        self.subject = subject
        self.action = action
        self.resource = resource
        self.environment = environment
        self.authorization_subscriptions = authorization_subscriptions

    def __repr__(self):
        """
        representation of python object AuthorizationSubscription,
        usually eval will convert it back to that object
        """
        dictionary = self.__dict__
        for element in dictionary:
            if element is None: del element
        representative = ",".join(element + "=" + repr(dictionary.get(element)) for element in dictionary)
        return f"{type(self).__name__}({representative})"

    def __str__(self):
        """
        The Method __str__ gives back a json of the AuthorizationSubscription
        """
        dictionary = self.__dict__.copy()
        for element in self.__dict__:
            if self.__dict__.get(element) is None:
                dictionary.pop(element)
        return json.dumps(dictionary, indent=2, skipkeys=True, default=lambda o: str(o))

    def __eq__(self, other):
        try:
            return (self.subject == other.subject) and (
                    self.action == other.action) and (
                           self.resource == other.resource) and (
                           self.environment == other.environment) and (
                           self.authorization_subscriptions == other.authorization_subscriptions)
        except AttributeError:
            return False
        except Exception as e:
            logging.exception(e)
            return False
