# Add optional Blood group field to Employee (Personal Info)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0005_remove_probationemployeeaccess"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="blood_group",
            field=models.CharField(
                blank=True,
                max_length=10,
                null=True,
                verbose_name="Blood group",
            ),
        ),
    ]
