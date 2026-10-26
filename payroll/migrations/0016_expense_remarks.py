from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0015_historicalpayslip_archived'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='remarks',
            field=models.TextField(blank=True, default='', null=True, verbose_name='Remarks'),
        ),
    ]
