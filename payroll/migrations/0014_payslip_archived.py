from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0013_expense_paid_by_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="payslip",
            name="archived",
            field=models.BooleanField(
                default=False,
                help_text="Archived payslips are hidden from the default list.",
                verbose_name="Archived",
            ),
        ),
    ]
