from django.db import migrations


def create_comp_off_leave(apps, schema_editor):
    """
    Create 'Comp Off Leave' with:
    - Paid
    - Full‑day quota: 5 days per year (no carryforward logic here)
    - Limit: 1 day per request period (month) via count/period_in
    Admin will assign this leave type to employees manually.
    """
    LeaveType = apps.get_model("leave", "LeaveType")

    # Use case-insensitive name check so we don't create duplicates
    if LeaveType.objects.filter(name__iexact="Comp Off Leave").exists():
        return

    LeaveType.objects.create(
        name="Comp Off Leave",
        payment="paid",
        limit_leave=True,
        # Per-request period limit: 1 day per month
        count=1,
        period_in="month",
        # Annual entitlement: 5 days, reset yearly on Jan 1
        total_days=5,
        reset=True,
        reset_based="yearly",
        reset_month="1",
        reset_day="1",
        carryforward_type="no carryforward",
        carryforward_max=None,
        require_approval="yes",
        require_attachment="no",
    )


def delete_comp_off_leave(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    LeaveType.objects.filter(name__iexact="Comp Off Leave").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0003_add_monthly_salary_data"),
    ]

    operations = [
        migrations.RunPython(create_comp_off_leave, delete_comp_off_leave),
    ]

