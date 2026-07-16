# attendance/signals.py

import logging
from datetime import datetime, timedelta

from django.apps import apps
from django.db.models.signals import post_migrate, post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from attendance.methods.utils import strtime_seconds
from attendance.models import Attendance, AttendanceGeneralSetting, WorkRecords
from base.models import Company, PenaltyAccounts
from employee.models import Employee
from horilla.methods import get_horilla_model_class

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=WorkRecords)
def log_work_record_type_change(sender, instance, **kwargs):
    try:
        if instance.pk:
            old_instance = WorkRecords.objects.get(pk=instance.pk)
            if old_instance.work_record_type != instance.work_record_type:
                from datetime import date as date_class
                # Protect SP records for past dates from being overwritten
                if old_instance.work_record_type == "SP" and instance.date < date_class.today():
                    instance.work_record_type = old_instance.work_record_type  # Keep SP
                    return
    except WorkRecords.DoesNotExist:
        pass


@receiver(post_save, sender=WorkRecords)
def protect_sp_records_post_save(sender, instance, **kwargs):
    """
    Revert HDP back to SP for past dates with at_work_second < 7200 (2 hours)
    This catches any bulk updates that bypass pre_save signals
    """
    from datetime import date as date_class
    if instance.date < date_class.today() and instance.at_work_second and instance.at_work_second < 7200:
        if instance.work_record_type == "HDP":
            # Use update to avoid triggering another save signal
            WorkRecords.objects.filter(pk=instance.pk).update(work_record_type="SP")


@receiver(post_save, sender=Attendance)
def attendance_post_save(sender, instance, **kwargs):
    """
    Handle post-save actions for Attendance model.
    
    Work Record Type Logic:
    - MP (Missing Punch): Check-in == Check-out (same time, 0 worked) OR no check-out for past day
    - HP (Half Day Present): Worked > 0 hours but < 8 hours
    - P (Present/FDP): Worked >= 8 hours
    - CONF: Attendance not validated yet
    """
    from datetime import date
    
    min_hour_second = strtime_seconds(instance.minimum_hour)
    at_work_second = strtime_seconds(instance.attendance_worked_hour)
    
    FULL_DAY_SECONDS = 28800  # 8 hours = 28800 seconds
    SHORT_PRESENCE_SECONDS = 7200  # 2 hours = 7200 seconds
    
    # Check for Missing Punch conditions first
    is_missing_punch = False
    
    # MP threshold: Less than 5 minutes (300 seconds) is considered missing punch
    MP_THRESHOLD_SECONDS = 300
    
    # Ensure at_work_second is a number
    if at_work_second is None:
        at_work_second = 0
    
    # Condition 1: No check-out for past day
    if not instance.attendance_clock_out:
        if instance.attendance_date == date.today():
            # Current day - still working
            is_missing_punch = False
        else:
            # Past day with no check-out - Missing Punch
            is_missing_punch = True
    # Condition 2: Worked less than 5 minutes (includes same time, 1-2 seconds, etc.)
    elif at_work_second < MP_THRESHOLD_SECONDS and instance.attendance_date != date.today():
        is_missing_punch = True
    
    # Determine status based on conditions
    if not instance.attendance_validated:
        status, message = "CONF", _("Validate the attendance")
    elif is_missing_punch:
        status, message = "MP", _("Missing Punch")
    elif not instance.attendance_clock_out and instance.attendance_date == date.today():
        # Currently working today (no check-out yet)
        status, message = "HDP", _("Currently working")
    elif at_work_second >= FULL_DAY_SECONDS:
        # Worked 8 hours or more = Present
        status, message = "FDP", _("Present")
    elif at_work_second >= SHORT_PRESENCE_SECONDS:
        # Worked 2 hours or more but less than 8 hours = Half Day Present
        status, message = "HDP", _("Half Day Present")
    elif at_work_second > 0:
        # Worked more than 0 but less than 2 hours = Short Presence
        status, message = "SP", _("Short Presence")
    else:
        # Fallback - should not reach here normally
        status, message = "ABS", _("Absent")
    
    try:
        work_record, created = WorkRecords.objects.get_or_create(
            date=instance.attendance_date,
            employee_id=instance.employee_id,
        )
    except WorkRecords.MultipleObjectsReturned:
        work_records = WorkRecords.objects.filter(
            date=instance.attendance_date,
            employee_id=instance.employee_id,
        )
        work_record = work_records.first()
        work_records.exclude(id=work_record.id).delete()
    except Exception as e:
        print(e)

    # Protect SP records for past dates from being overwritten by attendance_post_save signal
    if not created and work_record.work_record_type == "SP" and instance.attendance_date < date.today():
        return

    work_record.employee_id = instance.employee_id
    work_record.date = instance.attendance_date
    work_record.at_work = instance.attendance_worked_hour
    work_record.min_hour = instance.minimum_hour
    work_record.min_hour_second = min_hour_second
    work_record.at_work_second = at_work_second
    work_record.work_record_type = status
    work_record.message = message
    work_record.is_attendance_record = True
    work_record.attendance_id = instance
    work_record.shift_id = instance.shift_id

    if instance.attendance_validated:
        if at_work_second >= FULL_DAY_SECONDS:
            work_record.day_percentage = 1.00
        elif at_work_second >= SHORT_PRESENCE_SECONDS:
            work_record.day_percentage = 0.50
        elif at_work_second > 0:
            work_record.day_percentage = 0.25  # Short Presence = 25%
        else:
            work_record.day_percentage = 0.00

    # Handle leave records
    if work_record.is_leave_record:
        if status == "HDP":
            message = _("Half day leave")
            status = "HD"  # Change to Holiday/Leave status
        elif status == "SP":
            message = _("Short presence with leave")
            status = "HD"  # Change to Holiday/Leave status
        elif status == "FDP":
            message = _("On leave but attendance exists")
            status = "HD"  # Change to Holiday/Leave status
        else:
            message = _("An approved leave exists")
        work_record.work_record_type = status
        work_record.message = message

    work_record.save()


