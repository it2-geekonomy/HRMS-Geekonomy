# Archive salary data by month: hidden from default list, shown when filtering by month/year

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0005_salarydataarrearslog"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlysalarydata",
            name="archived",
            field=models.BooleanField(
                default=False,
                help_text="Archived data is hidden from the default list and only shown when filtering by month/year.",
                verbose_name="Archived",
            ),
        ),
    ]
