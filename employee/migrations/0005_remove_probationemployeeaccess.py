# Generated manually - remove ProbationEmployeeAccess table (reverted feature)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0004_historicalemployeeworkinformation_probation_action"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS employee_probationemployeeaccess;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
