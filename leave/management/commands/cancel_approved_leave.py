"""
Cancel an approved leave from the backend (e.g. past dates when UI buttons are disabled).

Restores approved_available_days and approved_carryforward_days to AvailableLeave,
sets status to cancelled, clears clash count — same balance logic as leave_request_cancel.

Examples:
  python manage.py cancel_approved_leave --request-id 123 --reason "Admin correction"
  python manage.py cancel_approved_leave --badge GEEKY0007 --start-date 2026-03-25 --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from employee.models import Employee
from leave.models import AvailableLeave, LeaveRequest


class Command(BaseCommand):
    help = (
        "Cancel an approved leave request and credit leave back to the employee's balance."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--request-id",
            type=int,
            default=None,
            help="Primary key of the leave request (safest).",
        )
        parser.add_argument(
            "--badge",
            type=str,
            default=None,
            help="Employee badge_id (e.g. GEEKY0007). Use with --start-date if no --request-id.",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help="Leave start date YYYY-MM-DD (with --badge when multiple matches possible).",
        )
        parser.add_argument(
            "--reason",
            type=str,
            default="Retroactive cancellation by administrator (management command).",
            help="Stored in reject_reason for audit trail.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without saving.",
        )

    def handle(self, *args, **options):
        request_id = options.get("request_id")
        badge = (options.get("badge") or "").strip() or None
        start_date_s = (options.get("start_date") or "").strip() or None
        reason = options.get("reason") or ""
        dry_run = options.get("dry_run", False)

        leave_request = None
        if request_id:
            leave_request = LeaveRequest.objects.filter(pk=request_id).first()
            if not leave_request:
                self.stderr.write(
                    self.style.ERROR(f"No LeaveRequest with id={request_id}.")
                )
                return
        elif badge and start_date_s:
            from datetime import datetime

            try:
                start_d = datetime.strptime(start_date_s, "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write(
                    self.style.ERROR("--start-date must be YYYY-MM-DD.")
                )
                return
            employee = Employee.objects.filter(badge_id=badge).first()
            if not employee:
                self.stderr.write(
                    self.style.ERROR(f"No employee with badge_id={badge!r}.")
                )
                return
            qs = LeaveRequest.objects.filter(
                employee_id=employee,
                start_date=start_d,
                status="approved",
            ).order_by("-id")
            if qs.count() > 1:
                self.stderr.write(
                    self.style.WARNING(
                        f"Multiple approved requests for {badge} on {start_date_s}; "
                        "use --request-id. IDs: "
                        + ", ".join(str(x) for x in qs.values_list("id", flat=True)[:10])
                    )
                )
                return
            leave_request = qs.first()
            if not leave_request:
                self.stderr.write(
                    self.style.ERROR(
                        f"No approved LeaveRequest for badge={badge!r}, start_date={start_date_s}."
                    )
                )
                return
        else:
            self.stderr.write(
                self.style.ERROR(
                    "Provide --request-id OR both --badge and --start-date (YYYY-MM-DD)."
                )
            )
            return

        if leave_request.status != "approved":
            self.stderr.write(
                self.style.ERROR(
                    f"LeaveRequest id={leave_request.id} has status={leave_request.status!r}; "
                    "only approved requests can be cancelled with balance restore."
                )
            )
            return

        employee = leave_request.employee_id
        leave_type = leave_request.leave_type_id
        av_days = leave_request.approved_available_days or 0
        cf_days = leave_request.approved_carryforward_days or 0

        self.stdout.write(
            f"LeaveRequest id={leave_request.id}\n"
            f"  Employee: {employee} (badge={getattr(employee, 'badge_id', None)})\n"
            f"  Type: {leave_type}\n"
            f"  Dates: {leave_request.start_date} .. {leave_request.end_date}\n"
            f"  Requested days: {leave_request.requested_days}\n"
            f"  Restore to balance: available={av_days}, carryforward={cf_days}\n"
            f"  New status: cancelled\n"
            f"  Reason: {reason}\n"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes saved."))
            return

        with transaction.atomic():
            available_leave = AvailableLeave.objects.filter(
                leave_type_id=leave_type,
                employee_id=employee,
            ).first()
            if not available_leave:
                self.stderr.write(
                    self.style.ERROR(
                        "No AvailableLeave row for this employee and leave type; "
                        "cannot restore balance safely."
                    )
                )
                return

            available_leave.available_days = (available_leave.available_days or 0) + av_days
            available_leave.carryforward_days = (
                available_leave.carryforward_days or 0
            ) + cf_days
            available_leave.save()

            leave_request.approved_available_days = 0
            leave_request.approved_carryforward_days = 0
            leave_request.status = "cancelled"
            leave_request.leave_clashes_count = 0
            leave_request.reject_reason = reason[:255]
            leave_request.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Cancelled LeaveRequest id={leave_request.id} and restored balance."
            )
        )
