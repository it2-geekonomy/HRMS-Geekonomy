from django.db import migrations


def rename_probation_leave(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    LeaveType.objects.filter(name="Probation Leave").update(name="Probation Sick Leave")
    LeaveType.objects.filter(name="Probation Leave (PL)").update(
        name="Probation Sick Leave (PSL)"
    )


def rename_back(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    LeaveType.objects.filter(name="Probation Sick Leave").update(name="Probation Leave")
    LeaveType.objects.filter(name="Probation Sick Leave (PSL)").update(
        name="Probation Leave (PL)"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0011_add_probation_casual_leave"),
    ]

    operations = [
        migrations.RunPython(rename_probation_leave, rename_back),
    ]
