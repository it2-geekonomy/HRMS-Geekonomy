from django.apps import AppConfig


class SpringVerificationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "spring_verification"
    verbose_name = "BGV"

    def ready(self):
        from horilla.horilla_settings import APPS

        APPS.append("spring_verification")
        # spring-verification/ URL is registered in horilla/urls.py (before base) so it is matched first on live
        super().ready()
