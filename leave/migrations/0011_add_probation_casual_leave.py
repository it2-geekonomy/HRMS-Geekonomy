from django.db import migrations


def create_probation_casual_leave(apps, schema_editor):
    """
    Create 'Probation Casual Leave':
    - Same rules as Probation Leave: 1 day/month, no carryforward
    - On probation confirm: days taken are deducted from Casual Leave
    """
    LeaveType = apps.get_model("leave", "LeaveType")

    if LeaveType.objects.filter(name__iexact="Probation Casual Leave").exists():
        return
    if LeaveType.objects.filter(name__iexact="Probation Casual Leave (PCL)").exists():
        return

    LeaveType.objects.create(
        name="Probation Casual Leave",
        payment="paid",
        limit_leave=True,
        total_days=1.0,
        reset=True,
        reset_based="monthly",
        reset_month="1",
        reset_day="1",
        carryforward_type="no carryforward",
        carryforward_max=None,
        require_approval="yes",
        require_attachment="no",
    )


def delete_probation_casual_leave(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    LeaveType.objects.filter(
        name__in=("Probation Casual Leave", "Probation Casual Leave (PCL)")
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0010_comp_off_leave_policy"),
    ]

    operations = [
        migrations.RunPython(create_probation_casual_leave, delete_probation_casual_leave),
    ]
