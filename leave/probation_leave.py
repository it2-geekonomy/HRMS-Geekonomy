"""
Helper functions for probation period leave credit logic.
Can be used by signals, management commands, and views.
"""
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from leave.models import LeaveType, AvailableLeave
from leave.intern_leave import is_intern
from leave.methods import get_probation_leave_taken
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
        'credited': False,
        'skipped': False,
        'error': None,
        'details': {}
    }
    
    # Get employee work info and joining date
    try:
        work_info = EmployeeWorkInformation.objects.filter(
            employee_id=employee
        ).first()
        
        if not work_info or not work_info.date_joining:
            result['skipped'] = True
            result['error'] = 'No joining date found'
            return result
        if is_intern(employee):
            result['skipped'] = True
            result['error'] = 'Interns get 1 SL per 3 months only; use fix_leave_balances'
            return result
        
        joining_date = work_info.date_joining
        
        # Calculate probation end date
        employee_probation_end = joining_date + relativedelta(months=3)
        
        # Check if probation period has ended
        if today < employee_probation_end:
            result['skipped'] = True
            result['error'] = 'Still in probation period'
            return result
        
        # Get leave types (try exact name first, then match by containing key text)
        def get_leave_type_by_name(exact_names, fallback_contains):
            qs = LeaveType.objects.filter(name__in=exact_names).first()
            if qs:
                return qs
            return LeaveType.objects.filter(name__icontains=fallback_contains).first()

        el_type = get_leave_type_by_name(
            ["Earned Leave (EL)", "Earned Leave"], "Earned Leave"
        )
        cl_type = get_leave_type_by_name(
            ["Casual Leave (CL)", "Casual Leave"], "Casual Leave"
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
            result["error"] = f"Required leave type(s) not found: {', '.join(missing)}. Create them in Leave > Leave Types."
            return result
        
        # Check if leave already exists
        el_exists = AvailableLeave.objects.filter(
            employee_id=employee,
            leave_type_id=el_type
        ).exists()
        cl_exists = AvailableLeave.objects.filter(
            employee_id=employee,
            leave_type_id=cl_type
        ).exists()
        sl_exists = AvailableLeave.objects.filter(
            employee_id=employee,
            leave_type_id=sl_type
        ).exists()
        
        # If all exist and not forcing update, skip
        if el_exists and cl_exists and sl_exists and not force_update:
            result['skipped'] = True
            result['error'] = 'Leave already credited'
            return result
        
        # EL and CL: Retrospective from joining date to confirmation month
        # Calculate months from joining date to current month (confirmation month)
        # EL/CL applicable from Jan 1, 2026
        from datetime import date as date_class
        EL_CL_START_DATE = date_class(2026, 1, 1)
        assigned_date = max(EL_CL_START_DATE, joining_date)
        
        months_from_joining = (today.year - joining_date.year) * 12 + (today.month - joining_date.month) + 1
        el_days = 1.25 * months_from_joining
        cl_days = 1 * months_from_joining
        # Sick Leave: 7 days minus probation leave taken (same as get_init_days_and_reset_for_assign)
        probation_leave_taken = get_probation_leave_taken(employee, today)
        sl_days = max(0, round(7 - probation_leave_taken, 2))
        
        # Credit leave
        with transaction.atomic():
            # Credit Earned Leave (EL)
            if not el_exists or force_update:
                el_leave, created = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=el_type,
                    defaults={
                        'available_days': el_days,
                        'assigned_date': assigned_date,
                    }
                )
                if not created or force_update:
                    el_leave.available_days = el_days
                    if force_update:
                        el_leave.assigned_date = assigned_date
                    el_leave.save()
                result['details']['EL'] = el_days
            
            # Credit Casual Leave (CL)
            if not cl_exists or force_update:
                cl_leave, created = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=cl_type,
                    defaults={
                        'available_days': cl_days,
                        'assigned_date': assigned_date,
                    }
                )
                if not created or force_update:
                    cl_leave.available_days = cl_days
                    if force_update:
                        cl_leave.assigned_date = assigned_date
                    cl_leave.save()
                result['details']['CL'] = cl_days
            
            # Credit Sick Leave (SL)
            if not sl_exists or force_update:
                sl_leave, created = AvailableLeave.objects.get_or_create(
                    employee_id=employee,
                    leave_type_id=sl_type,
                    defaults={
                        'available_days': sl_days,
                        'assigned_date': assigned_date,
                    }
                )
                if not created or force_update:
                    sl_leave.available_days = sl_days
                    if force_update:
                        sl_leave.assigned_date = assigned_date
                    sl_leave.save()
                result['details']['SL'] = sl_days
        
        result['credited'] = True
        return result
        
    except Exception as e:
        result['error'] = str(e)
        return result


# Leave type name variants for Probation Leave (used when removing on confirm).
PROBATION_LEAVE_NAMES = ("Probation Leave", "Probation Leave (PL)")


def switch_employee_from_probation_to_regular_leave(employee):
    """
    On probation Confirm: remove Probation Leave (PL) assignment and assign
    Earned Leave (EL), Sick Leave (SL), Casual Leave (CL).
    Call this from employee probation_confirm view.
    """
    result = {"removed_pl": False, "credited": False, "error": None}
    try:
        pl_types = LeaveType.objects.filter(name__in=PROBATION_LEAVE_NAMES)
        if pl_types.exists():
            deleted, _ = AvailableLeave.objects.filter(
                employee_id=employee,
                leave_type_id__in=pl_types,
            ).delete()
            result["removed_pl"] = deleted > 0
        credit_result = credit_probation_leave_for_employee(employee, force_update=True)
        result["credited"] = credit_result.get("credited", False)
        result["error"] = credit_result.get("error")
    except Exception as e:
        result["error"] = str(e)
    return result