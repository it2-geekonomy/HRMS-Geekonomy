import calendar
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.db.models import Q, Sum

from employee.models import Employee
from horilla.methods import get_horilla_model_class

CASUAL_LEAVE_NAMES = (
    "Casual Leave",
    "Casual Leave (CL)",
    "Casual Leave - Paid",
    "Casual Leave – Paid",
)

EARNED_LEAVE_NAMES = (
    "Earned Leave",
    "Earned Leave (EL)",
    "Earned Leave - Paid",
    "Earned Leave – Paid",
)

PROBATION_LEAVE_NAMES = (
    "Probation Sick Leave",
    "Probation Sick Leave (PSL)",
    "Probation Leave",
    "Probation Leave (PL)",
)
PROBATION_CASUAL_LEAVE_NAMES = (
    "Probation Casual Leave",
    "Probation Casual Leave (PCL)",
)
PROBATION_PERIOD_LEAVE_CAP = 2.0
INTERNS_LEAVE_NAMES = ("Interns Leave",)

# Temporary exception: these badge IDs may approve their own leave requests.
# Keep in sync with attendance SELF_APPROVE_ATTENDANCE_BADGES (Sanketh M).
SELF_APPROVE_LEAVE_BADGES = frozenset({"GEEKY0007"})


def can_user_approve_leave_request(user, leave_request):
    """
    Return False when the user is the employee who submitted the leave request,
    unless their badge is in SELF_APPROVE_LEAVE_BADGES (temporary exception).
    """
    if not user or not leave_request:
        return False
    try:
        requester = leave_request.employee_id
        requester_user = getattr(requester, "employee_user_id", None)
        if requester_user and requester_user == user:
            badge = (getattr(requester, "badge_id", None) or "").strip().upper()
            return badge in SELF_APPROVE_LEAVE_BADGES
    except Exception:
        return False
    return True


def get_probation_leave_type():
    """Probation Sick Leave (deducted from SL on confirm). Legacy names still match."""
    LeaveType = apps.get_model("leave", "LeaveType")
    for name in PROBATION_LEAVE_NAMES:
        leave_type = LeaveType.objects.filter(name=name).first()
        if leave_type:
            return leave_type
    return (
        LeaveType.objects.filter(name__icontains="probation")
        .exclude(name__icontains="casual")
        .filter(total_days=1)
        .first()
    )


def get_probation_casual_leave_type():
    LeaveType = apps.get_model("leave", "LeaveType")
    return LeaveType.objects.filter(name__in=PROBATION_CASUAL_LEAVE_NAMES).first()


def get_recent_approved_probation_leaves(employee):
    """Approved Probation Leave requests for an employee (newest first)."""
    if not employee:
        return []
    LeaveRequest = apps.get_model("leave", "LeaveRequest")
    pl_type = get_probation_leave_type()
    if not pl_type:
        return []
    return list(
        LeaveRequest.objects.filter(
            employee_id=employee,
            leave_type_id=pl_type,
            status="approved",
        ).order_by("-start_date")
    )


def _approved_leave_taken(employee, leave_type, as_of_date=None):
    """Sum of approved requested_days for leave_type up to as_of_date."""
    if not employee or not leave_type:
        return 0.0
    as_of = as_of_date or date.today()
    LeaveRequest = apps.get_model("leave", "LeaveRequest")
    total = (
        LeaveRequest.objects.filter(
            employee_id=employee,
            leave_type_id=leave_type,
            status="approved",
            end_date__lte=as_of,
        ).aggregate(total=Sum("requested_days"))["total"]
        or 0.0
    )
    return float(total)


def get_probation_leave_taken(employee=None, as_of_date=None):
    """
    Calculate total probation leave taken by an employee up to a specific date.
    Deducted from Sick Leave when probation is confirmed.
    """
    if not employee:
        return 0.0
    return _approved_leave_taken(employee, get_probation_leave_type(), as_of_date)


def get_probation_casual_leave_taken(employee=None, as_of_date=None):
    """
    Calculate total Probation Casual Leave taken up to a date.
    Deducted from Casual Leave when probation is confirmed.
    """
    if not employee:
        return 0.0
    return _approved_leave_taken(
        employee, get_probation_casual_leave_type(), as_of_date
    )

