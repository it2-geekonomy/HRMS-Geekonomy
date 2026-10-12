# Generated manually — store probation start date (e.g. for converted interns)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0013_employeeworkinformation_basic_salary_decimal"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeworkinformation",
            name="probation_start_date",
            field=models.DateField(
                blank=True,
                help_text=(
                    "Date probation begins (e.g. for converted interns). "
                    "If blank, defaults to joining date."
                ),
                null=True,
                verbose_name="Probation Start Date",
            ),
        ),
        migrations.AddField(
            model_name="historicalemployeeworkinformation",
            name="probation_start_date",
            field=models.DateField(
                blank=True,
                help_text=(
                    "Date probation begins (e.g. for converted interns). "
                    "If blank, defaults to joining date."
                ),
                null=True,
                verbose_name="Probation Start Date",
            ),
        ),
    ]
