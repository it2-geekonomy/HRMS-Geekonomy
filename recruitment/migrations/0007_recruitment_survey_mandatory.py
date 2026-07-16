from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recruitment", "0006_recruitmentsurvey_allow_other"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="recruitment",
                    name="survey_mandatory",
                    field=models.BooleanField(
                        default=False,
                        help_text="Require candidates to complete the survey during application",
                        verbose_name="Survey Mandatory",
                    ),
                ),
            ],
        ),
    ]
