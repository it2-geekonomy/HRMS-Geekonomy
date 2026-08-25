"""
Signals for leave app - automatically credit leave when employee joins or joining date is updated
and create work records when leave requests are approved
"""
from datetime import date
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.apps import apps
from django.utils.translation import gettext_lazy as _
import logging

logger = logging.getLogger(__name__)

# Store old joining date to detect changes
_old_joining_dates = {}

ATTENDANCE_PRESENT_TYPES = ("FDP", "HDP", "SP")


def _is_half_day_leave_on_date(leave_request, leave_date):
    """True when this calendar date is half-day leave (first/second half), not full day."""
    start = leave_request.start_date
    end = leave_request.end_date or start
    if leave_request.requested_days == 0.5 and start == end:
        return True
    if leave_date == start and leave_request.start_date_breakdown in (
        "first_half",
        "second_half",
    ):
        return True
    if leave_date == end and leave_request.end_date_breakdown in (
        "first_half",
        "second_half",
    ):
        return True
    return False


def _restore_attendance_type_from_hours(work_record):
    """
    Infer FDP/HDP/SP from stored worked hours when leave wrongly overwrote type to L.
    Returns restored type or None if hours are missing.
    """
    at_work = getattr(work_record, "at_work_second", None) or 0
    if at_work <= 0 and work_record.attendance_id_id:
        try:
            from attendance.methods.utils import strtime_seconds

            att = work_record.attendance_id
            if att and att.attendance_worked_hour:
                at_work = strtime_seconds(att.attendance_worked_hour)
                work_record.at_work = att.attendance_worked_hour
                work_record.at_work_second = at_work
        except Exception:
            pass
    if at_work <= 0:
        return None
    # Same thresholds as attendance_post_save (8h full, 2h half, else short)
    FULL_DAY_SECONDS = 8 * 3600
    SHORT_PRESENCE_SECONDS = 2 * 3600
    if at_work >= FULL_DAY_SECONDS:
        return "FDP"
    if at_work >= SHORT_PRESENCE_SECONDS:
        return "HDP"
    return "SP"


def connect_signals():
    """Connect signals after apps are loaded to avoid circular imports"""
    EmployeeWorkInformation = apps.get_model('employee', 'EmployeeWorkInformation')
    LeaveRequest = apps.get_model('leave', 'LeaveRequest')
    
    pre_save.connect(store_old_joining_date, sender=EmployeeWorkInformation)
    post_save.connect(auto_credit_leave_on_joining_date, sender=EmployeeWorkInformation)
    post_save.connect(create_work_records_for_leave, sender=LeaveRequest)


def store_old_joining_date(sender, instance, **kwargs):
    """Store the old joining date before save to detect changes"""
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            _old_joining_dates[instance.pk] = old_instance.date_joining
        except sender.DoesNotExist:
            _old_joining_dates[instance.pk] = None
    else:
        _old_joining_dates[instance.pk] = None


def auto_credit_leave_on_joining_date(sender, instance, created, **kwargs):
    """
    Left disabled: leave is created and assigned manually.
    Previously auto-credited EL/CL/SL after probation via probation_leave.
    """
    return


def create_work_records_for_leave(sender, instance, created, **kwargs):
    """
    Create or update work records when leave requests are approved/rejected/cancelled.
    Full-day leave → "L". Half-day leave with attendance kept as HDP/FDP/SP → calendar shows HP/L.
    """
    # Only process if leave app is installed
    if not apps.is_installed('attendance'):
        return

    # Lazy imports to avoid circular dependencies
    WorkRecords = apps.get_model('attendance', 'WorkRecords')
    from base.methods import get_date_range, is_holiday
    from attendance.methods.utils import monthly_leave_days, monthly_holiday_dates

    try:
        # Get all dates in the leave period
        period_dates = get_date_range(instance.start_date, instance.end_date)

        # Get all holidays and company leave dates for the leave period
        excluded_dates = set()
        current_date = instance.start_date
        while current_date <= instance.end_date:
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

        if instance.status == "approved":
            # Create or update work records for approved leave
            for leave_date in period_dates:
                # Check if this date is a holiday or company leave (WO/PH)
                is_holiday_or_company_leave = leave_date in excluded_dates
                is_half = _is_half_day_leave_on_date(instance, leave_date)

                # Determine the work record type - use 'HD' for holidays/company leaves, 'L' for regular leave
                work_record_type = 'HD' if is_holiday_or_company_leave else 'L'

                # Get or create work record for this date
                work_record, work_record_created = WorkRecords.objects.get_or_create(
                    date=leave_date,
                    employee_id=instance.employee_id,
                    defaults={
                        'work_record_type': work_record_type,
                        'is_leave_record': True,
                        'leave_request_id': instance,
                        'message': _("Half day leave") if is_half else _("On leave"),
                    }
                )

                # Update existing work record if it wasn't created
                if not work_record_created:
                    # Holiday/company leave (WO/PH) takes priority over attendance
                    if is_holiday_or_company_leave:
                        work_record.work_record_type = "HD"
                        work_record.is_leave_record = True
                        work_record.leave_request_id = instance
                        work_record.message = _("On leave")
                        work_record.save()
                        continue

                    # Half-day leave + existing present/half/short presence → keep attendance type
                    # so calendar shows HP/L (first or second half leave + other half present).
                    has_attendance = (
                        work_record.is_attendance_record
                        or work_record.work_record_type in ATTENDANCE_PRESENT_TYPES
                        or bool(work_record.attendance_id_id)
                        or (work_record.at_work_second or 0) > 0
                    )
                    if is_half and has_attendance:
                        if work_record.work_record_type not in ATTENDANCE_PRESENT_TYPES:
                            restored = _restore_attendance_type_from_hours(work_record)
                            if restored:
                                work_record.work_record_type = restored
                        work_record.is_leave_record = True
                        work_record.leave_request_id = instance
                        work_record.message = _("Half day leave")
                        work_record.save()
                        continue

                    work_record.work_record_type = work_record_type
                    work_record.is_leave_record = True
                    work_record.leave_request_id = instance
                    work_record.message = (
                        _("Half day leave") if is_half else _("On leave")
                    )
                    work_record.save()
                
        elif instance.status in ["rejected", "cancelled"]:
            # Delete work records created for this leave request
            WorkRecords.objects.filter(
                is_leave_record=True,
                leave_request_id=instance,
                date__in=period_dates,
                employee_id=instance.employee_id,
            ).delete()
            
    except Exception as e:
        logger.error(
            f"Error creating work records for leave request {instance.id}: {e}",
            exc_info=True
        )
