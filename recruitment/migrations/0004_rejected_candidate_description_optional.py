# Generated manually - make RejectedCandidate.description optional

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recruitment", "0003_add_candidate_archived"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rejectedcandidate",
            name="description",
            field=models.TextField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="historicalrejectedcandidate",
            name="description",
            field=models.TextField(blank=True, max_length=255, null=True),
        ),
    ]
