# Add arrears_amount and arrears_description to MonthlySalaryData

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0003_add_pt_and_final_salary"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlysalarydata",
            name="arrears_amount",
            field=models.FloatField(
                blank=True,
                default=0,
                help_text="Amount added to final salary (e.g. one-time arrears)",
                verbose_name="Arrears Amount",
            ),
        ),
        migrations.AddField(
            model_name="monthlysalarydata",
            name="arrears_description",
            field=models.CharField(
                blank=True,
                default="",
                max_length=255,
                verbose_name="Arrears Description",
            ),
        ),
    ]
