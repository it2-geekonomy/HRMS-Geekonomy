"""
Show leave balance (available_days, carryforward_days, total) for an employee by badge.
Use after delete_leave_record to confirm the restored balance (e.g. Casual Leave).

Example:
  python manage.py show_leave_balance --badge GEEKY0004
"""

from django.core.management.base import BaseCommand

from employee.models import Employee
from leave.models import AvailableLeave


class Command(BaseCommand):
    help = "Show leave balance (available + carryforward = total) for an employee by badge ID."

    def add_arguments(self, parser):
        parser.add_argument(
            "--badge",
            type=str,
            required=True,
            help="Employee badge ID (e.g. GEEKY0004)",
        )

    def handle(self, *args, **options):
        badge = (options.get("badge") or "").strip()
        if not badge:
            self.stderr.write(self.style.ERROR("Required: --badge (e.g. --badge GEEKY0004)"))
            return

        employee = Employee.objects.filter(badge_id=badge).first()
        if not employee:
            self.stderr.write(self.style.ERROR(f"No employee found with badge_id: {badge}"))
            return

        self.stdout.write(
            self.style.SUCCESS(f"Leave balance for {employee.get_full_name()} ({badge}):")
        )
        qs = AvailableLeave.objects.filter(employee_id=employee).select_related("leave_type_id")
        if not qs.exists():
            self.stdout.write("  (No leave types assigned)")
            return

        for av in qs.order_by("leave_type_id__name"):
            lt = av.leave_type_id
            name = getattr(lt, "name", str(lt))
            avail = av.available_days or 0
            carry = av.carryforward_days or 0
            total = getattr(av, "total_leave_days", None)
            if total is None:
                total = round(avail + carry, 3)
            self.stdout.write(
                f"  {name}: available={avail}, carryforward={carry}, total={total}"
            )
