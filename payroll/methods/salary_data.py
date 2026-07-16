"""
Salary data calculation based on Attendance Calendar.

Formula: calculated_salary = (days_worked / working_days) * monthly_salary
- days_worked: from WorkRecords (only on working days):
  - P/FDP (Present) = 1 day
  - P/L (Present + approved full-day leave) = 1 day
  - HP/HDP (Half day) = 0.5 day, except HP/L (HP + approved half-day leave) = 1 day
  - L (Paid Leave) / is_leave_record = 1 day
  - WO (Week Off) and PH (Public Holiday) days are excluded: even if employee has P/HP/L/HP/P on those days, they do not count in days_worked.
- working_days: month days excluding PH (Public Holiday) and WO (Week Off)
- monthly_salary: basic_salary * 2 from active contract
- final_salary: calculated_salary - PT (Professional Tax, default ₹200)
- PT applied only when monthly_salary > PT_MONTHLY_THRESHOLD (₹20,000); 20000 = no PT, 20001+ = PT.
"""

PT_DEDUCTION_DEFAULT = 200
PT_MONTHLY_THRESHOLD = 20000  # PT applied only if monthly_salary > this (20000 no PT, 20001+ PT)

import calendar
from datetime import date, timedelta
from django.apps import apps
from django.db.models import Q

from employee.models import Employee
from payroll.models.models import Contract, MonthlySalaryData


def get_working_days_for_month(month: int, year: int) -> int:
    """
    Number of working days in the month (exclude PH and WO).
    Uses same source as Attendance Calendar: total days - (PH + WO).
    PH = public holidays, WO = week off (from Company Leaves / attendance config).
    monthly_leave_dates(month, year) returns all dates that are PH or WO in that month.
    """
    if not apps.is_installed("attendance"):
        # Fallback: total days minus weekends
        _, last = calendar.monthrange(year, month)
        return sum(
            1
            for d in range(1, last + 1)
            if date(year, month, d).weekday() < 5
        )
    from attendance.methods.utils import monthly_leave_days

    _, last = calendar.monthrange(year, month)
    total_days_in_month = last
    # Same as Attendance Calendar: off_dates = PH + WO (company week off)
    off_dates_set = set(monthly_leave_days(month, year))
    month_dates = [date(year, month, d) for d in range(1, last + 1)]
    off_count = sum(1 for d in month_dates if d in off_dates_set)
    working_days = total_days_in_month - off_count
    return working_days


def _employee_dates_with_half_leave(employee_id, start_d, end_d):
    """
    Set of dates (as date objects) on which this employee has approved half-day leave.
    Used so HP + half-day leave (HP/L) counts as 1 full day in salary.
    """
    if not apps.is_installed("leave"):
        return set()
    from leave.models import LeaveRequest, leave_requested_dates

    leaves = LeaveRequest.objects.filter(
        status="approved",
        employee_id_id=employee_id,
        start_date__lte=end_d,
        start_date__gte=start_d,
    ).filter(Q(end_date__gte=start_d) | Q(end_date__isnull=True)).values(
        "start_date", "end_date", "requested_days",
        "start_date_breakdown", "end_date_breakdown"
    )
    month_dates_set = set(leave_requested_dates(start_d, end_d))
    half_leave_dates = set()
    for lr in leaves:
        end = lr["end_date"] or lr["start_date"]
        for d in leave_requested_dates(lr["start_date"], end):
            if d not in month_dates_set:
                continue
            is_half = (
                (lr["requested_days"] == 0.5 and lr["start_date"] == end)
                or (d == lr["start_date"] and lr["start_date_breakdown"] in ("first_half", "second_half"))
                or (d == end and lr["end_date_breakdown"] in ("first_half", "second_half"))
            )
            if is_half:
                half_leave_dates.add(d)
    return half_leave_dates


def _employee_dates_with_full_leave(employee_id, start_d, end_d):
    """
    Set of dates (as date objects) on which this employee has approved full-day leave.
    Used so P/L (FDP + approved full-day leave) and similar present+leave days count as 1 full day.
    """
    if not apps.is_installed("leave"):
        return set()
    from leave.models import LeaveRequest, leave_requested_dates

    leaves = LeaveRequest.objects.filter(
        status="approved",
        employee_id_id=employee_id,
        start_date__lte=end_d,
        start_date__gte=start_d,
    ).filter(Q(end_date__gte=start_d) | Q(end_date__isnull=True)).values(
        "start_date", "end_date", "requested_days",
        "start_date_breakdown", "end_date_breakdown"
    )
    month_dates_set = set(leave_requested_dates(start_d, end_d))
    full_leave_dates = set()
    for lr in leaves:
        end = lr["end_date"] or lr["start_date"]
        for d in leave_requested_dates(lr["start_date"], end):
            if d not in month_dates_set:
                continue
            is_half = (
                (lr["requested_days"] == 0.5 and lr["start_date"] == end)
                or (d == lr["start_date"] and lr["start_date_breakdown"] in ("first_half", "second_half"))
                or (d == end and lr["end_date_breakdown"] in ("first_half", "second_half"))
            )
            if not is_half:
                full_leave_dates.add(d)
    return full_leave_dates


