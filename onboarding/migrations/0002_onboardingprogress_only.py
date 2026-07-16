# Historical workaround for DBs that already had other onboarding tables.
# OnboardingProgress is already created in 0001 — keep this as a no-op for fresh installs.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("onboarding", "0001_add_onboarding_progress"),
    ]

    operations = []
