"""
Export Absent (A) work records for active employees to Excel.

Matches Attendance Calendar logic: ABS records and default (DFT) days on/after
the employee's joining/first-attendance date count as Absent (A).

Usage:
    python manage.py export_absent_records
    python manage.py export_absent_records --year 2026 --start-month 1 --end-month 6
    python manage.py export_absent_records --output C:\\Reports\\absent_jan_jun_2026.xlsx
"""

import calendar
import os
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db.models import Min, Q

from attendance.methods.utils import monthly_holiday_dates, monthly_leave_days
from attendance.models import Attendance, WorkRecords
from employee.models import Employee, EmployeeWorkInformation

EXCLUDED_BADGE_IDS = ["GEEKY0001"]


def _employee_effective_from(employee_ids):
    joining_by_emp = {
        row["employee_id"]: row["date_joining"]
        for row in EmployeeWorkInformation.objects.filter(
            employee_id__in=employee_ids
        ).values("employee_id", "date_joining")
    }
    first_attendance_by_emp = {
        row["employee_id"]: row["first_date"]
        for row in Attendance.objects.filter(employee_id__in=employee_ids)
        .values("employee_id")
        .annotate(first_date=Min("attendance_date"))
    }
    return {
        eid: joining_by_emp.get(eid) or first_attendance_by_emp.get(eid)
        for eid in employee_ids
    }


def _leave_overlay_keys(employee_ids, month_dates, work_records_dict):
    pl_dates = set()
    hp_l_dates = set()
    sp_l_dates = set()
    if not apps.is_installed("leave"):
        return pl_dates, hp_l_dates, sp_l_dates

    from leave.models import LeaveRequest, leave_requested_dates

    month_dates_set = set(month_dates)
    first_day = month_dates[0]
    last_day = month_dates[-1]
    leaves = LeaveRequest.objects.filter(
        status="approved",
        employee_id__in=employee_ids,
        start_date__lte=last_day,
        start_date__gte=first_day,
    ).filter(Q(end_date__gte=first_day) | Q(end_date__isnull=True)).values(
        "employee_id",
        "start_date",
        "end_date",
        "requested_days",
        "start_date_breakdown",
        "end_date_breakdown",
    )
    for lr in leaves:
        end = lr["end_date"] or lr["start_date"]
        for day in leave_requested_dates(lr["start_date"], end):
            if day not in month_dates_set:
                continue
            is_half = (
                (lr["requested_days"] == 0.5 and lr["start_date"] == end)
                or (
                    day == lr["start_date"]
                    and lr["start_date_breakdown"] in ("first_half", "second_half")
                )
                or (
                    day == lr["end_date"]
                    and lr["end_date_breakdown"] in ("first_half", "second_half")
                )
            )
            key = f"{lr['employee_id']}_{day.isoformat()}"
            wr = work_records_dict.get((lr["employee_id"], day))
            if is_half and wr:
                if wr.work_record_type in ("FDP", "HDP"):
                    hp_l_dates.add(key)
                elif wr.work_record_type == "SP":
                    sp_l_dates.add(key)
            elif wr and wr.work_record_type == "FDP":
                pl_dates.add(key)
            elif wr and wr.work_record_type == "SP":
                sp_l_dates.add(key)
    return pl_dates, hp_l_dates, sp_l_dates


def _display_code(
    employee,
    day,
    record_type,
    *,
    leave_dates,
    holiday_dates,
    pl_dates,
    hp_l_dates,
    sp_l_dates,
    attendance_request_cell_keys,
    leave_request_cell_keys,
    effective_from,
):
    """Return calendar display code for one employee/day (same rules as calendar export)."""
    if day in holiday_dates and record_type in ("", "DFT"):
        val = "PH"
    elif day in leave_dates and record_type in ("", "DFT"):
        val = "WO"
    elif record_type == "FDP":
        key = f"{employee.id}_{day.isoformat()}"
        if key in pl_dates:
            val = "P/L"
        elif key in hp_l_dates:
            val = "HP/L"
        else:
            val = "P"
    elif record_type == "HDP":
        key = f"{employee.id}_{day.isoformat()}"
        val = "HP/L" if key in hp_l_dates else "HP"
    elif record_type == "SP":
        key = f"{employee.id}_{day.isoformat()}"
        val = "SP/L" if key in sp_l_dates else "SP"
    elif record_type == "ABS":
        val = "A"
    elif record_type == "DFT":
        val = "A" if effective_from and day >= effective_from else ""
    elif record_type == "MP":
        val = "MP"
    elif record_type in ("L", "HD"):
        val = "L"
    elif record_type == "CONF":
        val = "AR"
    else:
        val = "" if record_type in ("", None) else record_type

    key = f"{employee.id}_{day.isoformat()}"
    if key in attendance_request_cell_keys:
        val = "AR"
    if key in leave_request_cell_keys:
        val = "LR"
    return val


