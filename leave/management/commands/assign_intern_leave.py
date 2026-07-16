"""
Assign Intern Sick Leave (ISL) to interns only; remove SL/CL/EL from interns.

Run after setup_new_leave_types. Use fix_leave_balances to set ISL balance (1 per 3 months).
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from employee.models import EmployeeWorkInformation
from leave.models import LeaveType, AvailableLeave
from leave.intern_leave import is_intern, intern_sl_balance, ensure_intern_sl_available_leave


class Command(BaseCommand):
    help = "Assign Intern Sick Leave (ISL) to interns; remove SL/CL/EL from interns"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        today = timezone.now().date()

        try:
            isl_type = LeaveType.objects.get(name="Intern Sick Leave (ISL)")
            sl_type = LeaveType.objects.get(name="Sick Leave (SL)")
            cl_type = LeaveType.objects.get(name="Casual Leave (CL)")
            el_type = LeaveType.objects.get(name="Earned Leave (EL)")
        except LeaveType.DoesNotExist as e:
            self.stdout.write(self.style.ERROR(f"Leave type not found: {e}. Run setup_new_leave_types first."))
            return

        work_infos = (
            EmployeeWorkInformation.objects.filter(date_joining__isnull=False)
            .select_related("employee_id", "employee_type_id")
            .order_by("date_joining")
        )

        assigned = 0
        removed = 0

        for wi in work_infos:
            emp = wi.employee_id
            if not is_intern(emp):
                continue

            if dry_run:
                self.stdout.write(f"Would process intern: {emp.get_full_name()} (id={emp.id})")
                balance, bs, be = intern_sl_balance(emp)
                self.stdout.write(f"  ISL balance: {balance:.2f} (1 per 3 months)")
                for lt in [sl_type, cl_type, el_type]:
                    if AvailableLeave.objects.filter(employee_id=emp, leave_type_id=lt).exists():
                        self.stdout.write(f"  Would remove {lt.name}")
                assigned += 1
                continue

            with transaction.atomic():
                balance, _, _ = intern_sl_balance(emp)
                av = ensure_intern_sl_available_leave(emp, isl_type, balance, today)
                av.save()
                assigned += 1
                self.stdout.write(self.style.SUCCESS(f"Assigned ISL to {emp.get_full_name()} (balance={balance:.2f})"))

                for lt in [sl_type, cl_type, el_type]:
                    deleted, _ = AvailableLeave.objects.filter(
                        employee_id=emp, leave_type_id=lt
                    ).delete()
                    if deleted:
                        removed += deleted
                        self.stdout.write(self.style.WARNING(f"  Removed {lt.name} from {emp.get_full_name()}"))

        if dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN ===\n"))
        self.stdout.write(
            self.style.SUCCESS(f"Processed {assigned} intern(s); removed {removed} SL/CL/EL assignment(s).")
        )