def _join_date(employee):
    """Get date_joining from employee's work info robustly. Returns None if unavailable."""
    if not employee:
        return None
    
    try:
        # First, try a robust direct DB query to avoid any select_related or context caching issues
        from employee.models import EmployeeWorkInformation
        # employee can be either Employee instance or ID
        emp_id = employee.id if hasattr(employee, 'id') else employee
        wi = EmployeeWorkInformation.objects.filter(employee_id=emp_id).first()
        if wi and wi.date_joining:
            return wi.date_joining
    except Exception:
        pass

    try:
        rel = getattr(employee, "employee_work_info", None)
        if rel is None:
            return None
        wi = rel.first() if hasattr(rel, "first") else rel
        return getattr(wi, "date_joining", None) if wi else None
    except Exception:
        return None


def next_yearly_reset_date(as_of_date=None):
    """Next 1 January when CL/SL yearly balances reset (all employees)."""
    as_of = as_of_date or date.today()
    jan1 = date(as_of.year, 1, 1)
    if as_of < jan1:
        return jan1
    return date(as_of.year + 1, 1, 1)


def is_earned_leave_type(leave_type):
    if not leave_type:
        return False
    lt_name = (leave_type.name or "").strip()
    return lt_name in EARNED_LEAVE_NAMES or lt_name.startswith("Earned Leave")


def is_casual_leave_type(leave_type):
    """Regular Casual Leave only — not Probation Casual Leave."""
    if not leave_type:
        return False
    lt_name = (leave_type.name or "").strip()
    lt_lower = lt_name.lower()
    if "probation" in lt_lower:
        return False
    if lt_name in CASUAL_LEAVE_NAMES:
        return True
    return lt_lower.startswith("casual leave")


def is_probation_sick_leave_type(leave_type):
    """Probation Sick Leave (1/month during probation; deducted from SL on confirm)."""
    if not leave_type:
        return False
    lt_name = (leave_type.name or "").strip()
    if lt_name in PROBATION_LEAVE_NAMES:
        return True
    lt_lower = lt_name.lower()
    return (
        "probation" in lt_lower
        and "casual" not in lt_lower
        and round(float(leave_type.total_days or 0), 2) == 1.0
    )


def is_probation_casual_leave_type(leave_type):
    """Probation Casual Leave (1/month during probation; deducted from CL on confirm)."""
    if not leave_type:
        return False
    lt_name = (leave_type.name or "").strip()
    if lt_name in PROBATION_CASUAL_LEAVE_NAMES:
        return True
    lt_lower = lt_name.lower()
    return "probation" in lt_lower and "casual" in lt_lower


def is_probation_or_interns_monthly(leave_type):
    """Probation / Probation Casual / Interns: 1 day per month on the 1st, no yearly wipe."""
    if not leave_type or getattr(leave_type, "reset_based", None) != "monthly":
        return False
    lt_name = (leave_type.name or "").strip()
    if lt_name in PROBATION_LEAVE_NAMES or lt_name in PROBATION_CASUAL_LEAVE_NAMES:
        return True
    if lt_name in INTERNS_LEAVE_NAMES:
        return True
    lt_lower = lt_name.lower()
    if "probation" in lt_lower and round(float(leave_type.total_days or 0), 2) == 1.0:
        return True
    return "interns leave" in lt_lower and round(float(leave_type.total_days or 0), 2) == 1.0


def next_monthly_accrual_date(leave_type, as_of_date=None):
    """Next calendar date when monthly leave is credited (typically 1st of month)."""
    as_of = as_of_date or date.today()
    reset_day = leave_type.reset_day if leave_type else "1"
    if reset_day == "last day":
        month_end = calendar.monthrange(as_of.year, as_of.month)[1]
        candidate = date(as_of.year, as_of.month, month_end)
        if as_of < candidate:
            return candidate
        next_month = as_of + relativedelta(months=1)
        return date(next_month.year, next_month.month, calendar.monthrange(next_month.year, next_month.month)[1])
    day = int(reset_day or 1)
    candidate = date(as_of.year, as_of.month, day)
    if as_of < candidate:
        return candidate
    next_month = as_of + relativedelta(months=1)
    return date(next_month.year, next_month.month, day)


def is_sick_leave_type(leave_type):
    """Full-time Sick Leave (7/year), not Intern Sick Leave."""
    if not leave_type:
        return False
    lt_name = (leave_type.name or "").strip()
    if lt_name in ("Sick Leave", "Sick Leave (SL)", "Sick Leave - Paid", "Sick Leave – Paid"):
        return True
    lt_lower = lt_name.lower()
    return lt_lower.startswith("sick leave") and "intern" not in lt_lower


