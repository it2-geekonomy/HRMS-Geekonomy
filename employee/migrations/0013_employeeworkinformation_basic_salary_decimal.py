# Generated manually for Basic Salary decimal support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0012_employee_pan_number"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeeworkinformation",
            name="basic_salary",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=0,
                max_digits=12,
                null=True,
                verbose_name="Basic Salary",
            ),
        ),
        migrations.AlterField(
            model_name="historicalemployeeworkinformation",
            name="basic_salary",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=0,
                max_digits=12,
                null=True,
                verbose_name="Basic Salary",
            ),
        ),
    ]
