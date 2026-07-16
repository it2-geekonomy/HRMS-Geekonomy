from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recruitment", "0005_historicalrejectedcandidate_email_sent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="recruitmentsurvey",
            name="allow_other",
            field=models.BooleanField(
                default=False,
                help_text="Adds an Other choice with a text field for applicants.",
                verbose_name="Allow Other option",
            ),
        ),
    ]