def get_yearly_entitlement(leave_type):
    """
    Yearly policy maximum for Leave Configuration 'Total' column.
    e.g. CL = 12, EL = 15 (1.25 x 12), SL = 7.
    """
    if not leave_type:
        return 0.0
    per_period = float(leave_type.total_days or 0)
    reset_based = getattr(leave_type, "reset_based", None) or ""
    if reset_based == "monthly" and per_period > 0:
        yearly = round(per_period * 12, 2)
        cap = leave_type.carryforward_max
        if cap is not None and not is_earned_leave_type(leave_type):
            return min(yearly, float(cap))
        return yearly
    return per_period


def get_sick_leave_balance_stats(available_leave, as_of_date=None):
    """
    Sick Leave: 7 days/year minus probation leave taken, minus sick leave used this year.
    Returns yearly_total, probation_leave_taken, sick_leave_taken, available_days.
    """
    as_of = as_of_date or date.today()
    leave_type = available_leave.leave_type_id
    yearly_total = float(leave_type.total_days or 7)
    probation_taken = get_probation_leave_taken(available_leave.employee_id, as_of)
    LeaveRequest = apps.get_model("leave", "LeaveRequest")
    sick_taken = (
        LeaveRequest.objects.filter(
            employee_id=available_leave.employee_id,
            leave_type_id=leave_type,
            status="approved",
            start_date__year=as_of.year,
        ).aggregate(total=Sum("requested_days"))["total"]
        or 0.0
    )
    sick_taken = float(sick_taken)
    available = max(0.0, yearly_total - probation_taken - sick_taken)
    accrued = round(available + sick_taken, 2)
    return {
        "yearly_total": yearly_total,
        "accrued_days": accrued,
        "probation_leave_taken": round(probation_taken, 2),
        "sick_leave_taken": round(sick_taken, 2),
        "available_days": round(available, 2),
    }


def get_casual_leave_balance_stats(available_leave, as_of_date=None):
    """
    Casual Leave: months accrued (from join/Jan 2026) minus Probation Casual Leave taken
    minus Casual Leave taken, capped at 12.
    """
    as_of = as_of_date or date.today()
    leave_type = available_leave.leave_type_id
    CL_EPOCH_DATE = date(2026, 1, 1)
    join_date = _join_date(available_leave.employee_id)
    raw_start = getattr(available_leave, "assigned_date", None)
    if join_date:
        accrual_start = max(CL_EPOCH_DATE, join_date.replace(day=1))
    elif raw_start:
        accrual_start = max(CL_EPOCH_DATE, raw_start.replace(day=1))
    else:
        accrual_start = CL_EPOCH_DATE
    months = max(
        0,
        (as_of.year - accrual_start.year) * 12
        + (as_of.month - accrual_start.month)
        + 1,
    )
    total_accrued = float(months)
    pcl_taken = get_probation_casual_leave_taken(available_leave.employee_id, as_of)
    LeaveRequest = apps.get_model("leave", "LeaveRequest")
    cl_taken = float(
        LeaveRequest.objects.filter(
            employee_id=available_leave.employee_id,
            leave_type_id=leave_type,
            status="approved",
        ).aggregate(total=Sum("requested_days"))["total"]
        or 0.0
    )
    cl_cap = (
        leave_type.carryforward_max
        if leave_type.carryforward_max is not None
        else 12
    )
    available = min(max(0.0, total_accrued - pcl_taken - cl_taken), float(cl_cap))
    return {
        "yearly_total": float(cl_cap),
        "accrued_days": round(total_accrued, 2),
        "probation_casual_leave_taken": round(pcl_taken, 2),
        "casual_leave_taken": round(cl_taken, 2),
        "available_days": round(available, 2),
        "leave_taken": round(pcl_taken + cl_taken, 2),
    }


def _probation_period_months_accrued(available_leave, as_of_date):
    """Months credited for PSL / PCL / Interns Leave (1 day per month)."""
    as_of = as_of_date or date.today()
    as_of_first = as_of.replace(day=1)
    join_date = _join_date(available_leave.employee_id)
    raw_start = getattr(available_leave, "assigned_date", None)
    candidates = [as_of_first]
    if join_date:
        candidates.append(join_date.replace(day=1))
    if raw_start:
        candidates.append(raw_start.replace(day=1))
    accrual_start = min(candidates)
    return max(
        0,
        (as_of.year - accrual_start.year) * 12
        + (as_of.month - accrual_start.month)
        + 1,
    )


