from __future__ import annotations

from django.apps import AppConfig


class SaplDjangoConfig(AppConfig):
    """Django application configuration for SAPL authorization integration."""

    name = "sapl_django"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Validate SAPL configuration on Django startup."""
        from sapl_django.config import get_sapl_config

        get_sapl_config()
