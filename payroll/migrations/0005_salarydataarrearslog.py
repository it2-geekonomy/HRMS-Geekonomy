# Arrears log for Salary Data (who added/updated, amount, when)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0004_monthlysalarydata_arrears"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SalaryDataArrearsLog",
            fields=[
                (
                    "action",
                    models.CharField(
                        choices=[("added", "Added"), ("updated", "Updated")],
                        default="updated",
                        max_length=20,
                    ),
                ),
                ("amount", models.FloatField(default=0, verbose_name="Amount (₹)")),
                ("description", models.CharField(blank=True, default="", max_length=255, verbose_name="Description")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "salary_data",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="arrears_logs",
                        to="payroll.monthlysalarydata",
                        verbose_name="Salary Data",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="User",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Arrears Log",
                "verbose_name_plural": "Arrears Logs",
            },
        ),
    ]