def get_probation_period_leave_balance_stats(
    available_leave, as_of_date=None, exclude_leave_request_id=None
):
    """
    Probation Sick Leave / Probation Casual Leave / Interns Leave:
    1 day per month, max 2 in bucket (current + previous month), no carry forward.
    available_days = usable right now (bucket balance capped by 1 per calendar month).
    """
    as_of = as_of_date or date.today()
    leave_type = available_leave.leave_type_id
    LeaveRequest = apps.get_model("leave", "LeaveRequest")
    leave_taken = float(
        LeaveRequest.objects.filter(
            employee_id=available_leave.employee_id,
            leave_type_id=leave_type,
            status="approved",
        ).aggregate(total=Sum("requested_days"))["total"]
        or 0.0
    )
    months = _probation_period_months_accrued(available_leave, as_of)
    total_accrued = float(months)
    bucket_balance = min(
        max(0.0, total_accrued - leave_taken), PROBATION_PERIOD_LEAVE_CAP
    )
    days_in_month = probation_leave_days_in_month(
        available_leave.employee_id,
        leave_type,
        as_of.year,
        as_of.month,
        exclude_leave_request_id=exclude_leave_request_id,
    )
    usable_in_month = max(0.0, 1.0 - float(days_in_month))
    available = round(min(bucket_balance, usable_in_month), 3)
    accrued = round(available + leave_taken, 2)
    return {
        "yearly_total": PROBATION_PERIOD_LEAVE_CAP,
        "accrued_days": accrued,
        "available_days": available,
        "bucket_days": round(bucket_balance, 2),
        "leave_taken": round(leave_taken, 2),
        "months_accrued": months,
    }


def leave_type_uses_yearly_balance_reset(leave_type):
    """True for Casual Leave and Sick Leave (cleared every calendar year on 1 Jan)."""
    if not leave_type:
        return False
    lt_name = (leave_type.name or "").strip()
    reset_based = getattr(leave_type, "reset_based", None) or ""
    if lt_name in CASUAL_LEAVE_NAMES or lt_name.startswith("Casual Leave"):
        return True
    if "sick" in lt_name.lower() and reset_based == "yearly":
        return True
    if reset_based == "yearly" and getattr(leave_type, "reset", False):
        return True
    return False


def get_leave_configuration_date_display(leave_type, available_leave, as_of_date=None):
    """
    Date shown in Leave Configuration per leave type:
    - CL/SL: next 1 Jan (yearly balance clear)
    - EL: balance expiry (3 years from assignment)
    - Probation/Interns: next monthly accrual (adds 1 day, does not wipe balance)
    - Other: stored reset_date if any
    Returns (date_or_none, column_label).
    """
    as_of = as_of_date or date.today()
    if leave_type_uses_yearly_balance_reset(leave_type):
        return next_yearly_reset_date(as_of), "Year Reset"
    if is_probation_or_interns_monthly(leave_type):
        return next_monthly_accrual_date(leave_type, as_of), "Next Accrual"
    if is_earned_leave_type(leave_type):
        if available_leave and available_leave.expired_date:
            return available_leave.expired_date, "Expires On"
        assigned = getattr(available_leave, "assigned_date", None) or as_of
        lt = leave_type
        if (
            lt
            and lt.carryforward_type == "carryforward expire"
            and lt.carryforward_expire_in
            and lt.carryforward_expire_period
        ):
            n = lt.carryforward_expire_in
            period = lt.carryforward_expire_period
            if period == "day":
                return assigned + relativedelta(days=n), "Expires On"
            if period == "month":
                return assigned + relativedelta(months=n), "Expires On"
            return assigned + relativedelta(years=n), "Expires On"
        return None, "Expires On"
    reset_date = getattr(available_leave, "reset_date", None)
    return reset_date, "Reset Date"


