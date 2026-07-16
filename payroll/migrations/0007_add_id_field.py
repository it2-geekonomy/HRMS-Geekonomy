# Add explicit id field to SalaryDataArrearsLog

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0005_salarydataarrearslog"),
    ]

    operations = [
        migrations.AddField(
            model_name="salarydataarrearslog",
            name="id",
            field=models.AutoField(primary_key=True, serialize=False),
        ),
    ]
