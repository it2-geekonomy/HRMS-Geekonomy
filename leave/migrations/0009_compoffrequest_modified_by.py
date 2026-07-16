import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("leave", "0008_compoffrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="compoffrequest",
            name="modified_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="compoffrequest_modified_by",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Modified By",
            ),
        ),
    ]
