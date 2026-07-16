"""
Create the standard leave types. No employees are assigned; you assign them
via Leave → Assign Leave using the filters described in the docstring below.

Run: python manage.py create_standard_leave_types

Leave types created:
  1. Casual Leave – Paid       → Assign: Full Time + Confirmed; 1 day per month, carryforward to next (cap 12)
  2. Casual Leave – LOP        → Assign: All
  3. Sick Leave – Paid         → Assign: Full Time + Confirmed
  4. Sick Leave – LOP          → Assign: All
  5. Earned Leave – Paid       → Assign: Full Time + Confirmed
  6. Leave – LOP (Probation)   → Assign: Probation only
  7. Casual Leave – Intern     → Assign: Intern
  8. Sick Leave – Intern       → Assign: Intern
"""
from datetime import date

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.db import transaction

from leave.models import AvailableLeave, LeaveType

# When limit_leave=False we still need a DB value; use a high number.
UNLIMITED_DAYS = 9999

CONFIGS = [
    {
        # 1 day per month, accrual on 1st; unused carries to next month (cap 12)
        "name": "Casual Leave – Paid",
        "payment": "paid",
        "limit_leave": True,
        "total_days": 1,
        "reset": True,
        "reset_based": "monthly",
        "reset_month": "1",
        "reset_day": "1",
        "carryforward_type": "carryforward",
        "carryforward_max": 12,
        "require_approval": "yes",
        "require_attachment": "no",
    },
    {
        "name": "Casual Leave – LOP",
        "payment": "unpaid",
        "limit_leave": False,
        "total_days": UNLIMITED_DAYS,
        "reset": False,
        "reset_based": None,
        "reset_month": "",
        "reset_day": None,
        "carryforward_type": "no carryforward",
        "carryforward_max": None,
        "require_approval": "yes",
        "require_attachment": "no",
    },
    {
        # Up to 2 days without attachment; >2 days requires medical certificate (enforced in LeaveRequest.clean)
        "name": "Sick Leave – Paid",
        "payment": "paid",
        "limit_leave": True,
        "total_days": 7,
        "reset": True,
        "reset_based": "yearly",
        "reset_month": "1",
        "reset_day": "1",
        "carryforward_type": "no carryforward",
        "carryforward_max": None,
        "require_approval": "yes",
        "require_attachment": "no",
    },
    {
        "name": "Sick Leave – LOP",
        "payment": "unpaid",
        "limit_leave": False,
        "total_days": UNLIMITED_DAYS,
        "reset": False,
        "reset_based": None,
        "reset_month": "",
        "reset_day": None,
        "carryforward_type": "no carryforward",
        "carryforward_max": None,
        "require_approval": "yes",
        "require_attachment": "no",
    },
    {
        # 1.25/day per month (15/year), monthly accrual on 1st, cap 30, expire 3y from credit
        "name": "Earned Leave – Paid",
        "payment": "paid",
        "limit_leave": True,
        "total_days": 1.25,
        "reset": True,
        "reset_based": "monthly",
        "reset_month": "1",
        "reset_day": "1",
        "carryforward_type": "carryforward expire",
        "carryforward_max": 30,
        "carryforward_expire_in": 3,
        "carryforward_expire_period": "year",
        "require_approval": "yes",
        "require_attachment": "no",
    },
    {
        "name": "Leave – LOP (Probation)",
        "payment": "unpaid",
        "limit_leave": False,
        "total_days": UNLIMITED_DAYS,
        "reset": False,
        "reset_based": None,
        "reset_month": "",
        "reset_day": None,
        "carryforward_type": "no carryforward",
        "carryforward_max": None,
        "require_approval": "yes",
        "require_attachment": "no",
    },
    {
        "name": "Casual Leave – Intern",
        "payment": "paid",
        "limit_leave": True,
        "total_days": 1,
        "reset": True,
        "reset_based": "yearly",
        "reset_month": "1",
        "reset_day": "1",
        "carryforward_type": "no carryforward",
        "carryforward_max": None,
        "require_approval": "yes",
        "require_attachment": "no",
    },
    {
        "name": "Sick Leave – Intern",
        "payment": "paid",
        "limit_leave": True,
        "total_days": 1,
        "reset": True,
        "reset_based": "yearly",
        "reset_month": "1",
        "reset_day": "1",
        "carryforward_type": "no carryforward",
        "carryforward_max": None,
        "require_approval": "yes",
        "require_attachment": "no",
    },
]