def collect_absent_rows(year, start_month=1, end_month=6):
    """Return list of absent record dicts for active employees in the month range."""
    range_start = date(year, start_month, 1)
    range_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    employees = list(
        Employee.objects.filter(is_active=True)
        .exclude(badge_id__in=EXCLUDED_BADGE_IDS)
        .order_by("employee_first_name", "employee_last_name")
    )
    employee_ids = [employee.id for employee in employees]
    effective_from_map = _employee_effective_from(employee_ids)
    today = date.today()
    rows = []

    for month in range(start_month, end_month + 1):
        num_days = calendar.monthrange(year, month)[1]
        month_dates = [date(year, month, day) for day in range(1, num_days + 1)]
        leave_dates = set(monthly_leave_days(month, year))
        holiday_dates = set(monthly_holiday_dates(month, year))
        month_dates_set = set(month_dates)

        records = WorkRecords.objects.filter(
            date__month=month,
            date__year=year,
            date__lte=today,
            employee_id__in=employee_ids,
        ).select_related("employee_id")

        record_lookup = defaultdict(lambda: "DFT")
        work_records_dict = {}
        for record in records:
            record_lookup[(record.employee_id, record.date)] = record.work_record_type
            work_records_dict[(record.employee_id.id, record.date)] = record

        pl_dates, hp_l_dates, sp_l_dates = _leave_overlay_keys(
            employee_ids, month_dates, work_records_dict
        )

        attendance_request_cell_keys = set()
        for emp_id, att_date, clock_in_date in Attendance.objects.filter(
            is_validate_request=True,
            employee_id__is_active=True,
            employee_id__in=employee_ids,
        ).filter(
            Q(attendance_date__in=month_dates)
            | Q(attendance_clock_in_date__in=month_dates)
        ).values_list("employee_id", "attendance_date", "attendance_clock_in_date"):
            if att_date and att_date in month_dates_set:
                attendance_request_cell_keys.add(f"{emp_id}_{att_date.isoformat()}")
            if clock_in_date and clock_in_date in month_dates_set:
                attendance_request_cell_keys.add(
                    f"{emp_id}_{clock_in_date.isoformat()}"
                )

        leave_request_cell_keys = set()
        if apps.is_installed("leave"):
            from leave.models import LeaveRequest

            for emp_id, start_date, end_date in LeaveRequest.objects.filter(
                status="requested",
                employee_id__is_active=True,
                employee_id__in=employee_ids,
            ).filter(
                Q(start_date__in=month_dates) | Q(end_date__in=month_dates)
            ).values_list("employee_id", "start_date", "end_date"):
                if start_date and end_date:
                    current = start_date
                    while current <= end_date:
                        if current in month_dates_set:
                            leave_request_cell_keys.add(
                                f"{emp_id}_{current.isoformat()}"
                            )
                        current += timedelta(days=1)
                elif start_date and start_date in month_dates_set:
                    leave_request_cell_keys.add(f"{emp_id}_{start_date.isoformat()}")

        for employee in employees:
            effective_from = effective_from_map.get(employee.id)
            for day in month_dates:
                if day > today or day < range_start or day > range_end:
                    continue
                if day in leave_dates:
                    continue
                record_type = record_lookup.get((employee, day), "DFT")
                code = _display_code(
                    employee,
                    day,
                    record_type,
                    leave_dates=leave_dates,
                    holiday_dates=holiday_dates,
                    pl_dates=pl_dates,
                    hp_l_dates=hp_l_dates,
                    sp_l_dates=sp_l_dates,
                    attendance_request_cell_keys=attendance_request_cell_keys,
                    leave_request_cell_keys=leave_request_cell_keys,
                    effective_from=effective_from,
                )
                if code != "A":
                    continue
                rows.append(
                    {
                        "Employee ID": employee.badge_id or "",
                        "Employee Name": employee.get_full_name(),
                        "Department": employee.get_department() or "",
                        "Date": day.strftime("%d-%m-%Y"),
                        "Month": day.strftime("%B"),
                        "Status": "A",
                        "_sort_date": day,
                    }
                )

    rows.sort(key=lambda item: (item["_sort_date"], item["Employee Name"]))
    for row in rows:
        row.pop("_sort_date", None)
    return rows


class Command(BaseCommand):
    help = (
        "Export Absent (A) records for active employees (Jan–Jun by default) to Excel."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=date.today().year,
            help="Calendar year (default: current year)",
        )
        parser.add_argument(
            "--start-month",
            type=int,
            default=1,
            help="Start month 1–12 (default: 1 = January)",
        )
        parser.add_argument(
            "--end-month",
            type=int,
            default=6,
            help="End month 1–12 (default: 6 = June)",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="",
            help="Output .xlsx path (default: absent_records_Jan-Jun_<year>.xlsx in cwd)",
        )

    def handle(self, *args, **options):
        year = options["year"]
        start_month = options["start_month"]
        end_month = options["end_month"]
        output_path = options["output"]

        if start_month < 1 or end_month > 12 or start_month > end_month:
            self.stdout.write(self.style.ERROR("Invalid month range."))
            return

        if not output_path:
            output_path = os.path.abspath(
                f"absent_records_Jan-Jun_{year}.xlsx"
            )
        else:
            output_path = os.path.abspath(output_path)

        self.stdout.write(
            f"Collecting Absent (A) records for active employees: "
            f"{date(year, start_month, 1):%B} – {date(year, end_month, 1):%B} {year}..."
        )
        rows = collect_absent_rows(year, start_month, end_month)

        columns = [
            "Employee ID",
            "Employee Name",
            "Department",
            "Date",
            "Month",
            "Status",
        ]
        df = pd.DataFrame(rows, columns=columns)

        with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Absent Records")
            worksheet = writer.sheets["Absent Records"]
            header_format = writer.book.add_format(
                {"bold": True, "bg_color": "#2196F3", "font_color": "#ffffff"}
            )
            for col_idx, col in enumerate(columns):
                worksheet.write(0, col_idx, col, header_format)
                max_len = max(
                    df[col].astype(str).map(len).max() if len(df) else 0,
                    len(col),
                )
                worksheet.set_column(col_idx, col_idx, min(max_len + 2, 40))

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(rows)} absent record(s) to:\n{output_path}"
            )
        )
