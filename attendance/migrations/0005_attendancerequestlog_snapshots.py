from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0004_attendancerequestlog_created_by_modified_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancerequestlog",
            name="requested_data_snapshot",
            field=models.JSONField(
                blank=True,
                help_text="Snapshot of Attendance.requested_data at the time of this action (requested/edited/approved/rejected).",
                null=True,
                verbose_name="Requested data snapshot",
            ),
        ),
        migrations.AddField(
            model_name="attendancerequestlog",
            name="attendance_snapshot",
            field=models.JSONField(
                blank=True,
                help_text="Snapshot of Attendance.serialize() at the time of this action (e.g. approved values).",
                null=True,
                verbose_name="Attendance snapshot",
            ),
        ),
    ]

