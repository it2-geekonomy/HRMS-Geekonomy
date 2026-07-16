# Migration that only creates onboarding_onboardingprogress table.
# Use this if onboarding other tables already exist and 0001 would fail.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("employee", "0002_add_slack_user_id_and_slack_presence"),
        ("onboarding", "0001_add_onboarding_progress"),
    ]

    operations = [
        migrations.CreateModel(
            name="OnboardingProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True, verbose_name="Created At")),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                ("step_1_employee_hired", models.BooleanField(default=True, verbose_name="Employee hired")),
                ("step_2_offer_letter_issued", models.BooleanField(default=False, verbose_name="Offer letter issued")),
                ("step_3_documents_collected", models.BooleanField(default=False, verbose_name="Documents collected")),
                ("step_4_account_setup", models.BooleanField(default=False, verbose_name="Account setup")),
                ("step_5_welcome_completed", models.BooleanField(default=False, verbose_name="Welcome completed")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name="Created By")),
                ("employee_id", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="onboarding_progress", to="employee.employee", verbose_name="Employee")),
                ("modified_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified_by", to=settings.AUTH_USER_MODEL, verbose_name="Modified By")),
            ],
            options={
                "verbose_name": "Onboarding Progress",
                "verbose_name_plural": "Onboarding Progress",
            },
        ),
    ]