def get_init_days_and_reset_for_assign(leave_type, assigned_date, employee=None):
    """
    Pro-rate first-year leave when assigning mid-year (e.g. after probation).

    - Casual Leave (1/month, cap 12): init_days = months from assign to Dec 31, capped 12;
      reset_date = Jan 1 next year so scheduler doesn't add in between.
    - Sick Leave (7/year): init_days = 7 * (months from assign to Dec 31) / 12.
    - Earned Leave (1.25/month):
      - Assigned on 1st: probation_credit = 1.25 × (months from join to assign), plus 1.25 for
        this month; reset_date = 1st of next month.
      - Assigned after 1st (e.g. Feb 2): give 1.25 for current month (one accrual for the
        month); reset_date = 1st of next month. Next 1.25 on that 1st.
    - Other monthly: (0, None). Other: (total_days, None).

    Returns (init_days, reset_date_override or None).
    """
    if not leave_type:
        return (0, None)
    assigned_date = assigned_date or date.today()
    months_remaining = (12 - assigned_date.month) + 1
    next_1st = (assigned_date + relativedelta(months=1)).replace(day=1)

    # Casual Leave (1/month, cap 12): retrospective from joining, minus Probation Casual Leave taken
    if is_casual_leave_type(leave_type) and getattr(leave_type, "reset_based", None) == "monthly":
        if employee:
            join_date = _join_date(employee)
            if join_date:
                months_from_joining = (assigned_date.year - join_date.year) * 12 + (assigned_date.month - join_date.month) + 1
                pcl_taken = get_probation_casual_leave_taken(employee, assigned_date)
                init_days = max(0, min(12, months_from_joining) - pcl_taken)
                return (round(init_days, 2), date(assigned_date.year + 1, 1, 1))
        init_days = min(12, months_remaining)
        return (init_days, date(assigned_date.year + 1, 1, 1))

    # Probation Leave / Probation Casual Leave (1/month, no carryforward)
    if (
        leave_type.name in PROBATION_LEAVE_NAMES
        or leave_type.name in PROBATION_CASUAL_LEAVE_NAMES
        or is_probation_casual_leave_type(leave_type)
    ) and getattr(leave_type, "reset_based", None) == "monthly":
        init_days = 1
        return (init_days, next_1st)

    if leave_type.name == "Sick Leave":
        # Get probation leave taken by employee
        probation_leave_taken = get_probation_leave_taken(employee, assigned_date)
        # Calculate sick leave: 7 days total minus probation leave taken
        init_days = max(0, round(7 - probation_leave_taken, 2))
        return (init_days, None)

    if leave_type.name in ("Earned Leave", "Earned Leave (EL)", "Earned Leave – Paid") and getattr(leave_type, "reset_based", None) == "monthly":
        # EL: 1.25 per month retrospective from joining date to confirmation month
        el_per_month = float(leave_type.total_days or 1.25)
        if employee:
            join_date = _join_date(employee)
            if join_date:
                months_from_joining = (assigned_date.year - join_date.year) * 12 + (assigned_date.month - join_date.month) + 1
                init_days = round(el_per_month * months_from_joining, 3)
                return (init_days, next_1st)
        # Fallback to current month only if no employee info
        init_days = round(el_per_month, 3)
        return (init_days, next_1st)

    if getattr(leave_type, "reset_based", None) == "monthly":
        return (0, None)
    return (float(leave_type.total_days or 0), None)


