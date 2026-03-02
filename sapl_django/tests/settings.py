from __future__ import annotations

SECRET_KEY = "test-secret-key-for-sapl-django-tests"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "sapl_django",
]

MIDDLEWARE = [
    "sapl_django.middleware.SaplRequestMiddleware",
]

SAPL_CONFIG = {
    "base_url": "http://localhost:8443",
    "allow_insecure_connections": True,
}

ROOT_URLCONF = "tests.urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}
