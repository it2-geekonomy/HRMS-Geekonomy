from datetime import date
from dateutil.relativedelta import relativedelta
from django.db import migrations


def switch_to_monthly_casual_and_sick_leaves(apps, schema_editor):
    """
    1. Mark all existing legacy leave types as inactive (is_active=False) with clean names.
    2. Create 2 new active monthly leave types: Casual Leave and Sick Leave (1 day/month, no carryforward).
    3. Assign both to all active employees with 1.0 day available.
    """
    LeaveType = apps.get_model("leave", "LeaveType")
    AvailableLeave = apps.get_model("leave", "AvailableLeave")
    Employee = apps.get_model("employee", "Employee")

    today = date.today()
    next_1st = (today + relativedelta(months=1)).replace(day=1)

    # 1. Dynamically identify and deactivate all existing legacy leave types
    # without relying on hardcoded IDs (which differ between environments).
    for lt in LeaveType.objects.all():
        is_new_monthly = (
            lt.reset_based == "monthly"
            and lt.carryforward_type == "no carryforward"
            and round(float(lt.total_days or 0), 2) == 1.0
            and "probation" not in (lt.name or "").lower()
            and "intern" not in (lt.name or "").lower()
            and not getattr(lt, "is_compensatory_leave", False)
        )
        # Clean any legacy prefix in name if present
        name = lt.name or ""
        for prefix in ["[Old] ", "[Legacy] "]:
            if name.startswith(prefix):
                name = name[len(prefix):]
        lt.name = name

        if not is_new_monthly:
            lt.is_active = False
            name_lower = (lt.name or "").strip().lower()
            if "casual" in name_lower and "probation" not in name_lower:
                lt.name = "Casual Leave (old)"
            elif "sick" in name_lower and "probation" not in name_lower and "intern" not in name_lower:
                lt.name = "Sick Leave (old)"
        lt.save()

    # 2. Get or create new active Casual Leave (monthly, no carryforward)
    cl_type = LeaveType.objects.filter(
        name="Casual Leave",
        is_active=True,
        reset_based="monthly",
        carryforward_type="no carryforward",
    ).first()

    if not cl_type:
        cl_type = LeaveType.objects.create(
            name="Casual Leave",
            payment="paid",
            count=1.0,
            period_in="day",
            limit_leave=True,
            total_days=1.0,
            reset=True,
            reset_based="monthly",
            reset_month="1",
            reset_day="1",
            carryforward_type="no carryforward",
            carryforward_max=None,
            is_active=True,
            require_approval="yes",
            require_attachment="no",
            color="#1E88E5",
        )

    # 3. Get or create new active Sick Leave (monthly, no carryforward)
    sl_type = LeaveType.objects.filter(
        name="Sick Leave",
        is_active=True,
        reset_based="monthly",
        carryforward_type="no carryforward",
    ).first()

    if not sl_type:
        sl_type = LeaveType.objects.create(
            name="Sick Leave",
            payment="paid",
            count=1.0,
            period_in="day",
            limit_leave=True,
            total_days=1.0,
            reset=True,
            reset_based="monthly",
            reset_month="1",
            reset_day="1",
            carryforward_type="no carryforward",
            carryforward_max=None,
            is_active=True,
            require_approval="yes",
            require_attachment="no",
            color="#43A047",
        )

    # 4. Assign both to all active employees
    for emp in Employee.objects.filter(is_active=True):
        # Casual Leave
        AvailableLeave.objects.update_or_create(
            employee_id=emp,
            leave_type_id=cl_type,
            defaults={
                "available_days": 1.0,
                "carryforward_days": 0.0,
                "assigned_date": today,
                "reset_date": next_1st,
            },
        )
        # Sick Leave
        AvailableLeave.objects.update_or_create(
            employee_id=emp,
            leave_type_id=sl_type,
            defaults={
                "available_days": 1.0,
                "carryforward_days": 0.0,
                "assigned_date": today,
                "reset_date": next_1st,
            },
        )


def rollback_monthly_leaves(apps, schema_editor):
    """
    Rollback: Reactivate legacy leave types and deactivate the monthly ones.
    """
    LeaveType = apps.get_model("leave", "LeaveType")
    for lt in LeaveType.objects.all():
        is_new_monthly = (
            lt.reset_based == "monthly"
            and lt.carryforward_type == "no carryforward"
            and round(float(lt.total_days or 0), 2) == 1.0
            and "probation" not in (lt.name or "").lower()
            and "intern" not in (lt.name or "").lower()
            and not getattr(lt, "is_compensatory_leave", False)
        )
        if is_new_monthly:
            lt.is_active = False
        else:
            lt.is_active = True
        lt.save()


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0012_rename_probation_leave_to_probation_sick_leave"),
    ]

    operations = [
        migrations.RunPython(
            switch_to_monthly_casual_and_sick_leaves,
            rollback_monthly_leaves,
        ),
    ]
