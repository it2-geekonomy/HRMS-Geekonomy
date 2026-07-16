import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0001_initial"),
        ("leave", "0007_add_comp_off_leave"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompOffRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Is active"),
                ),
                ("start_date", models.DateField(verbose_name="Start Date")),
                ("end_date", models.DateField(verbose_name="End Date")),
                (
                    "start_date_breakdown",
                    models.CharField(
                        choices=[
                            ("full_day", "Full Day"),
                            ("first_half", "First Half"),
                            ("second_half", "Second Half"),
                        ],
                        default="full_day",
                        max_length=30,
                        verbose_name="Breakdown",
                    ),
                ),
                (
                    "end_date_breakdown",
                    models.CharField(
                        choices=[
                            ("full_day", "Full Day"),
                            ("first_half", "First Half"),
                            ("second_half", "Second Half"),
                        ],
                        default="full_day",
                        max_length=30,
                        verbose_name="End Date Breakdown",
                    ),
                ),
                (
                    "requested_days",
                    models.FloatField(
                        blank=True, null=True, verbose_name="Requested Days"
                    ),
                ),
                (
                    "approved_days",
                    models.FloatField(
                        blank=True, null=True, verbose_name="Approved Days"
                    ),
                ),
                (
                    "description",
                    models.TextField(max_length=255, verbose_name="Description"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("requested", "Requested"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="requested",
                        max_length=30,
                        verbose_name="Status",
                    ),
                ),
                (
                    "reject_reason",
                    models.TextField(
                        blank=True, max_length=255, verbose_name="Reject Reason"
                    ),
                ),
                (
                    "requested_date",
                    models.DateField(
                        default=django.utils.timezone.now,
                        verbose_name="Requested Date",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name="Created At"
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="comp_off_requests_created",
                        to="employee.employee",
                        verbose_name="Created By",
                    ),
                ),
                (
                    "employee_id",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="employee.employee",
                        verbose_name="Employee",
                    ),
                ),
            ],
            options={
                "verbose_name": "Comp-Off Request",
                "verbose_name_plural": "Comp-Off Requests",
                "ordering": ["-id"],
            },
        ),
    ]
