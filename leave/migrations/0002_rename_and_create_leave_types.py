# Data migration: rename Paid leave types, create Interns Leave & Probation Leave,
# merge Sick Leave – Intern and Casual Leave – Intern into Interns Leave.

from django.db import migrations


def _monthly_one_no_carryforward():
    """Leave type defaults: 1 per month, no carryforward."""
    return {
        "total_days": 1.0,
        "reset": True,
        "reset_based": "monthly",
        "reset_month": "1",
        "reset_day": "1",
        "carryforward_type": "no carryforward",
        "payment": "paid",
        "limit_leave": True,
        "require_approval": "yes",
        "require_attachment": "no",
    }


def forward(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    AvailableLeave = apps.get_model("leave", "AvailableLeave")
    LeaveRequest = apps.get_model("leave", "LeaveRequest")
    Employee = apps.get_model("employee", "Employee")

    # 1. Rename Paid types (logic in code now uses new names)
    renames = [
        ("Earned Leave – Paid", "Earned Leave"),
        ("Sick Leave – Paid", "Sick Leave"),
        ("Casual Leave – Paid", "Casual Leave"),
    ]
    for old_name, new_name in renames:
        LeaveType.objects.filter(name=old_name).update(name=new_name)

    # 2. Create Interns Leave (1 per month, no carryforward) if not exists
    interns, _ = LeaveType.objects.get_or_create(
        name="Interns Leave",
        defaults=_monthly_one_no_carryforward(),
    )

    # 3. Create Probation Leave (1 per month, no carryforward) if not exists
    LeaveType.objects.get_or_create(
        name="Probation Leave",
        defaults=_monthly_one_no_carryforward(),
    )

    # 4. Merge Sick Leave – Intern and Casual Leave – Intern into Interns Leave
    sick_intern = LeaveType.objects.filter(name="Sick Leave – Intern").first()
    casual_intern = LeaveType.objects.filter(name="Casual Leave – Intern").first()

    if sick_intern or casual_intern:
        intern_type_ids = [t.id for t in [sick_intern, casual_intern] if t is not None]

        # Point all LeaveRequest from either intern type to Interns Leave
        LeaveRequest.objects.filter(leave_type_id__in=intern_type_ids).update(
            leave_type_id=interns.id
        )

        # For each employee with an AvailableLeave for either intern type, ensure one for Interns Leave
        avl_intern = AvailableLeave.objects.filter(leave_type_id__in=intern_type_ids)
        employees_seen = set()
        for avl in avl_intern:
            emp_id = avl.employee_id_id
            if emp_id not in employees_seen:
                employees_seen.add(emp_id)
                employee = Employee.objects.get(pk=emp_id)
                AvailableLeave.objects.get_or_create(
                    leave_type_id=interns,
                    employee_id=employee,
                    defaults={
                        "available_days": 1.0,
                        "total_leave_days": 1.0,
                        "carryforward_days": 0,
                    },
                )

        # Remove old AvailableLeave for the two intern types
        AvailableLeave.objects.filter(leave_type_id__in=intern_type_ids).delete()

        # Delete the two old leave types
        if sick_intern:
            sick_intern.delete()
        if casual_intern:
            casual_intern.delete()


def reverse(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    # Restore old names for Paid types
    renames = [
        ("Earned Leave", "Earned Leave – Paid"),
        ("Sick Leave", "Sick Leave – Paid"),
        ("Casual Leave", "Casual Leave – Paid"),
    ]
    for new_name, old_name in renames:
        LeaveType.objects.filter(name=new_name).update(name=old_name)
    # We do not recreate Sick Leave – Intern / Casual Leave – Intern or undo merge
    # (reverse would require storing old IDs). Probation Leave and Interns Leave
    # are left as-is on reverse; user can delete manually if needed.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
