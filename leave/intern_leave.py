"""
Intern leave logic: Employee Type = Intern.

- Intern Sick Leave (ISL): 1 day per 3-month block, paid. Separate leave type, interns only.
- No CL, EL, or full-time SL for interns.
- When converted to full-time (joining date set), probation starts, then normal EL/CL/SL.
"""

from datetime import date

from dateutil.relativedelta import relativedelta
from django.db.models import Sum

from employee.models import EmployeeWorkInformation
from leave.models import LeaveType, AvailableLeave, LeaveRequest

ISL_NAME = "Intern Sick Leave (ISL)"


def is_intern(employee):
    """True if employee's Employee Type is Intern (case-insensitive)."""
    work_info = (
        EmployeeWorkInformation.objects.filter(employee_id=employee)
        .select_related("employee_type_id")
        .first()
    )
    if not work_info or not work_info.employee_type_id:
        return False
    return (work_info.employee_type_id.employee_type or "").strip().lower() == "intern"


def _intern_block_dates(joining_date, today):
    """
    Current 3-month block (0-indexed) from joining_date and (block_start, block_end).
    Block 0: months 0–2, block 1: months 3–5, etc.
    """
    months = (today.year - joining_date.year) * 12 + (today.month - joining_date.month)
    if today.day < joining_date.day:
        months -= 1
    months = max(0, months)
    block = months // 3
    block_start = joining_date + relativedelta(months=3 * block)
    block_end = block_start + relativedelta(months=3) - relativedelta(days=1)
    return block_start, block_end


def intern_isl_balance(employee):
    """
    Intern ISL: 1 day per 3-month block. Returns (balance, block_start, block_end).
    Balance = 1 - approved ISL days in current block.
    Block start: date_joining if set; else AvailableLeave.assigned_date for ISL (fallback for interns without joining date).
    """
    try:
        isl_type = LeaveType.objects.get(name=ISL_NAME)
    except LeaveType.DoesNotExist:
        return 0.0, None, None

    today = date.today()
    block_start_date = None

    work_info = EmployeeWorkInformation.objects.filter(employee_id=employee).first()
    if work_info and work_info.date_joining:
        block_start_date = work_info.date_joining
    else:
        av = AvailableLeave.objects.filter(
            employee_id=employee, leave_type_id=isl_type
        ).first()
        if av and av.assigned_date:
            block_start_date = av.assigned_date

    if not block_start_date:
        return 0.0, None, None

    block_start, block_end = _intern_block_dates(block_start_date, today)

    taken = (
        LeaveRequest.objects.filter(
            employee_id=employee,
            leave_type_id=isl_type,
            status="approved",
            start_date__lte=block_end,
            end_date__gte=block_start,
        ).aggregate(total=Sum("requested_days"))
    ).get("total") or 0

    balance = max(0.0, 1.0 - float(taken))
    return balance, block_start, block_end


def intern_sl_balance(employee):
    """Alias for intern_isl_balance (backward compatibility)."""
    return intern_isl_balance(employee)


def ensure_intern_sl_available_leave(employee, leave_type, balance, today):
    """Create or update AvailableLeave for intern ISL (1 per 3-month block)."""
    av, _ = AvailableLeave.objects.get_or_create(
        employee_id=employee,
        leave_type_id=leave_type,
        defaults={"available_days": 0, "assigned_date": today},
    )
    av.available_days = balance
    av.carryforward_days = 0
    av.assigned_date = today
    return av



def prepare_user_leaves_for_display(employee, available_leaves_qs):
    """
    For My Leave Requests: interns only see ISL (1 per 3 months).
    Filters to ISL-only and sets display values from intern_isl_balance.
    If intern has no ISL record, adds a synthetic ISL card.
    """
    out = list(available_leaves_qs)
    if not is_intern(employee):
        return out
    try:
        isl_type = LeaveType.objects.get(name=ISL_NAME)
    except LeaveType.DoesNotExist:
        return []
    filtered = [av for av in out if av.leave_type_id_id == isl_type.id]
    balance, _, _ = intern_isl_balance(employee)
    for av in filtered:
        av.available_days = balance
        av.carryforward_days = 0
        av.total_leave_days = round(max(balance + 0, 0), 3)
    if not filtered:
        synthetic = AvailableLeave(
            employee_id=employee,
            leave_type_id=isl_type,
            available_days=balance,
            carryforward_days=0,
            total_leave_days=round(max(balance + 0, 0), 3),
        )
        filtered = [synthetic]
    return filtered
