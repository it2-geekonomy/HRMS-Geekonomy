# Historical workaround — SalaryDataArrearsLog already gets an auto id in 0005.
# Keep as a no-op so fresh installs do not hit DuplicateColumn on "id".

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0005_salarydataarrearslog"),
    ]

    operations = []
