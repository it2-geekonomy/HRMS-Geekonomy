"""
Remove all non-compensatory leave types and their related data from the local DB.
Use this to reset leave data so you can create leave types and assign them manually
with the standard (pre-custom-logic) behaviour.

Deletes: LeaveRequest, LeaveAllocationRequest, AvailableLeave, and LeaveType
where is_compensatory_leave=False. Compensatory leave types are kept.
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from leave.models import (
    AvailableLeave,
    LeaveAllocationRequest,
    LeaveRequest,
    LeaveType,
    RestrictLeave,
)


class Command(BaseCommand):
    help = (
        "Delete all non-compensatory leave types and related data. "
        "Use --all to also remove compensatory leave types."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Also delete compensatory leave types (default: only non-compensatory).",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Do not ask for confirmation.",
        )

    def handle(self, *args, **options):
        delete_compensatory = options["all"]
        no_input = options["no_input"]

        if delete_compensatory:
            types = LeaveType.objects.all()
        else:
            types = LeaveType.objects.filter(is_compensatory_leave=False)

        types = list(types)
        if not types:
            self.stdout.write(self.style.WARNING("No leave types to delete."))
            return

        names = [t.name for t in types]
        if not no_input:
            self.stdout.write(
                "Leave types to delete: " + ", ".join(names)
            )
            confirm = input("Proceed? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write("Aborted.")
                return

        with transaction.atomic():
            # 1. LeaveRequest (cascades to LeaveRequestConditionApproval, LeaverequestComment;
            #    WorkRecords.leave_request_id set to NULL)
            req_qs = LeaveRequest.objects.filter(leave_type_id__in=types)
            req_count = req_qs.count()
            req_qs.delete()
            self.stdout.write(f"Deleted {req_count} LeaveRequest(s).")

            # 2. LeaveAllocationRequest (cascades to LeaveallocationrequestComment)
            alloc_qs = LeaveAllocationRequest.objects.filter(leave_type_id__in=types)
            alloc_count = alloc_qs.count()
            alloc_qs.delete()
            self.stdout.write(f"Deleted {alloc_count} LeaveAllocationRequest(s).")

            # 3. AvailableLeave
            av_qs = AvailableLeave.objects.filter(leave_type_id__in=types)
            av_count = av_qs.count()
            av_qs.delete()
            self.stdout.write(f"Deleted {av_count} AvailableLeave(s).")

            # 4. Clear RestrictLeave M2M to these types
            for r in RestrictLeave.objects.all():
                r.spesific_leave_types.remove(*types)
                r.exclued_leave_types.remove(*types)
            self.stdout.write("Cleared RestrictLeave M2M for removed types.")

            # 5. leave_accrual_leaveaccrualconfig if it exists
            with connection.cursor() as cursor:
                try:
                    cursor.execute("""
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'leave_accrual_leaveaccrualconfig'
                    """)
                    if cursor.fetchone():
                        cursor.execute(
                            "DELETE FROM leave_accrual_leaveaccrualconfig WHERE leave_type_id IN %s",
                            [tuple(t.pk for t in types)],
                        )
                        self.stdout.write(
                            f"Deleted {cursor.rowcount} LeaveAccrualConfig row(s)."
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f"Note: leave_accrual: {e}")
                    )

            # 6. LeaveType
            for t in types:
                t.delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted LeaveType: {t.name}"))

        self.stdout.write(self.style.SUCCESS("Done. Create leave types and assign manually as needed."))
