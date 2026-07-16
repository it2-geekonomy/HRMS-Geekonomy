# Generated manually: store full HTML so attendance approval emails can expose
# "approved by …" in EmailLog.body (was truncated at 255 chars).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0005_documenttemplate_template_file"),
    ]

    operations = [
        migrations.AlterField(
            model_name="emaillog",
            name="body",
            field=models.TextField(blank=True),
        ),
    ]
