from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0004_attendancerequestlog_created_by_modified_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancerequestlog",
            name="employee_request_note",
            field=models.TextField(
                blank=True,
                help_text="Reason or description the employee entered (snapshotted on approval).",
                verbose_name="Employee request note",
            ),
        ),
    ]
