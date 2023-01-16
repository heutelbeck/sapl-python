import pytest
from flask import Flask

import sapl_flask
from sapl_flask.flask_authorization_subscription_factory import FlaskAuthorizationSubscriptionFactory


def subject_function(values :dict):
    return {"Anonymous"}


class TestSaplFlaskInit:

    @pytest.fixture()
    def app(self):
        app = Flask(__name__, instance_relative_config=True)
        app.config.from_mapping()
        return app

    def test_when_init_sapl_then_authorization_subscription_factory_is_flask(self, app):
        sapl_flask.init_sapl(app.config, [subject_function])
        from sapl_base.authorization_subscription_factory import auth_factory
        assert isinstance(auth_factory, FlaskAuthorizationSubscriptionFactory)
