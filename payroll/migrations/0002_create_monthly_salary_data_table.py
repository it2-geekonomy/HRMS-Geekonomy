# Historical workaround for DBs that already had other payroll tables.
# MonthlySalaryData is already created in 0001 — keep this as a no-op for fresh installs.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0001_add_monthly_salary_data"),
    ]

    operations = []
