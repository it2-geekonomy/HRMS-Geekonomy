from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


def forwards_convert_late_hdp_to_lh(apps, schema_editor):
    WorkRecords = apps.get_model("attendance", "WorkRecords")
    # Existing late-login rows were stored as HDP with a Late login message.
    WorkRecords.objects.filter(
        work_record_type="HDP",
        date__gte="2026-11-02",
        message__istartswith="Late login",
    ).update(work_record_type="LH", day_percentage=0.5)


def backwards_convert_lh_to_hdp(apps, schema_editor):
    WorkRecords = apps.get_model("attendance", "WorkRecords")
    WorkRecords.objects.filter(work_record_type="LH").update(work_record_type="HDP")


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0006_merge_0005_attendancerequestlog"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workrecords",
            name="work_record_type",
            field=models.CharField(
                choices=[
                    ("FDP", _("Present")),
                    ("HDP", _("Half Day Present")),
                    ("LH", _("Late Login (Half Day)")),
                    ("SP", _("Short Presence")),
                    ("ABS", _("Absent")),
                    ("MP", _("Missing Punch")),
                    ("HD", _("Holiday/Company Leave")),
                    ("L", _("Leave")),
                    ("CONF", _("Conflict")),
                    ("DFT", _("Draft")),
                ],
                max_length=10,
                null=True,
            ),
        ),
        migrations.RunPython(forwards_convert_late_hdp_to_lh, backwards_convert_lh_to_hdp),
    ]
