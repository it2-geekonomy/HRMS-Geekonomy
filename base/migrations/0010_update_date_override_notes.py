from django.db import migrations, models


NOTE_MAP = {
    "Migrated from temporary WO override": "Special Week Off",
    "Migrated from temporary force-working override": "Marked as Working Day",
}


def update_notes(apps, schema_editor):
    CompanyLeaveDateOverride = apps.get_model("base", "CompanyLeaveDateOverride")
    for old_note, new_note in NOTE_MAP.items():
        CompanyLeaveDateOverride.objects.filter(note=old_note).update(note=new_note)


def revert_notes(apps, schema_editor):
    CompanyLeaveDateOverride = apps.get_model("base", "CompanyLeaveDateOverride")
    for old_note, new_note in NOTE_MAP.items():
        CompanyLeaveDateOverride.objects.filter(note=new_note).update(note=old_note)


class Migration(migrations.Migration):

    dependencies = [
        ("base", "0009_companyleavedateoverride"),
    ]

    operations = [
        migrations.RunPython(update_notes, revert_notes),
        migrations.AlterField(
            model_name="companyleavedateoverride",
            name="override_type",
            field=models.CharField(
                choices=[
                    ("week_off", "Week Off (WO)"),
                    ("working", "Working Day"),
                ],
                default="week_off",
                max_length=20,
                verbose_name="Type",
            ),
        ),
        migrations.AlterField(
            model_name="companyleavedateoverride",
            name="note",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional reason, e.g. Festival holiday.",
                max_length=255,
                verbose_name="Note",
            ),
        ),
    ]
