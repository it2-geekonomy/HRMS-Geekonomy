from django.db import migrations


def update_comp_off_leave_policy(apps, schema_editor):
    """
    Comp Off Leave:
    - Balance comes only from approved comp-off requests (not a fixed monthly/yearly quota).
    - Can be used on any date within the year while balance remains.
    - Unused balance lapses on 1 January (no carryforward).
    """
    LeaveType = apps.get_model("leave", "LeaveType")
    qs = LeaveType.objects.filter(name__iexact="Comp Off Leave")
    qs.update(
        limit_leave=True,
        total_days=0,
        count=999,
        period_in="year",
        reset=True,
        reset_based="yearly",
        reset_month="1",
        reset_day="1",
        carryforward_type="no carryforward",
        carryforward_max=None,
    )


def revert_comp_off_leave_policy(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    qs = LeaveType.objects.filter(name__iexact="Comp Off Leave")
    qs.update(
        total_days=5,
        count=1,
        period_in="month",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0009_compoffrequest_modified_by"),
    ]

    operations = [
        migrations.RunPython(update_comp_off_leave_policy, revert_comp_off_leave_policy),
    ]
