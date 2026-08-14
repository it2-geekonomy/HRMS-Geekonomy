# Add from/to time fields to Closers Fellowship comments

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recruitment", "0010_closers_fellowship_application_comment"),
    ]

    operations = [
        migrations.AddField(
            model_name="closersfellowshipapplicationcomment",
            name="time_from",
            field=models.TimeField(default="09:00", verbose_name="From Time"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="closersfellowshipapplicationcomment",
            name="time_to",
            field=models.TimeField(default="10:00", verbose_name="To Time"),
            preserve_default=False,
        ),
    ]
