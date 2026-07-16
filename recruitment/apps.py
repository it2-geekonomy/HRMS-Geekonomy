"""
apps.py
"""

from django.apps import AppConfig


class RecruitmentConfig(AppConfig):
    """
    AppConfig for the 'recruitment' app.

    This class represents the configuration for the 'recruitment' app. It provides
    the necessary settings and metadata for the app.

    Attributes:
        default_auto_field (str): The default auto field to use for model field IDs.
        name (str): The name of the app.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "recruitment"

    def ready(self):
        from horilla.horilla_settings import APPS
        from recruitment import signals

        APPS.append("recruitment")
        # recruitment/ URLs are included in horilla.urls to avoid 404 on live
        # when URL resolver is built before ready() runs (e.g. Gunicorn preload)
        super().ready()
