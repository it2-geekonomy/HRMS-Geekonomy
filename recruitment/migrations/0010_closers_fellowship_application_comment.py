# Closers Fellowship application comment log

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("recruitment", "0009_closers_fellowship_application"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClosersFellowshipApplicationComment",
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
                ("comment", models.TextField(verbose_name="Comment")),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="recruitment.closersfellowshipapplication",
                        verbose_name="Application",
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
                "verbose_name": "Closers Fellowship Comment",
                "verbose_name_plural": "Closers Fellowship Comments",
                "ordering": ["created_at"],
            },
        ),
    ]
