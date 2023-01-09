# Library to integrate SAPL into a Flask project

SAPL_Flask is a library to use SAPL for a Flask Project.
SAPL (Streaming Attribute Policy Language) is a powerful policy language and engine to implement Attribute-based access control (ABAC)

For information about SAPL see [https://sapl.io](https://sapl.io)

# how to install

To install SAPL_Flask you can use `pip install sapl_flask`. 

# initialize the library

To use the Library you have to initialize it.
The init method needs two arguments, one of the Type Config and a list of Functions, which need a dict as argument and return a dict.
It should be initialized before you call `app.run()`

An example could look like this.
```
...
def subject_function(values:dict):
    return {"return_value": "subject"}

sapl_flask.init_sapl(app.config, [subject_function])
app.run()
```
How to write subject_functions is explained [here](#how-to-write-subject-functions)

# how to configure

SAPL creates a connection to a Policy Decision Point, which Parameters need to be configured.

Authorization Subscriptions are sent to the PDP to request a Decision, which is used by the Project and the Library to determine
the behaviour for the Decision.

The Configuration is loaded automatically, but has to be added to the Flask Config.
The Flask Config is searched for a Key: 'POLICY_DECISION_POINT', which contains a dict with key/value pairs for each parameter.

The Default Configuration in JSON Format looks like this:
```json
"POLICY_DECISION_POINT" = {
    "dummy": False,
    "base_url": "http://localhost:8080/api/pdp/",
    "key": "YJidgyT2mfdkbmL",
    "secret": "Fa4zvYQdiwHZVXh",
    "verify": False,
    "debug": False,
    "backoff_const_max_time": 1
}
```

# How to write subject functions

Subject functions need to be provided, when the library is initialized.
These functions determine, how the subject for the Authorization Subscription is created.

A subject function takes a dict as argument, which contains the decorated function, which is enforced and 
the arguments with which the function is called.

The dict, which has to be returned by the subject function is merged with the existing dict for the subject of the 
Authorization Subscription

# how to use it

Do use the library, you have to decorate a function, which shall be enforced by SAPL with one of 3 decorators.
`pre_enforce`, `post_enforce`, `pre_and_post_enforce`. These Decorators can take arguments for their subject, action, resource and environment.
If an argument is provided, these parameters are replaced by the provided arguments.

These arguments can either be simple values, or can be functions, which get called instead of the default function to create 
these parameters.

Important: If a function has multiple decorators, the SAPL decorator has to be the first one.

# how to migrate

If you have an existing project of Flask you can migrate it, as if it were a new project, 
you have to add the configuration and initialize the Library at the start.

