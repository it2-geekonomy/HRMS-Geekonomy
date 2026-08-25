"""
Helper functions for probation period leave credit logic.
Can be used by signals, management commands, and views.
"""
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from leave.models import LeaveType, AvailableLeave
from leave.intern_leave import is_intern
from leave.methods import get_probation_leave_taken, get_probation_casual_leave_taken
from employee.models import Employee, EmployeeWorkInformation


def credit_probation_leave_for_employee(employee, force_update=False):
    """
    Credit accumulated leave for an employee who completed 3 months probation period.

    Args:
        employee: Employee instance
        force_update: If True, update even if leave already exists

    Returns:
        dict with 'credited', 'skipped', 'error' status and details
    """
    today = timezone.now().date()
    result = {
        "credited": False,
        "skipped": False,
        "error": None,
        "details": {},
    }

    try:
        work_info = EmployeeWorkInformation.objects.filter(
            employee_id=employee
        ).first()

        if not work_info or not work_info.date_joining:
            result["skipped"] = True
            result["error"] = "No joining date found"
            return result
        if is_intern(employee):
            result["skipped"] = True
            result["error"] = "Interns get 1 SL per 3 months only; use fix_leave_balances"
            return result

        joining_date = work_info.date_joining
        employee_probation_end = joining_date + relativedelta(months=3)

        if today < employee_probation_end:
            result["skipped"] = True
            result["error"] = "Still in probation period"
            return result

        def get_leave_type_by_name(exact_names, fallback_contains, exclude_contains=None):
            qs = LeaveType.objects.filter(name__in=exact_names).first()
            if qs:
                return qs
            q = LeaveType.objects.filter(name__icontains=fallback_contains)
            if exclude_contains:
                q = q.exclude(name__icontains=exclude_contains)
            return q.first()

        el_type = get_leave_type_by_name(
            ["Earned Leave (EL)", "Earned Leave"], "Earned Leave"
        )
        cl_type = get_leave_type_by_name(
            ["Casual Leave (CL)", "Casual Leave"],
            "Casual Leave",
            exclude_contains="Probation",
        )
        sl_type = get_leave_type_by_name(
            ["Sick Leave (SL)", "Sick Leave"], "Sick Leave"
        )
        if not el_type or not cl_type or not sl_type:
            missing = []
            if not el_type:
                missing.append("Earned Leave")
            if not cl_type:
                missing.append("Casual Leave")
            if not sl_type:
                missing.append("Sick Leave")
            result["error"] = (
                f"Required leave type(s) not found: {', '.join(missing)}. "
                "Create them in Leave > Leave Types."
            )
            return result

        el_exists = AvailableLeave.objects.filter(
            employee_id=employee, leave_type_id=el_type
        ).exists()
        cl_exists = AvailableLeave.objects.filter(
            employee_id=employee, leave_type_id=cl_type
        ).exists()
        sl_exists = AvailableLeave.objects.filter(
            employee_id=employee, leave_type_id=sl_type
        ).exists()

        if el_exists and cl_exists and sl_exists and not force_update:
            result["skipped"] = True
            result["error"] = "Leave already credited"
            return result

        from datetime import date as date_class

        EL_CL_START_DATE = date_class(2026, 1, 1)
        assigned_date = max(EL_CL_START_DATE, joining_date)

        months_from_joining = (
            (today.year - joining_date.year) * 12
            + (today.month - joining_date.month)
            + 1
        )
        el_days = 1.25 * months_from_joining
        # Casual Leave: months credited minus Probation Casual Leave taken
        probation_casual_taken = get_probation_casual_leave_taken(employee, today)
        cl_days = max(0, round(months_from_joining - probation_casual_taken, 2))
        # Sick Leave: 7 days minus Probation Leave taken
        probation_leave_taken = get_probation_leave_taken(employee, today)
        sl_days = max(0, round(7 - probation_leave_taken, 2))

        with transaction.atomic():
            if not el_exists or force_update:
                el_leave, created = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=el_type,
                    defaults={
                        "available_days": el_days,
                        "assigned_date": assigned_date,
                    },
                )
                if not created or force_update:
                    el_leave.available_days = el_days
                    if force_update:
                        el_leave.assigned_date = assigned_date
                    el_leave.save()
                result["details"]["EL"] = el_days

            if not cl_exists or force_update:
                cl_leave, created = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=cl_type,
                    defaults={
                        "available_days": cl_days,
                        "assigned_date": assigned_date,
                    },
                )
                if not created or force_update:
                    cl_leave.available_days = cl_days
                    if force_update:
                        cl_leave.assigned_date = assigned_date
                    cl_leave.save()
                result["details"]["CL"] = cl_days
                result["details"]["PCL_taken"] = probation_casual_taken

            if not sl_exists or force_update:
                sl_leave, created = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=sl_type,
                    defaults={
                        "available_days": sl_days,
                        "assigned_date": assigned_date,
                    },
                )
                if not created or force_update:
                    sl_leave.available_days = sl_days
                    if force_update:
                        sl_leave.assigned_date = assigned_date
                    sl_leave.save()
                result["details"]["SL"] = sl_days
                result["details"]["PL_taken"] = probation_leave_taken

        result["credited"] = True
        return result

    except Exception as e:
        result["error"] = str(e)
        return result


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
PROBATION_PERIOD_LEAVE_NAMES = PROBATION_LEAVE_NAMES + PROBATION_CASUAL_LEAVE_NAMES