def computed_balance_for_validation(available_leave, as_of_date=None):
    """
    For monthly accrual types (Earned Leave, Casual Leave, Probation Leave), return
    the same total available days used for display, so leave request validation
    matches the UI. Returns None for other types (caller uses available_days +
    carryforward + forcasted).
    """
    if not available_leave or not getattr(available_leave, "leave_type_id", None):
        return None
    leave_type = available_leave.leave_type_id
    lt_name = (leave_type.name or "").strip()
    reset_based = getattr(leave_type, "reset_based", None) or ""
    total_days_val = round(float(leave_type.total_days or 0), 2)
    as_of = as_of_date or date.today()

    LeaveRequest = apps.get_model("leave", "LeaveRequest")

    def months_accrued(accrual_start):
        return max(
            0,
            (as_of.year - accrual_start.year) * 12
            + (as_of.month - accrual_start.month)
            + 1,
        )

    def approved_taken():
        return (
            LeaveRequest.objects.filter(
                employee_id=available_leave.employee_id,
                leave_type_id=leave_type,
                status="approved",
            ).aggregate(total=Sum("requested_days"))["total"]
            or 0
        )

    # Earned Leave: monthly 1.25
    is_el = (
        (reset_based == "monthly" and ("Earned Leave" in lt_name or total_days_val == 1.25))
        or ("Earned Leave" in lt_name and total_days_val == 1.25)
    )
    if is_el and leave_type.total_days:
        EL_EPOCH_DATE = date(2026, 1, 1)
        join_date = _join_date(available_leave.employee_id)
        raw_start = getattr(available_leave, "assigned_date", None)
        
        if join_date:
            accrual_start = max(EL_EPOCH_DATE, join_date.replace(day=1))
        else:
            accrual_start = (
                max(EL_EPOCH_DATE, raw_start.replace(day=1))
                if raw_start
                else EL_EPOCH_DATE
            )
            
        months = months_accrued(accrual_start)
        total_accrued = float(leave_type.total_days) * months
        cap = leave_type.carryforward_max if leave_type.carryforward_max is not None else 9999
        balance = min(max(0.0, total_accrued - approved_taken()), cap)
        return round(balance, 3)

    # Casual Leave: monthly 1, cap 12, minus Probation Casual Leave taken
    is_cl = is_casual_leave_type(leave_type) and reset_based == "monthly" and total_days_val == 1.0
    if is_cl and leave_type.total_days:
        return get_casual_leave_balance_stats(available_leave, as_of)["available_days"]

    # Probation Leave / Interns Leave: 1 per month, NO carry forward.
    # At any time at most 2 in bucket: current month + previous month (if unused).
    lt_name_lower = lt_name.lower()
    is_pl_or_interns = (
        total_days_val == 1.0
        and ("probation" in lt_name_lower or "interns leave" in lt_name_lower or "intern" in lt_name_lower)
    )
    if is_pl_or_interns and leave_type.total_days:
        return get_probation_period_leave_balance_stats(available_leave, as_of)[
            "available_days"
        ]

    if is_sick_leave_type(leave_type):
        return get_sick_leave_balance_stats(available_leave, as_of)["available_days"]

    return None


def probation_leave_days_in_month(employee_id, leave_type_id, year, month, exclude_leave_request_id=None):
    """
    For Probation/Interns Leave: total approved + requested days in the given calendar month.
    Used to enforce max 1 day per month.
    """
    LeaveRequest = apps.get_model("leave", "LeaveRequest")
    qs = LeaveRequest.objects.filter(
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        status__in=("approved", "requested"),
        start_date__year=year,
        start_date__month=month,
    )
    if exclude_leave_request_id is not None:
        qs = qs.exclude(pk=exclude_leave_request_id)
    return qs.aggregate(total=Sum("requested_days"))["total"] or 0


def calculate_requested_days(
    start_date, end_date, start_date_breakdown, end_date_breakdown, exclude_holidays=True, employee_id=None
):
    if start_date == end_date:
        return (
            1
            if start_date_breakdown == "full_day" and end_date_breakdown == "full_day"
            else 0.5
        )

    # Count full days between the two dates, excluding start and end
    middle_days = (end_date - start_date).days - 1

    # Count start and end days
    start_day_value = 1 if start_date_breakdown == "full_day" else 0.5
    end_day_value = 1 if end_date_breakdown == "full_day" else 0.5

    total_days = middle_days + start_day_value + end_day_value

    # Automatically exclude holidays and company leaves if requested
    if exclude_holidays:
        from base.methods import is_holiday
        from attendance.methods.utils import monthly_leave_days, monthly_holiday_dates

        # Get all dates in the leave period
        requested_dates = [start_date + timedelta(i) for i in range((end_date - start_date).days + 1)]

        # Get all holidays and company leave dates for each month in the leave period
        excluded_dates = set()
        current_date = start_date
        while current_date <= end_date:
            month = current_date.month
            year = current_date.year
            # Get public holidays for this month
            excluded_dates.update(monthly_holiday_dates(month, year))
            # Get company leaves (including alternating Saturdays) for this month
            excluded_dates.update(monthly_leave_days(month, year))
            # Move to next month
            if month == 12:
                current_date = date(year + 1, 1, 1)
            else:
                current_date = date(year, month + 1, 1)

        # Count how many days in the period are holidays or company leaves
        excluded_count = sum(
            1 for date in requested_dates if date in excluded_dates
        )

        # Subtract excluded days from total
        total_days = max(0, total_days - excluded_count)

    return total_days


