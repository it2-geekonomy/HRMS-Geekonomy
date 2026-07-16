# Migration: clear all old onboarding checklist logs so only new 17-step logs are kept

from django.db import migrations


def clear_checklist_logs(apps, schema_editor):
    OnboardingChecklistLog = apps.get_model("onboarding", "OnboardingChecklistLog")
    OnboardingChecklistLog.objects.all().delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("onboarding", "0004_replace_5_steps_with_17"),
    ]

    operations = [
        migrations.RunPython(clear_checklist_logs, noop_reverse),
    ]
