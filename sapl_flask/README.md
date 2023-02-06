# SAPL Integration library for Flask

This library enables the usage of SAPL for a Flask application by providing decorators to enforce functions with SAPL functionality.
Basic knowledge about Attributes based access control(ABAC) is beneficial to understand the functionality of this library.

If you don't have any knowledge about ABAC, you should read the SAPL [documentation](https://sapl.io/documentation) before you continue reading.

## What is SAPL

SAPL is a further development of ABAC and can be described as Attribute-Stream-Based Access Control (ASBAC).
In contrary to ABAC, which is based on a request-response model and demands a new connection whenever a new decision is 
needed, SAPL works on a publish/subscribe model.
The client sends an Authorization Subscription to the Policy Decision Point(PDP) and receives a stream of Decisions, 
which can update the decision for the given Subscription for the client. 

The functionality of updating and enforcing newly received Decisions is done by the library in the background, so the 
developer can concentrate on writing the policies.

A complete documentation of SAPL can be found at [https://sapl.io](https://sapl.io), which also contains a playground to
write policies.


## how to install

The SAPL Flask integration library is released on PyPI and can be installed with the Package Manager pip.

To install SAPL_Flask you can use `pip install sapl_flask`. 

## Initialize the library

To initialize the library, the `init_sapl` function, which takes two arguments has to be called.

`def init_sapl(config: Config, subject_function: Callable[[], Any]):`

The first argument is an argument of the type Configuration, which works exactly like a dictionary.
The 2nd argument is a function, which returns Any, which will be the Subject of the Authorization Subscription.
What these functions are and how to write them is explained in the section [How to write subject function](#how-to-write-subject-function).

A simple project, which uses pre_enforce for a route, initializes SAPL_Flask and starts a Flask application would look like this:
```Python
import sapl_flask
from flask import Flask
from flask import session
from sapl_base.decorators import pre_enforce
app = Flask(__name__)

def subject_function():
  try:
    return session['access_token']
  except KeyError:
    return None

@app.route('/')
@pre_enforce
def hello_world():
  return "Hello World!"

if __name__ == "__main__":
    sapl_flask.init_sapl(app.config, subject_function)
    app.run()
```

## How to configure SAPL_Flask

The configuration is used to determine, how to connect to the PDP.
This PDP should be a SAPL server, for which a documented open source version is available on 
[GitHub](https://github.com/heutelbeck/sapl-policy-engine/tree/master/sapl-server-lt).

The easiest way to configure SAPL_Flask is to add a key `"POLICY_DECISION_POINT"` with according values to your Flask 
Configuration and use your Flask Configuration as the 1st argument of the init method.

The default configuration in JSON Format looks like this:
```json
{
  "POLICY_DECISION_POINT" : {
    "base_url": "http://localhost:8080/api/pdp/",
    "key": "YJidgyT2mfdkbmL",
    "secret": "Fa4zvYQdiwHZVXh",
    "dummy": false,
    "verify": false,
    "debug": false,
    "backoff_const_max_time": 1
  }
}
```
- base_url: The URL, where your PDP Server is located. This has to include the path `'/api/pdp/'` of the PDP Server. 
- key: Access to the API of the SAPL PDP Server requires "Basic Auth". The client key (username) can be set with this parameter.
  The default is the default implemented credentials of a [SAPL-Server-lt](https://github.com/heutelbeck/sapl-policy-engine/tree/master/sapl-server-lt)
- secret: The password which is used to get access to the API.
- dummy: Enables a dummy PDP, which is used instead of a remote PDP. This PDP always grants access and should never be used in production.
- verify: 
- debug: Enables debugging , which adds logging.
- backoff_const_max_time: When an error occurs, while requesting a Decision from the PDP SAPL_Flask does a retry. 
  This parameter determines, how many seconds the library should retry to connect, before it aborts and denies the access.

# Subject functions

For authentication, it has to be known who(subject) does the request. Flask does not have authentication built in 
from which the library could gather information about who did the request.
To determine who is requesting something you need to provide a function, which creates the subject for an Authorization 
Subscription. This function is called, whenever an Authorization Subscription is created. 
The value this function returns is used to create the subject for the Authorization Subscription.

## How to write a subject function

Subject function can be any function without parameter, which returns Any.
This function is called, when an Authorization Subscription is created.

An example for a subject function, where the subject is the access token of a session, if it is available.
```Python
from flask import session

def subject_function():
  try:
    return session['access_token']
  except KeyError:
    return None
```
If the function does return None, or an empty list, or dict, the subject will be set to "anonymous"

A Flask project, which uses SAPL_Flask, which is initialized with default configuration and this subject_function would be:

```Python
import sapl_flask
from flask import Flask
from flask import session
from sapl_base.decorators import pre_enforce
app = Flask(__name__)

def subject_function():
  try:
    return session['access_token']
  except KeyError:
    return None

@app.route('/')
@pre_enforce
def hello_world():
  return "Hello World!"

if __name__ == "__main__":
    sapl_flask.init_sapl(app.config, subject_function)
    app.run()
```

# How to use it

To implement SAPL into a Flask project, the functions, which shall be enforced by SAPL have to be decorated with SAPL decorators.
The decorator have to be the first decorator of a function. There are 3 possible decorators, which can be used for a function.

- `pre_enforce` when a function shall be enforced, before it is called.
- `post_enforce` when the function is already executed and the return_value is needed to determine if the requesting client has access to these data.
- `pre_and_post_enforce` when the function is enforced before and after it is called. This decorator can be used,
when the return value of the function is needed to finally decide if access can be granted, but the execution of the 
function is expensive and there are certain parameters of a request, which can already be used to deny access before the 
return value is known.

an example for a pre_enforced function would be:
```Python
from sapl_base.decorators import pre_enforce

@pre_enforce
def pre_enforced_function(*args,**kwargs):
    return_value = "Do something"
    return return_value
```

A decorated function will use the default implementation to create a subject,action and resources of an Authorization Subscription.
If no subject_functions are provided the subject is always "anonymous".

subject, action and resources are dictionarys, which are json dumped with a default JSON Converter.
These 3 dictionarys json formatted contain these values:

```json
{
  "subject": "is determined by the subject_functions",
  
  "action": {
    "function": {
      "function_name": "name of the function"
    },
    "request": {
      "path": "request.path",
      "method": "request.method",
      "endpoint": "request.endpoint",
      "route": "request.root_url",
      "blueprint": "request.blueprint"
    }
  },
  "resources": {
    "function": {
      "kwargs": "arguments with which the decorated function was called"
    },
    "request": {
      "GET" : "Arguments of the GET Request",
      "POST" : "Arguments of the POST Request"
    },
    "return_value": "Return value of the decorated function"
  }
}
```
To determine, who should have access to what values, Policies have to be written, which are used by the SAPL Server 
to evaluate the Decision for an Authorization Subscription.

Decisions can contain Obligations and Advices, which are in details explained in the section [Obligations and Advices].(#obligations-and-advices)
More Information about SAPL Server, Authorization Subscriptions, Obligations and Advices can be found in the 
[SAPL documentation](https://sapl.io/documentation)

SAPL_Flask does also support writing custom functions for the subject,action and/or resources of an Authorization 
Subscription, as well as providing values for these parameters, which replaces the default functions for these values.

## Providing arguments to a decorator

Instead of using the default implementation on how the subject,action and/or resources are created, it is possible to 
use values, or create your own functions to determine these values.
An example on how to use a constant as the value for the `action` argument would be
```Python
from sapl_base.decorators import pre_enforce

@pre_enforce(action="retrieve data")
def pre_enforced_function():
    return_value = "You are granted access to these data"
    return return_value
```
Whenever this function is called, it will be enforced before it is executed.
The value of the 'action' parameter of the Authorization Subscription will always be "retrieve data"

A more dynamic approach could get the type and path of the request, create a dictionary from these values and set this 
dictionary as action.
```Python
from flask import request
from sapl_base.decorators import pre_enforce

def create_action():
  return {"method": request.method,"path":request.path}

@pre_enforce(action=create_action)
def pre_enforced_function(*args,**kwargs):
    return_value = "Do something"
    return return_value
```


# Obligations and Advices

A Decision from the PDP can have Constraints attached to the Decision. There are two different kinds of Constraints,
Obligations and Advices. Obligations have to be handled, otherwise the Permission is Denied. Advices should be handled, 
but the Decision won't change when the Advices are not handled.

To handle these Constraints, this library offers an abstract class called `ConstraintHandlerProvider`, which can handle 
Constraints. The classes, which can handle the constraints are created by the developer and have to be registered to be available 
to the library, to check if given constraints can be handled.


## How to create ConstraintHandlerProvider

In order to create ConstraintHandlerProvider, 4 abstract ConstraintHandlerProvider are available to inherit from. These
abstract classes are: 

- `ErrorConstraintHandlerProvider`
- `OnDecisionConstraintHandlerProvider`
- `FunctionArgumentsConstraintHandlerProvider`
- `ResultConstraintHandlerProvider`

They all inherit from the base class `ConstraintHandlerProvider` and only differ in the types of the arguments their methods
take and return.

The Baseclass is defined like this:
```python
from abc import abstractmethod, ABC

class ConstraintHandlerProvider(ABC):
  
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
```

When a Decision contains a Constraint, the library checks all registered Constraint handler provider, if their 
`is_responsible` method evaluates to true for the given Constraint. 
The responsible Constraint handler provider are gathered and 
sorted by the value their method `priority` returns.
At the end, the `handle` methods of the sorted list of `ConstraintHandlerProvider`, which are responsible for a given 
Constraint are executed in the order of the list.

An example for a ConstraintHandlerProvider, which logs the received Decision when it contains a constraint which 
equals to "log decision" would be:
```python
from sapl_base.decision import Decision
from sapl_base.constraint_handling.constraint_handler_provider import OnDecisionConstraintHandlerProvider
import logging

class LogNewDecisionConstraintHandler(OnDecisionConstraintHandlerProvider):

    def handle(self, decision: Decision) -> None:
        logging.info(str(decision))

    def priority(self) -> int:
        return 0

    def is_responsible(self, constraint) -> bool:
        return True if constraint == "log decision" else False
```

## How to register ConstraintHandlerProvider

The class `ConstraintHandlerService` handles any Constraints and contains a singleton(constraint_handler_service), which 
is created when the file is loaded. All `ConstraintHandlerProvider` registered at this singleton are taken into account, 
when the Constraints of a Decision are checked, if they can be handled.

The ConstraintHandlerService has methods to register single ConstraintHandlerProvider, or lists of ConstraintHandlerProvider 
for each of the 4 types of ConstraintHandlerProvider.

The following code would initialize the library, register the previously created ConstraintHandlerProvider and launch 
the Flask app.

```Python
import sapl_flask
from sapl_base.constraint_handling.constraint_handler_service import constraint_handler_service
from sapl_base.decision import Decision
from sapl_base.decorators import pre_enforce
from sapl_base.constraint_handling.constraint_handler_provider import OnDecisionConstraintHandlerProvider
import logging
from flask import Flask,session


app = Flask(__name__)

class LogNewDecisionConstraintHandler(OnDecisionConstraintHandlerProvider):

    def handle(self, decision: Decision) -> None:
        logging.info(str(decision))

    def priority(self) -> int:
        return 0

    def is_responsible(self, constraint) -> bool:
        return True if constraint == "log decision" else False

def subject_function():
  try:
    return session['access_token']
  except KeyError:
    return None

@app.route('/')
@pre_enforce
def hello_world():
  return "Hello World!"
  
if __name__ == "__main__":
    sapl_flask.init_sapl(app.config, subject_function)
    constraint_handler_service.register_decision_constraint_handler_provider(LogNewDecisionConstraintHandler())
    app.run()
```

# How to migrate

If you have an existing project of Flask, you can add SAPL_Flask by installing and initializing the library.
The library can then be used by decorating functions and writing policies.

