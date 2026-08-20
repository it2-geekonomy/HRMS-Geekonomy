from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("employee", "0011_employeeworkinformation_probation_end_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="pan_number",
            field=models.CharField(
                blank=True,
                help_text="Indian PAN format, e.g. ABCDE1234F",
                max_length=10,
                null=True,
                verbose_name="PAN Card Number",
            ),
        ),
    ]
