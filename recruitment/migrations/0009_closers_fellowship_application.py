# Generated manually for Closers Fellowship website applications

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import recruitment.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("recruitment", "0008_add_recruitment_survey_mandatory_column"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClosersFellowshipApplication",
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
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name="Created At"
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Is Active")),
                ("full_name", models.CharField(max_length=255, verbose_name="Full Name")),
                ("email", models.EmailField(max_length=254, verbose_name="Email")),
                (
                    "phone",
                    models.CharField(
                        blank=True,
                        max_length=50,
                        null=True,
                        validators=[recruitment.models.validate_mobile],
                        verbose_name="Phone / WhatsApp",
                    ),
                ),
                (
                    "seat",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        verbose_name="Which seat fits you?",
                    ),
                ),
                (
                    "linkedin_portfolio",
                    models.URLField(
                        blank=True,
                        max_length=500,
                        null=True,
                        verbose_name="LinkedIn or Portfolio",
                    ),
                ),
                (
                    "answer_q1",
                    models.TextField(
                        blank=True,
                        null=True,
                        verbose_name="Q1: Biggest deal closed",
                    ),
                ),
                (
                    "answer_q2",
                    models.TextField(
                        blank=True,
                        null=True,
                        verbose_name="Q2: Revenue number carried",
                    ),
                ),
                (
                    "answer_q3",
                    models.TextField(
                        blank=True,
                        null=True,
                        verbose_name="Q3: Fixed vs variable compensation",
                    ),
                ),
                (
                    "utm_campaign",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        verbose_name="Campaign",
                    ),
                ),
                (
                    "utm_content",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        verbose_name="Ad",
                    ),
                ),
                (
                    "utm_term",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        verbose_name="Adset",
                    ),
                ),
                (
                    "utm_source",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        verbose_name="UTM Source",
                    ),
                ),
                (
                    "utm_medium",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        verbose_name="UTM Medium",
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
                "verbose_name": "Closers Fellowship Application",
                "verbose_name_plural": "Closers Fellowship Applications",
                "ordering": ["-created_at"],
            },
        ),
    ]
