from django.db import migrations


def rename_legacy_leaves_to_old(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    for lt in LeaveType.objects.all():
        is_new_monthly = (
            lt.reset_based == "monthly"
            and lt.carryforward_type == "no carryforward"
            and round(float(lt.total_days or 0), 2) == 1.0
            and "probation" not in (lt.name or "").lower()
            and "intern" not in (lt.name or "").lower()
            and not getattr(lt, "is_compensatory_leave", False)
            and getattr(lt, "is_active", False)
        )
        if not is_new_monthly:
            name_lower = (lt.name or "").strip().lower()
            if "casual" in name_lower and "probation" not in name_lower:
                lt.name = "Casual Leave (old)"
                lt.save(update_fields=["name"])
            elif "sick" in name_lower and "probation" not in name_lower and "intern" not in name_lower:
                lt.name = "Sick Leave (old)"
                lt.save(update_fields=["name"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0013_switch_to_monthly_casual_and_sick_leaves"),
    ]

    operations = [
        migrations.RunPython(
            rename_legacy_leaves_to_old,
            noop,
        ),
    ]
