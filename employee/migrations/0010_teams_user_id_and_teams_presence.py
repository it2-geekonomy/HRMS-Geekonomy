# Generated manually for Teams Online/Offline presence

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0009_remove_employee_team_ids_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamsPresence",
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
                    "teams_user_id",
                    models.CharField(db_index=True, max_length=64, unique=True),
                ),
                (
                    "presence",
                    models.CharField(
                        choices=[("active", "Active"), ("away", "Away")],
                        default="away",
                        max_length=20,
                    ),
                ),
                (
                    "availability",
                    models.CharField(blank=True, default="", max_length=50),
                ),
                (
                    "activity",
                    models.CharField(blank=True, default="", max_length=50),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Teams Presence",
                "verbose_name_plural": "Teams Presences",
            },
        ),
        migrations.AddField(
            model_name="employee",
            name="teams_user_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Microsoft Entra object ID for Teams presence (Online/Offline on employee view).",
                max_length=64,
                null=True,
                unique=True,
                verbose_name="Teams User ID",
            ),
        ),
    ]