@receiver(pre_delete, sender=Attendance)
def handle_attendance_deletion(sender, instance, **kwargs):
    for workrecord in instance.workrecords_set.all():
        if not workrecord.leave_request_id:
            workrecord.delete()


# @receiver(post_migrate)
def add_missing_attendance_to_workrecord(sender, **kwargs):
    if sender.label not in ["attendance", "leave"]:
        return

    from attendance.models import Attendance, WorkRecords

    try:
        work_records = WorkRecords.objects.filter(
            is_attendance_record=True, attendance_id__isnull=True
        )

        if not work_records.exists():
            return

        attendances = Attendance.objects.all()
        attendance_map = {
            (att.employee_id, att.attendance_date): att for att in attendances
        }

        records_to_update = []
        for record in work_records:
            attendance = attendance_map.get((record.employee_id, record.date))
            if attendance:
                record.attendance_id = attendance
                records_to_update.append(record)
            else:
                record.delete()

        if records_to_update:
            WorkRecords.objects.bulk_update(
                records_to_update, ["attendance_id"], batch_size=500
            )
            logger.info(
                f"Successfully updated {len(records_to_update)} work records with attendance information."
            )

    except Exception as e:
        logger.error(f"Error updating work records with attendance: {e}")


# @receiver(post_migrate)
def add_missing_shift_to_work_record(sender, **kwargs):
    if sender.label not in ["attendance", "leave"]:
        return

    try:
        work_records = WorkRecords.objects.filter(
            is_attendance_record=True, shift_id__isnull=True
        )

        if not work_records.exists():
            return

        records_to_update = []

        for record in work_records:
            if record.attendance_id:
                record.shift_id = record.attendance_id.shift_id
            else:
                record.shift_id = record.employee_id.employee_work_info.shift_id

            records_to_update.append(record)

        if records_to_update:
            WorkRecords.objects.bulk_update(
                records_to_update, ["shift_id"], batch_size=500
            )
            print(
                f"Successfully updated {len(records_to_update)} work records with shift information."
            )

    except Exception as e:
        print(f"Error updating work records with shift information: {e}")


@receiver(post_save, sender=Company)
def create_attendance_setting(sender, instance, created, raw, **kwargs):
    """
    Signal receiver that automatically creates an AttendanceGeneralSetting object
    whenever a new Company is created. This does NOT skip creation during
    loaddata, so the object will also be created when fixture data is loaded.
    """
    AttendanceGeneralSetting.objects.get_or_create(company_id=None)
    if created:
        AttendanceGeneralSetting.objects.get_or_create(company_id=instance)


# @receiver(post_migrate)
def create_missing_work_records(sender, **kwargs):
    if sender.label not in ["attendance"]:
        return

    employees = Employee.objects.all()
    work_records = WorkRecords.objects.all()

    if work_records.exists():
        st_date = work_records.earliest("date").date

        for employee in employees:
            try:
                start_date = employee.employee_work_info.date_joining or st_date
                end_date = datetime.today().date()

                existing_dates = set(
                    WorkRecords.objects.filter(employee_id=employee.id).values_list(
                        "date", flat=True
                    )
                )

                all_dates = {
                    start_date + timedelta(days=i)
                    for i in range((end_date - start_date).days)
                }
                missing_dates = all_dates - existing_dates

                work_records_to_create = [
                    WorkRecords(
                        employee_id=employee,
                        date=missing_date,
                        work_record_type="DFT",
                        shift_id=employee.employee_work_info.shift_id,
                    )
                    for missing_date in missing_dates
                ]

                if work_records_to_create:
                    WorkRecords.objects.bulk_create(
                        work_records_to_create, batch_size=500, ignore_conflicts=True
                    )

            except Exception as e:
                print(
                    f"Error creating missing work records for employee {employee}: {e}"
                )
