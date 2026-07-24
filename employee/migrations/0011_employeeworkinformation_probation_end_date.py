# Generated manually — store extended probation end date

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0010_teams_user_id_and_teams_presence"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeworkinformation",
            name="probation_end_date",
            field=models.DateField(
                blank=True,
                help_text=(
                    "Optional override. Default is joining date + 3 months. "
                    "Updated when probation is extended."
                ),
                null=True,
                verbose_name="Probation Will Complete Date",
            ),
        ),
        migrations.AddField(
            model_name="historicalemployeeworkinformation",
            name="probation_end_date",
            field=models.DateField(
                blank=True,
                help_text=(
                    "Optional override. Default is joining date + 3 months. "
                    "Updated when probation is extended."
                ),
                null=True,
                verbose_name="Probation Will Complete Date",
            ),
        ),
    ]
