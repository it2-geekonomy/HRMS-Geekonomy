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
    This ensures "L" (Leave) appears in work records when an employee is on leave.
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
                        'message': _("On leave"),
                    }
                )

                # Update existing work record if it wasn't created
                if not work_record_created:
                    # Always set the correct work record type based on holiday/company leave status
                    # Holiday/company leave (WO/PH) takes priority over attendance
                    work_record.work_record_type = work_record_type
                    work_record.is_leave_record = True
                    work_record.leave_request_id = instance
                    work_record.message = _("On leave")
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