class Command(BaseCommand):
    help = "Create standard leave types (no employee assignment). You assign via Leave → Assign Leave."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Do not ask for confirmation.",
        )

    def handle(self, *args, **options):
        no_input = options.get("no_input", False)

        # Rename existing "Unpaid" leave type names to "LOP" in the DB
        renames = [
            ("Casual Leave – Unpaid", "Casual Leave – LOP"),
            ("Sick Leave – Unpaid", "Sick Leave – LOP"),
            ("Leave – Unpaid (Probation)", "Leave – LOP (Probation)"),
        ]
        with transaction.atomic():
            for old_name, new_name in renames:
                updated = LeaveType.objects.filter(name=old_name).update(name=new_name)
                if updated:
                    self.stdout.write(self.style.SUCCESS(f"Renamed: {old_name} -> {new_name}"))

        # Sick Leave – Paid: require_attachment=no; >2 days requires medical certificate (enforced in LeaveRequest.clean)
        sl_upd = LeaveType.objects.filter(name="Sick Leave – Paid").update(require_attachment="no")
        if sl_upd:
            self.stdout.write(self.style.SUCCESS("Updated: Sick Leave – Paid (attachment only when >2 days, via validation)"))

        # Ensure Casual Leave – Paid has monthly 1 day, carryforward to next month (cap 12)
        cl_upd = LeaveType.objects.filter(name="Casual Leave – Paid").update(
            total_days=1,
            reset_based="monthly",
            reset_day="1",
            carryforward_type="carryforward",
            carryforward_max=12,
        )
        if cl_upd:
            self.stdout.write(self.style.SUCCESS("Updated: Casual Leave – Paid (1/month, carryforward cap 12)"))

        # Set reset_date to next 1st for existing CL AvailableLeaves
        cl_type = LeaveType.objects.filter(name="Casual Leave – Paid").first()
        if cl_type:
            today = date.today()
            next_1st = (today + relativedelta(months=1)).replace(day=1) if today.day != 1 else today
            n = 0
            for av in AvailableLeave.objects.filter(leave_type_id=cl_type):
                if av.reset_date is None or av.reset_date.day != 1:
                    av.reset_date = next_1st
                    av.save()
                    n += 1
            if n:
                self.stdout.write(self.style.SUCCESS(f"Set reset_date to {next_1st} for {n} Casual Leave – Paid assignment(s)."))

        # Recalculate CL Paid balances: start fresh — available_days=1 (current month), carryforward_days=0 (no carry from old system)
        if cl_type:
            recalc_n = 0
            for av in AvailableLeave.objects.filter(leave_type_id=cl_type):
                av.available_days = 1.0
                av.carryforward_days = 0.0
                av.save()
                recalc_n += 1
            if recalc_n:
                self.stdout.write(self.style.SUCCESS(f"Recalculated Casual Leave – Paid (1/mo, fresh start) for {recalc_n} assignment(s)."))

        # Ensure Earned Leave – Paid has monthly accrual (1.25/mo, cap 30, 3y expiry)
        el_upd = LeaveType.objects.filter(name="Earned Leave – Paid").update(
            total_days=1.25,
            reset_based="monthly",
            reset_day="1",
            carryforward_type="carryforward expire",
            carryforward_max=30,
            carryforward_expire_in=3,
            carryforward_expire_period="year",
            carryforward_expire_date=None,
        )
        if el_upd:
            self.stdout.write(self.style.SUCCESS("Updated: Earned Leave – Paid (1.25/mo, cap 30, 3y expiry)"))

        # Set reset_date to next 1st for existing EL AvailableLeaves so monthly accrual runs
        el_type = LeaveType.objects.filter(name="Earned Leave – Paid").first()
        if el_type:
            today = date.today()
            next_1st = (today + relativedelta(months=1)).replace(day=1) if today.day != 1 else today
            n = 0
            for av in AvailableLeave.objects.filter(leave_type_id=el_type):
                if av.reset_date is None or av.reset_date.day != 1:
                    av.reset_date = next_1st
                    av.save()
                    n += 1
            if n:
                self.stdout.write(self.style.SUCCESS(f"Set reset_date to {next_1st} for {n} Earned Leave assignment(s)."))

        # Recalculate EL balances: 1.25 per 1st of month since first 1st, cap 30, minus taken.
        # EL accrual starts Jan 1, 2026: anyone assigned before Feb 2026 gets Jan 1, 2026 as first 1st.
        EL_ACCRUAL_START = date(2026, 1, 1)
        if el_type:
            today = date.today()
            recalc_n = 0
            for av in AvailableLeave.objects.filter(leave_type_id=el_type).select_related("leave_type_id"):
                ad = av.assigned_date or today
                first_1st_candidate = ad.replace(day=1) if ad.day == 1 else (ad + relativedelta(months=1)).replace(day=1)
                first_1st = EL_ACCRUAL_START if ad < date(2026, 2, 1) else first_1st_candidate
                if first_1st > today:
                    months = 0
                else:
                    months = max(0, (today.year - first_1st.year) * 12 + (today.month - first_1st.month) + 1)
                accrued = min(months * 1.25, 30.0)
                taken = av.leave_taken()
                balance = max(0.0, accrued - taken)
                current = (av.available_days or 0) + (av.carryforward_days or 0)
                if abs(current - balance) > 0.001:
                    av.available_days = round(balance, 3)
                    av.carryforward_days = 0
                    av.save()
                    recalc_n += 1
            if recalc_n:
                self.stdout.write(self.style.SUCCESS(f"Recalculated EL balance (1.25/mo, cap 30) for {recalc_n} assignment(s)."))

        existing = {o.name for o in LeaveType.objects.all()}
        to_create = [c for c in CONFIGS if c["name"] not in existing]

        if not to_create:
            self.stdout.write(self.style.WARNING("All standard leave types already exist. Nothing to do."))
            return

        if not no_input:
            self.stdout.write("Will create:\n  " + "\n  ".join(c["name"] for c in to_create))
            confirm = input("Proceed? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write("Aborted.")
                return

        with transaction.atomic():
            for cfg in to_create:
                LeaveType.objects.create(**cfg)
                self.stdout.write(self.style.SUCCESS(f"Created: {cfg['name']}"))

        self.stdout.write(
            self.style.SUCCESS(
                "\nDone. Assign employees via Leave > Assign Leave using:\n"
                "  - Full Time + Confirmed: CL Paid, SL Paid, EL Paid\n"
                "  - In Probation Period = Yes: Leave - LOP (Probation)\n"
                "  - Employee Type = Intern: Casual Leave - Intern, Sick Leave - Intern\n"
                "  - All: Casual Leave - LOP, Sick Leave - LOP"
            )
        )
