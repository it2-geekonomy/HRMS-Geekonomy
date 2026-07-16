"""
App configuration for the Horilla Automations app.
Initializes model choices and starts automation when the server runs.
"""

import logging
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class HorillaAutomationConfig(AppConfig):
    """Configuration class for the Horilla Automations Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_automations"

    def ready(self):
        """Run initialization tasks when the app is ready."""
        from base.templatetags.horillafilters import app_installed
        from employee.models import Employee
        from horilla_automations.methods.methods import get_related_models
        from horilla_automations.models import MODEL_CHOICES as model_choices

        # Build MODEL_CHOICES
        models = [Employee]
        if app_installed("recruitment"):
            from recruitment.models import Candidate

            models.append(Candidate)

        for main_model in models:
            for model in get_related_models(main_model):
                model_choices.append(
                    (f"{model.__module__}.{model.__name__}", model.__name__)
                )

        model_choices.append(("employee.models.Employee", "Employee"))
        model_choices.append(("pms.models.EmployeeKeyResult", "Employee Key Results"))
        model_choices[:] = list(set(model_choices))  # Update in-place

        # Skip DB-backed automation wiring for management commands that do not
        # need it (and may run before tables exist).
        skip_cmds = {
            "makemigrations",
            "migrate",
            "compilemessages",
            "flush",
            "shell",
            "collectstatic",
            "showmigrations",
            "check",
        }
        if any(cmd in sys.argv for cmd in skip_cmds):
            return

        try:
            from horilla_automations.signals import start_automation

            start_automation()
        except Exception:
            # Table may not exist yet on first boot; avoid crashing startup.
            logger.exception("horilla_automations: start_automation skipped")