def switch_employee_from_probation_to_regular_leave(employee):
    """
    On probation Confirm: remove Probation Leave and Probation Casual Leave,
    then assign Earned Leave (EL), Sick Leave (SL), Casual Leave (CL).
    - Probation Leave taken is deducted from Sick Leave
    - Probation Casual Leave taken is deducted from Casual Leave
    """
    result = {"removed_pl": False, "credited": False, "error": None}
    try:
        pl_types = LeaveType.objects.filter(name__in=PROBATION_PERIOD_LEAVE_NAMES)
        if pl_types.exists():
            deleted, _ = AvailableLeave.objects.filter(
                employee_id=employee,
                leave_type_id__in=pl_types,
            ).delete()
            result["removed_pl"] = deleted > 0
        credit_result = credit_probation_leave_for_employee(employee, force_update=True)
        result["credited"] = credit_result.get("credited", False)
        result["error"] = credit_result.get("error")
        result["details"] = credit_result.get("details", {})
    except Exception as e:
        result["error"] = str(e)
    return result


REGULAR_LEAVE_NAMES = (
    "Earned Leave",
    "Earned Leave (EL)",
    "Casual Leave",
    "Casual Leave (CL)",
    "Sick Leave",
    "Sick Leave (SL)",
)


def revert_employee_from_regular_to_probation_leave(employee):
    """
    Undo Confirm leave switch: remove EL/CL/SL and restore Probation Leave +
    Probation Casual Leave (1 day each for current month).
    """
    today = timezone.now().date()
    result = {"removed_regular": False, "restored_pl": False, "error": None}
    try:
        with transaction.atomic():
            regular_types = LeaveType.objects.filter(name__in=REGULAR_LEAVE_NAMES)
            if regular_types.exists():
                deleted, _ = AvailableLeave.objects.filter(
                    employee_id=employee,
                    leave_type_id__in=regular_types,
                ).delete()
                result["removed_regular"] = deleted > 0

            next_1st = (today + relativedelta(months=1)).replace(day=1)
            restored_any = False
            for name_set, label in (
                (PROBATION_LEAVE_NAMES, "Probation Sick Leave"),
                (PROBATION_CASUAL_LEAVE_NAMES, "Probation Casual Leave"),
            ):
                leave_type = LeaveType.objects.filter(name__in=name_set).first()
                if not leave_type:
                    if label == "Probation Sick Leave":
                        result["error"] = (
                            "Probation Sick Leave type not found. "
                            "Create it in Leave > Leave Types."
                        )
                        return result
                    continue
                pl_leave, created = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=leave_type,
                    defaults={
                        "available_days": 1,
                        "assigned_date": today,
                        "reset_date": next_1st,
                    },
                )
                if not created:
                    pl_leave.available_days = 1
                    pl_leave.assigned_date = today
                    pl_leave.reset_date = next_1st
                    pl_leave.save(
                        update_fields=["available_days", "assigned_date", "reset_date"]
                    )
                restored_any = True
            result["restored_pl"] = restored_any
    except Exception as e:
        result["error"] = str(e)
    return result
