import datetime

from django.db import migrations, models
import django.db.models.deletion


def seed_existing_overrides(apps, schema_editor):
    CompanyLeaveDateOverride = apps.get_model("base", "CompanyLeaveDateOverride")
    seeds = [
        (datetime.date(2026, 5, 23), "week_off", "Migrated from temporary WO override"),
        (datetime.date(2026, 5, 30), "working", "Migrated from temporary force-working override"),
        (datetime.date(2026, 7, 18), "week_off", "Migrated from temporary WO override"),
        (datetime.date(2026, 7, 25), "week_off", "Migrated from temporary WO override"),
        (datetime.date(2026, 9, 12), "week_off", "Migrated from temporary WO override"),
    ]
    for day, override_type, note in seeds:
        CompanyLeaveDateOverride.objects.get_or_create(
            date=day,
            defaults={"override_type": override_type, "note": note},
        )


def unseed_existing_overrides(apps, schema_editor):
    CompanyLeaveDateOverride = apps.get_model("base", "CompanyLeaveDateOverride")
    CompanyLeaveDateOverride.objects.filter(
        date__in=[
            datetime.date(2026, 5, 23),
            datetime.date(2026, 5, 30),
            datetime.date(2026, 7, 18),
            datetime.date(2026, 7, 25),
            datetime.date(2026, 9, 12),
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0008_alter_slackconfiguration_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyLeaveDateOverride",
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
                    models.DateTimeField(auto_now_add=True, null=True, verbose_name="Created At"),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Is Active"),
                ),
                ("date", models.DateField(unique=True, verbose_name="Date")),
                (
                    "override_type",
                    models.CharField(
                        choices=[
                            ("week_off", "Week Off (WO)"),
                            ("working", "Force Working Day"),
                        ],
                        default="week_off",
                        max_length=20,
                        verbose_name="Override Type",
                    ),
                ),
                (
                    "note",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional reason, e.g. Festival / special holiday WO.",
                        max_length=255,
                        verbose_name="Note",
                    ),
                ),
                (
                    "company_id",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
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
                        related_name="%(class)s_created",
                        to="auth.user",
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
                        related_name="%(class)s_modified",
                        to="auth.user",
                        verbose_name="Modified By",
                    ),
                ),
            ],
            options={
                "verbose_name": "Company Leave Date Override",
                "verbose_name_plural": "Company Leave Date Overrides",
                "ordering": ["-date"],
            },
        ),
        migrations.RunPython(seed_existing_overrides, unseed_existing_overrides),
    ]