def get_days_worked_for_employee(employee_id, month: int, year: int) -> float:
    """
    Count days worked from WorkRecords:
    - FDP (Present) = 1 day
    - P/L (Present + approved full-day leave) = 1 day
    - HDP/HP (Half day present) = 0.5 day, or 1 day if HP/L (HP + approved half-day leave)
    - L (Paid Leave) / is_leave_record = 1 day

    Do NOT count days that are WO (Week Off) or PH (Public Holiday). Even if the
    employee punched in on a WO/PH day (P, HP, L, HP/P), that day is excluded from
    days_worked so salary is based only on working days.
    """
    if not apps.is_installed("attendance"):
        return 0
    from attendance.models import WorkRecords
    from attendance.methods.utils import monthly_leave_days

    _, last = calendar.monthrange(year, month)
    start_d = date(year, month, 1)
    end_d = date(year, month, last)

    # Days that are WO or PH: exclude these from days_worked
    wo_ph_dates = set(monthly_leave_days(month, year))

    # Use entire() so archived/inactive employees' work records are included
    # (company filter would otherwise exclude them when work_info is missing/different)
    records = WorkRecords.objects.entire().filter(
        employee_id_id=employee_id,
        date__gte=start_d,
        date__lte=end_d,
    )

    half_leave_dates = _employee_dates_with_half_leave(employee_id, start_d, end_d)
    full_leave_dates = _employee_dates_with_full_leave(employee_id, start_d, end_d)

    days_worked = 0.0
    for rec in records:
        if rec.date in wo_ph_dates:
            # Do not count WO/PH days in days_worked even if they have P, HP, L, HP/P
            continue
        if rec.work_record_type == "FDP":
            # FDP includes P/L and regular present days; both count as a full day.
            days_worked += 1
        elif rec.work_record_type in ("HDP", "HP"):
            # HP/L (HP + approved half-day leave) and HP + approved full-day leave both count as 1 full day.
            if rec.date in half_leave_dates or rec.date in full_leave_dates:
                days_worked += 1
            else:
                days_worked += 0.5
        elif rec.work_record_type == "SP" and (rec.date in half_leave_dates or rec.date in full_leave_dates):
            # SP/L (Short Presence with Leave) - Full Day Pay
            days_worked += 1
        elif rec.work_record_type == "SP":
            # SP (Short Presence) is LOP - no salary for that day
            days_worked += 0
        elif rec.is_leave_record or rec.work_record_type == "L":
            days_worked += 1
    return days_worked


def get_contract_for_period(employee, month: int, year: int):
    """
    Return the contract that was in effect for the given month/year.
    Uses contract dates (start/end) so inactive employees or expired/terminated
    contracts still get the correct wage for that period.
    Uses entire() to bypass company filter so inactive employees (who may have
    no/different work info) still get their contract for salary calculation.
    """
    _, last_day = calendar.monthrange(year, month)
    period_start = date(year, month, 1)
    period_end = date(year, month, last_day)
    contract = (
        Contract.objects.entire()
        .filter(
            employee_id=employee,
            contract_start_date__lte=period_end,
        )
        .filter(
            Q(contract_end_date__isnull=True) | Q(contract_end_date__gte=period_start)
        )
        .order_by("-contract_start_date")
        .first()
    )
    return contract


def get_monthly_salary_for_employee(employee, month: int = None, year: int = None) -> float:
    """Monthly salary = basic_salary * 2 from contract (active or the one in effect for month/year)."""
    if month is not None and year is not None:
        contract = get_contract_for_period(employee, month, year)
    else:
        contract = (
            Contract.objects.filter(
                employee_id=employee,
                contract_status="active",
            )
            .order_by("-contract_start_date")
            .first()
        )
    if not contract or contract.wage is None:
        return 0.0
    return float(contract.wage) * 2


