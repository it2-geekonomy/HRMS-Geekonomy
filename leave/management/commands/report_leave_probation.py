"""
Report employees by probation / intern status and leave balances.

- Interns: Intern Sick Leave (ISL) 1 per 3 months, no CL/EL/SL. Converted → probation.
- Probation (full-time, first 3 months): LOP only.
- Not in probation: EL/CL/SL (from Jan 1 2026).
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from employee.models import Employee, EmployeeWorkInformation
from leave.models import LeaveType, AvailableLeave
from leave.intern_leave import is_intern, intern_isl_balance

EL_EPOCH_DATE = date(2026, 1, 1)


class Command(BaseCommand):
    help = "Report employees in probation vs not, with leave balances (EL/CL/SL)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            action="store_true",
            help="Output as CSV (employee, joining_date, probation_end, status, EL, CL, SL)",
        )

    def handle(self, *args, **options):
        today = timezone.now().date()
        as_csv = options["csv"]

        try:
            el_type = LeaveType.objects.get(name="Earned Leave (EL)")
            cl_type = LeaveType.objects.get(name="Casual Leave (CL)")
            sl_type = LeaveType.objects.get(name="Sick Leave (SL)")
        except LeaveType.DoesNotExist as e:
            self.stdout.write(self.style.ERROR(f"Leave type not found: {e}"))
            return

        work_infos = (
            EmployeeWorkInformation.objects.filter(date_joining__isnull=False)
            .select_related("employee_id", "employee_type_id")
            .order_by("date_joining")
        )

        interns = []
        in_probation = []
        not_in_probation = []

        for wi in work_infos:
            emp = wi.employee_id
            jd = wi.date_joining
            if is_intern(emp):
                interns.append((emp, jd))
                continue
            prob_end = jd + relativedelta(months=3)
            if today < prob_end:
                in_probation.append((emp, jd, prob_end))
            else:
                not_in_probation.append((emp, jd, prob_end))

        # Fetch leave balances for non-probation
        emp_ids = [e[0].id for e in not_in_probation]
        el_map = {}
        cl_map = {}
        sl_map = {}
        for al in AvailableLeave.objects.filter(
            employee_id__in=emp_ids,
            leave_type_id__in=[el_type, cl_type, sl_type],
        ).select_related("leave_type_id"):
            eid = al.employee_id_id
            if al.leave_type_id_id == el_type.id:
                el_map[eid] = al
            elif al.leave_type_id_id == cl_type.id:
                cl_map[eid] = al
            elif al.leave_type_id_id == sl_type.id:
                sl_map[eid] = al

        def el_cl_sl(emp):
            el = el_map.get(emp.id)
            cl = cl_map.get(emp.id)
            sl = sl_map.get(emp.id)
            return (
                (el.available_days + el.carryforward_days) if el else 0,
                (cl.available_days + cl.carryforward_days) if cl else 0,
                (sl.available_days + sl.carryforward_days) if sl else 0,
            )

        if as_csv:
            self.stdout.write(
                "employee_id,employee_name,badge_id,joining_date,probation_end,status,EL,CL,SL"
            )
            for emp, jd in interns:
                isl_b, _, _ = intern_isl_balance(emp)
                name = (emp.get_full_name() or "").replace('"', '""')
                bid = (getattr(emp, "badge_id", None) or "").replace('"', '""')
                self.stdout.write(
                    f'{emp.id},"{name}","{bid}",{jd},,INTERN,0,0,{isl_b:.2f}'
                )
            for emp, jd, pe in in_probation:
                name = (emp.get_full_name() or "").replace('"', '""')
                bid = (getattr(emp, "badge_id", None) or "").replace('"', '""')
                self.stdout.write(
                    f'{emp.id},"{name}","{bid}",{jd},{pe},IN_PROBATION,0,0,0'
                )
            for emp, jd, pe in not_in_probation:
                ev, cv, sv = el_cl_sl(emp)
                name = (emp.get_full_name() or "").replace('"', '""')
                bid = (getattr(emp, "badge_id", None) or "").replace('"', '""')
                self.stdout.write(
                    f'{emp.id},"{name}","{bid}",{jd},{pe},NOT_IN_PROBATION,{ev:.2f},{cv:.2f},{sv:.2f}'
                )
            return

        self.stdout.write(self.style.SUCCESS(f"Report as of {today}"))
        self.stdout.write("")

        self.stdout.write(self.style.WARNING("=== INTERN (ISL 1 per 3 months, no CL/EL/SL) ==="))
        self.stdout.write("")
        if not interns:
            self.stdout.write("  (none)")
        else:
            for emp, jd in interns:
                isl_b, block_start, block_end = intern_isl_balance(emp)
                bid = getattr(emp, "badge_id", "") or ""
                block = f"block ~{block_start} to {block_end}" if block_start and block_end else ""
                self.stdout.write(
                    f"  {emp.get_full_name()} (id={emp.id}, {bid})\n"
                    f"    Joining: {jd}  |  ISL: {isl_b:.2f} (1 per 3 months, {block})"
                )
        self.stdout.write("")

        self.stdout.write(self.style.WARNING("=== IN PROBATION (no EL/CL/SL, LOP only) ==="))
        self.stdout.write("")
        if not in_probation:
            self.stdout.write("  (none)")
        else:
            for emp, jd, pe in in_probation:
                bid = getattr(emp, "badge_id", "") or ""
                self.stdout.write(
                    f"  {emp.get_full_name()} (id={emp.id}, {bid})\n"
                    f"    Joining: {jd}  |  Probation ends: {pe}"
                )
        self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("=== NOT IN PROBATION (EL/CL/SL active) ==="))
        self.stdout.write("")
        if not not_in_probation:
            self.stdout.write("  (none)")
        else:
            for emp, jd, pe in not_in_probation:
                ev, cv, sv = el_cl_sl(emp)
                bid = getattr(emp, "badge_id", "") or ""
                self.stdout.write(
                    f"  {emp.get_full_name()} (id={emp.id}, {bid})\n"
                    f"    Joining: {jd}  |  Probation ended: {pe}\n"
                    f"    EL: {ev:.2f}  |  CL: {cv:.2f}  |  SL: {sv:.2f}"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Summary: {len(interns)} intern(s), {len(in_probation)} in probation, {len(not_in_probation)} not in probation"
            )
        )
