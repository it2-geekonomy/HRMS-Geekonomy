from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0014_payslip_archived"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalpayslip",
            name="archived",
            field=models.BooleanField(
                default=False,
                help_text="Archived payslips are hidden from the default list.",
                verbose_name="Archived",
            ),
        ),
    ]
