from django.apps import AppConfig, apps


class LeaveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "leave"

    def ready(self):
        from django.urls import include, path

        from horilla.horilla_settings import APPS
        from horilla.urls import urlpatterns

        if "leave" not in APPS:
            APPS.append("leave")

        leave_already_mounted = any(
            hasattr(p, "pattern") and getattr(p.pattern, "_route", None) == "leave/"
            for p in urlpatterns
        )
        if not leave_already_mounted:
            urlpatterns.append(
                path("leave/", include("leave.urls")),
            )

        # Connect signals after apps are loaded (lazy import to avoid circular dependency)
        from leave import signals

        signals.connect_signals()

        super().ready()