def get_basic_salary_for_employee(employee, month: int = None, year: int = None) -> float:
    """Basic salary (wage) from contract (active or the one in effect for month/year)."""
    if month is not None and year is not None:
        contract = get_contract_for_period(employee, month, year)
    else:
        contract = (
            Contract.objects.filter(
                employee_id=employee,
                contract_status="active",
            )
            .order_by("-contract_start_date")
            .first()
        )
    if not contract or contract.wage is None:
        return 0.0
    return float(contract.wage)


def get_lop_amount(monthly_salary, working_days, days_worked) -> float:
    """LOP rupees = monthly salary minus prorated earned amount (same as salary data)."""
    if not working_days or working_days <= 0:
        return 0.0
    calculated = round((float(days_worked) / float(working_days)) * float(monthly_salary), 2)
    return round(max(0.0, float(monthly_salary) - calculated), 2)


def apply_professional_tax_amount(deduction_lists, monthly_salary) -> float:
    """
    Set Professional Tax line items to ₹200 or ₹0 (monthly salary > ₹20,000 threshold).
    Returns the PT amount applied.
    """
    pt_amount = (
        PT_DEDUCTION_DEFAULT if (monthly_salary or 0) > PT_MONTHLY_THRESHOLD else 0
    )
    pt_titles = ("professional tax", "pt", "professional tax (pt)")
    for ded_list in deduction_lists:
        if not ded_list:
            continue
        for item in ded_list:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip().lower()
            if title in pt_titles or "professional tax" in title:
                item["amount"] = pt_amount
    return pt_amount


def compute_salary_data_for_employee(employee, month: int, year: int) -> dict:
    """
    Compute salary data for one employee for the given month.
    Uses the contract that was in effect for that month (so inactive employees
    with contract/attendance for that period get correct salary).
    Returns dict with days_worked, working_days, basic_salary, monthly_salary, calculated_salary.
    """
    working_days = get_working_days_for_month(month, year)
    days_worked = get_days_worked_for_employee(employee.id, month, year)
    basic_salary = get_basic_salary_for_employee(employee, month=month, year=year)
    monthly_salary = get_monthly_salary_for_employee(employee, month=month, year=year)

    if working_days <= 0:
        calculated_salary = 0.0
    else:
        calculated_salary = round(
            (days_worked / working_days) * monthly_salary, 2
        )

    # PT ₹200 only when monthly_salary > 20000 (20000 = no PT, 20001+ = PT)
    pt_deduction = (
        PT_DEDUCTION_DEFAULT if (monthly_salary or 0) > PT_MONTHLY_THRESHOLD else 0
    )
    final_salary = round(max(0, calculated_salary - pt_deduction), 2)

    return {
        "employee": employee,
        "year": year,
        "month": month,
        "days_worked": days_worked,
        "working_days": working_days,
        "basic_salary": basic_salary,
        "monthly_salary": monthly_salary,
        "calculated_salary": calculated_salary,
        "pt_deduction": pt_deduction,
        "final_salary": final_salary,
    }


def get_ph_wo_paid_leave_counts(month: int, year: int, employee_id=None):
    """
    Return PH count, WO count, and paid leave (L) count for the month.
    If employee_id is given, paid_leave is for that employee; otherwise 0.
    """
    ph_count = 0
    wo_count = 0
    paid_leave_count = 0
    if not apps.is_installed("attendance"):
        return {"ph_count": 0, "wo_count": 0, "paid_leave_count": 0}

    from attendance.methods.utils import monthly_holiday_dates, monthly_leave_days

    _, last = calendar.monthrange(year, month)
    month_dates = [date(year, month, d) for d in range(1, last + 1)]
    holiday_dates = set(monthly_holiday_dates(month, year))
    off_dates = set(monthly_leave_days(month, year))

    ph_count = sum(1 for d in month_dates if d in holiday_dates)
    off_in_month = [d for d in month_dates if d in off_dates]
    wo_count = len(off_in_month) - ph_count  # off = PH + WO

    if employee_id is not None:
        from attendance.models import WorkRecords

        start_d = date(year, month, 1)
        end_d = date(year, month, last)
        leave_records = WorkRecords.objects.filter(
            employee_id_id=employee_id,
            date__gte=start_d,
            date__lte=end_d,
        ).filter(Q(is_leave_record=True) | Q(work_record_type="L"))
        paid_leave_count = leave_records.count()

    return {
        "ph_count": ph_count,
        "wo_count": wo_count,
        "paid_leave_count": paid_leave_count,
    }