def holiday_dates_list(holidays):
    """
    :return: This function returns a list of all holiday dates.
    """
    holiday_dates = []
    for holiday in holidays:
        holiday_start_date = holiday.start_date
        holiday_end_date = holiday.end_date or holiday_start_date
        holiday_dates.extend(
            holiday_start_date + timedelta(i)
            for i in range((holiday_end_date - holiday_start_date).days + 1)
        )
    return holiday_dates


def company_leave_dates_list(company_leaves, start_date):
    """
    :return: This function returns a list of all company leave dates
    """
    company_leave_dates = set()
    year = start_date.year
    for company_leave in company_leaves:
        based_on_week = company_leave.based_on_week
        based_on_week_day = company_leave.based_on_week_day

        for month in range(1, 13):
            month_calendar = calendar.monthcalendar(year, month)

            if based_on_week is not None:
                # Set Sunday as the first day of the week
                calendar.setfirstweekday(6)
                try:
                    week_days = [
                        day for day in month_calendar[int(based_on_week)] if day != 0
                    ]
                    for day in week_days:
                        date = datetime(year, month, day)
                        if date.weekday() == int(based_on_week_day):
                            company_leave_dates.add(date.date())
                except IndexError:
                    pass
            else:
                # Set Monday as the first day of the week
                calendar.setfirstweekday(0)
                for week in month_calendar:
                    if week[int(based_on_week_day)] != 0:
                        date = datetime(year, month, week[int(based_on_week_day)])
                        company_leave_dates.add(date.date())

    return list(company_leave_dates)


def get_leave_day_attendance(employee, comp_id=None):
    """
    This function returns a queryset of attendance on leave dates
    """
    Attendance = get_horilla_model_class(app_label="attendance", model="attendance")
    from leave.models import CompensatoryLeaveRequest

    attendances_to_exclude = Attendance.objects.none()  # Empty queryset to start with
    # Check for compensatory leave requests that are not rejected and not the current one
    if (
        CompensatoryLeaveRequest.objects.filter(employee_id=employee)
        .exclude(Q(id=comp_id) | Q(status="rejected"))
        .exists()
    ):
        comp_leave_reqs = CompensatoryLeaveRequest.objects.filter(
            employee_id=employee
        ).exclude(Q(id=comp_id) | Q(status="rejected"))
        for req in comp_leave_reqs:
            attendances_to_exclude |= req.attendance_id.all()
    # Filter holiday attendance excluding the attendances in attendances_to_exclude
    holiday_attendance = Attendance.objects.filter(
        is_holiday=True, employee_id=employee, attendance_validated=True
    ).exclude(id__in=attendances_to_exclude.values_list("id", flat=True))
    return holiday_attendance


def attendance_days(employee, attendances):
    """
    This function returns count of workrecord from the attendance
    """
    attendance_days = 0
    if apps.is_installed("attendance"):
        from attendance.models import WorkRecords

        for attendance in attendances:
            if WorkRecords.objects.filter(
                employee_id=employee, date=attendance.attendance_date
            ).exists():
                work_record_type = (
                    WorkRecords.objects.filter(
                        employee_id=employee, date=attendance.attendance_date
                    )
                    .first()
                    .work_record_type
                )
                if work_record_type == "HDP":
                    attendance_days += 0.5
                elif work_record_type == "FDP":
                    attendance_days += 1
    return attendance_days


def filter_conditional_leave_request(request):
    """
    Filters and returns LeaveRequest objects that have been conditionally approved by the previous sequence of approvals.
    """
    approval_manager = Employee.objects.filter(employee_user_id=request.user).first()
    leave_request_ids = []
    if apps.is_installed("leave"):
        from leave.models import LeaveRequest, LeaveRequestConditionApproval

        multiple_approval_requests = LeaveRequestConditionApproval.objects.filter(
            manager_id=approval_manager
        )
    else:
        multiple_approval_requests = None
    for instance in multiple_approval_requests:
        if instance.sequence > 1:
            pre_sequence = instance.sequence - 1
            leave_request_id = instance.leave_request_id
            instance = LeaveRequestConditionApproval.objects.filter(
                leave_request_id=leave_request_id, sequence=pre_sequence
            ).first()
            if instance and instance.is_approved:
                leave_request_ids.append(instance.leave_request_id.id)
        else:
            leave_request_ids.append(instance.leave_request_id.id)
    return LeaveRequest.objects.filter(pk__in=leave_request_ids)
