# Migration to create only payroll_monthlysalarydata table (other payroll tables already exist)

from django.db import migrations


def create_monthly_salary_data_table(apps, schema_editor):
    """Create the payroll_monthlysalarydata table."""
    Model = apps.get_model("payroll", "MonthlySalaryData")
    schema_editor.create_model(Model)


def drop_monthly_salary_data_table(apps, schema_editor):
    """Drop the payroll_monthlysalarydata table (reverse)."""
    Model = apps.get_model("payroll", "MonthlySalaryData")
    schema_editor.delete_model(Model)


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0001_add_monthly_salary_data"),
    ]

    operations = [
        migrations.RunPython(create_monthly_salary_data_table, drop_monthly_salary_data_table),
    ]
