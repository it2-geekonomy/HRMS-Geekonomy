# Generated manually for AttendanceRequestLog

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0002_initial"),
        ("employee", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AttendanceRequestLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True, verbose_name="Created At")),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("requested", "Requested"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("edited", "Edited"),
                        ],
                        max_length=20,
                        verbose_name="Action",
                    ),
                ),
                ("performed_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Performed at")),
                (
                    "description",
                    models.TextField(blank=True, help_text="Optional context, e.g. attendance date or request type", verbose_name="Description"),
                ),
                (
                    "attendance_id",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="request_logs",
                        to="attendance.attendance",
                        verbose_name="Attendance",
                    ),
                ),
                (
                    "employee_id",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_request_logs",
                        to="employee.employee",
                        verbose_name="Employee",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="attendance_request_actions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Performed by",
                    ),
                ),
            ],
            options={
                "ordering": ["-performed_at"],
                "verbose_name": "Attendance request log",
                "verbose_name_plural": "Attendance request logs",
            },
        ),
    ]
