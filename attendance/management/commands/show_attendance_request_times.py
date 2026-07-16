"""
Show check-in / check-out an employee submitted (or has on record) for a given date.

Uses the Attendance row and optional requested_data snapshot from when they raised
the validate request.

Usage:
  python manage.py show_attendance_request_times --badge GEEKY0029 --date 2026-03-18
  python manage.py show_attendance_request_times --badge GEEKY0029 --date 18-03-2026
"""

import json
from datetime import datetime

from django.core.management.base import BaseCommand

from attendance.models import Attendance, AttendanceRequestLog
from employee.models import Employee


def _parse_date(s: str):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise 

    
    
    (f"Unrecognized date: {s!r} (try YYYY-MM-DD or DD-MM-YYYY)")


def _requested_data_dict(raw):
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


class Command(BaseCommand):
    help = "Print check-in/out for an employee on a date (current record + requested_data if any)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--badge",
            type=str,
            help="Employee badge_id (e.g. GEEKY0029)",
            default=None,
        )
        parser.add_argument(
            "--employee-id",
            type=int,
            help="Primary key of Employee",
            default=None,
        )
        parser.add_argument(
            "--date",
            type=str,
            required=True,
            help="Attendance date: YYYY-MM-DD or DD-MM-YYYY",
        )

    def handle(self, *args, **options):
        badge = (options.get("badge") or "").strip() or None
        emp_pk = options.get("employee_id")
        try:
            d = _parse_date(options["date"])
        except ValueError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return

        emp = None
        if emp_pk:
            emp = Employee.objects.filter(pk=emp_pk, is_active=True).first()
        elif badge:
            emp = Employee.objects.filter(badge_id__iexact=badge, is_active=True).first()
        else:
            self.stdout.write(
                self.style.ERROR("Provide --badge BADGE or --employee-id PK.")
            )
            return

        if not emp:
            self.stdout.write(
                self.style.ERROR("No active employee found for that badge / id.")
            )
            return

        self.stdout.write(self.style.SUCCESS(f"Employee: {emp} (pk={emp.pk})"))
        self.stdout.write(f"Attendance date: {d}")

        att = (
            Attendance.objects.filter(employee_id=emp, attendance_date=d)
            .order_by("-id")
            .select_related("employee_id", "shift_id")
            .first()
        )

        if not att:
            self.stdout.write(
                self.style.WARNING("No Attendance row for this employee on that date.")
            )
            return

        self.stdout.write("")
        self.stdout.write("--- Current fields on Attendance (after any approval) ---")
        self.stdout.write(f"  attendance_clock_in_date: {att.attendance_clock_in_date}")
        self.stdout.write(f"  attendance_clock_in:       {att.attendance_clock_in}")
        self.stdout.write(f"  attendance_clock_out_date: {att.attendance_clock_out_date}")
        self.stdout.write(f"  attendance_clock_out:      {att.attendance_clock_out}")
        self.stdout.write(f"  request_type:              {att.request_type}")
        self.stdout.write(f"  request_description:       {att.request_description!r}")
        self.stdout.write(
            f"  is_validate_request:       {att.is_validate_request} | "
            f"is_validate_request_approved: {att.is_validate_request_approved}"
        )

        snap = _requested_data_dict(att.requested_data)
        if snap:
            self.stdout.write("")
            self.stdout.write(
                "--- Snapshot from requested_data (values submitted with the request) ---"
            )
            for key in (
                "attendance_clock_in",
                "attendance_clock_out",
                "attendance_clock_in_date",
                "attendance_clock_out_date",
                "attendance_date",
                "shift_id",
                "work_type_id",
            ):
                if key in snap:
                    self.stdout.write(f"  {key}: {snap[key]!r}")
            other = {k: v for k, v in snap.items() if k not in (
                "attendance_clock_in",
                "attendance_clock_out",
                "attendance_clock_in_date",
                "attendance_clock_out_date",
                "attendance_date",
                "shift_id",
                "work_type_id",
                "employee_id",
            )}
            if other:
                self.stdout.write("  (other keys:)")
                for k, v in sorted(other.items()):
                    self.stdout.write(f"    {k}: {v!r}")
        else:
            self.stdout.write("")
            self.stdout.write(
                "(No requested_data JSON stored — times above are what is on the record now.)"
            )

        logs = AttendanceRequestLog.objects.filter(
            employee_id=emp,
            attendance_id=att,
        ).order_by("-performed_at")[:10]

        if logs:
            self.stdout.write("")
            self.stdout.write("--- Recent AttendanceRequestLog for this row (latest first) ---")
            for log in logs:
                who = (
                    log.performed_by.get_full_name()
                    if log.performed_by_id
                    else "—"
                )
                self.stdout.write(
                    f"  {log.performed_at} | {log.action} | by {who} | {log.description[:80] if log.description else ''}"
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done."))
