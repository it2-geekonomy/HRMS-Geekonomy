"""
Create the Special Allowance: Total Salary - (Basic + HRA + Conveyance + Medical).
Run once: python manage.py create_special_allowance
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from payroll.models.models import Allowance

User = get_user_model()


# Allowance.save() and HorillaModel read request from thread_locals; use minimal mock when running from CLI
class _MockSession:
    def get(self, key, default=None):
        return "all" if key == "selected_company" else default


class _MockRequest:
    session = _MockSession()
    user = None  # set in handle() to first superuser or first user


class Command(BaseCommand):
    help = (
        "Create Special Allowance (monthly total salary - basic - HRA - Conveyance - Medical) "
        "if it does not exist. Applies to all active employees."
    )

    def handle(self, *args, **options):
        if Allowance.objects.filter(
            title="Special Allowance", based_on="special_allowance"
        ).exists():
            self.stdout.write(
                self.style.WARNING("Special Allowance already exists.")
            )
            return
        # Allowance.save() uses request from thread_locals; set mock for CLI
        import horilla.horilla_middlewares as hm
        mock = _MockRequest()
        mock.user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        old_request = getattr(hm._thread_locals, "request", None)
        hm._thread_locals.request = mock
        try:
            allowance = Allowance(
                title="Special Allowance",
                based_on="special_allowance",
                is_fixed=False,
                include_active_employees=True,
                is_taxable=True,
                is_condition_based=False,
            )
            allowance.save()
        finally:
            hm._thread_locals.request = old_request
        self.stdout.write(
            self.style.SUCCESS(
                "Special Allowance created. "
                "Formula: Total Salary - (Basic + House Rent Allowance + Conveyance/LTA + Medical Allowance)."
            )
        )
