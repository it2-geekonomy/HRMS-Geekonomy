# Generated manually for DocumentTemplate

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True, verbose_name="Created At")),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                ("name", models.CharField(max_length=200, verbose_name="Template Name")),
                (
                    "template_type",
                    models.CharField(
                        choices=[
                            ("employment_agreement", "Employment Agreement"),
                            ("appointment_letter", "Appointment Letter"),
                            ("other", "Other"),
                        ],
                        default="employment_agreement",
                        max_length=50,
                        verbose_name="Template Type",
                    ),
                ),
                (
                    "body",
                    models.TextField(
                        help_text="Use {{ variable }} for placeholders (e.g. {{ employee_name }}, {{ company_name }}).",
                        verbose_name="Template Content",
                    ),
                ),
                ("signatory_name", models.CharField(blank=True, max_length=200, null=True, verbose_name="Signatory Name")),
                (
                    "signatory_designation",
                    models.CharField(blank=True, max_length=200, null=True, verbose_name="Signatory Designation"),
                ),
                (
                    "company_id",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="base.company",
                        verbose_name="Company",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created By",
                    ),
                ),
                (
                    "modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Modified By",
                    ),
                ),
            ],
            options={
                "verbose_name": "Document Template",
                "verbose_name_plural": "Document Templates",
            },
        ),
    ]
