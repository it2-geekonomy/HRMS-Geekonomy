"""
List employees (active and inactive) whose date of joining is missing.
Output: name, phone, work phone (if any), email, active status.
"""
import csv
import sys

from django.core.management.base import BaseCommand
from django.db.models import Q

from employee.models import Employee


class Command(BaseCommand):
    help = (
        "List all employees (active and inactive) whose date of joining is missing. "
        "Outputs: name, phone, work phone, email, is_active."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            action="store_true",
            help="Output as CSV to stdout (default: table to console)",
        )
        parser.add_argument(
            "--file",
            type=str,
            help="Write CSV to this file instead of stdout (implies --csv)",
        )

    def handle(self, *args, **options):
        # Employees with no work info, or work info with null date_joining
        qs = (
            Employee.objects.filter(
                Q(employee_work_info__isnull=True)
                | Q(employee_work_info__date_joining__isnull=True)
            )
            .select_related("employee_work_info")
            .order_by("employee_first_name", "employee_last_name")
        )

        rows = []
        for emp in qs:
            work = getattr(emp, "employee_work_info", None)
            work_phone = getattr(work, "mobile", None) or ""
            rows.append(
                {
                    "name": emp.get_full_name(),
                    "phone": emp.phone or "",
                    "work_phone": work_phone,
                    "email": emp.email or "",
                    "is_active": "Yes" if emp.is_active else "No",
                }
            )

        if not rows:
            self.stdout.write(
                self.style.SUCCESS("No employees found with missing date of joining.")
            )
            return

        out_csv = options["csv"] or options.get("file")
        if options.get("file"):
            with open(options["file"], "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["name", "phone", "work_phone", "email", "is_active"],
                )
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Written {len(rows)} employee(s) to {options['file']}"
                )
            )
            return

        if out_csv:
            writer = csv.DictWriter(
                sys.stdout,
                fieldnames=["name", "phone", "work_phone", "email", "is_active"],
            )
            writer.writeheader()
            writer.writerows(rows)
            return

        # Table to console
        self.stdout.write(
            self.style.WARNING(
                f"Employees with missing date of joining ({len(rows)} total):\n"
            )
        )
        col_name = "Name"
        col_phone = "Phone"
        col_work = "Work Phone"
        col_email = "Email"
        col_active = "Active"
        w_name = max(len(col_name), *[len(r["name"] or "") for r in rows], 4)
        w_phone = max(len(col_phone), *[len(r["phone"] or "") for r in rows], 5)
        w_work = max(len(col_work), *[len(r["work_phone"] or "") for r in rows], 10)
        w_email = max(len(col_email), *[len(r["email"] or "") for r in rows], 5)
        w_active = len(col_active)
        fmt = (
            f"{{:<{w_name}}} {{:<{w_phone}}} {{:<{w_work}}} {{:<{w_email}}} {{:<{w_active}}}"
        )
        self.stdout.write(fmt.format(col_name, col_phone, col_work, col_email, col_active))
        self.stdout.write("-" * (w_name + w_phone + w_work + w_email + w_active + 4))
        for r in rows:
            self.stdout.write(
                fmt.format(
                    r["name"][:w_name],
                    (r["phone"] or "-")[:w_phone],
                    (r["work_phone"] or "-")[:w_work],
                    (r["email"] or "-")[:w_email],
                    r["is_active"],
                )
            )
