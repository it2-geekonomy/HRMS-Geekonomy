import calendar
import datetime as dt
import sys
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from dateutil.relativedelta import relativedelta


# Earned Leave accrual starts from this date (no credit before).
EL_EPOCH_DATE = date(2026, 1, 1)

# Leave type names that use monthly 1.25 accrual (any of these in DB).
EARNED_LEAVE_NAMES = ("Earned Leave", "Earned Leave (EL)", "Earned Leave – Paid")

# Casual Leave: monthly 1/day, carryforward cap 12 (any of these in DB).
CASUAL_LEAVE_NAMES = ("Casual Leave", "Casual Leave (CL)", "Casual Leave – Paid")

# Probation Leave & Interns Leave: 1 per month, no carryforward (include name variants after rename).
PROBATION_LEAVE_NAMES = ("Probation Leave", "Probation Leave (PL)")
INTERNS_LEAVE_NAMES = ("Interns Leave",)

COMP_OFF_LEAVE_NAMES = ("Comp Off Leave",)


def _is_comp_off_leave_type(leave_type):
    name = (leave_type.name or "").strip()
    if name in COMP_OFF_LEAVE_NAMES:
        return True
    return "comp off" in name.lower()


def leave_reset():
    from leave.models import LeaveType

    today = datetime.now()
    today_date = today.date()
    leave_types = LeaveType.objects.filter(reset=True)

    for leave_type in leave_types:
        available_leaves = leave_type.employee_available_leave.all()

        # Earned Leave: monthly accrual (1.25 on 1st of each month, cap at carryforward_max)
        is_el_accrual = (
            leave_type.name in EARNED_LEAVE_NAMES
            and leave_type.reset_based == "monthly"
        )
        # Casual Leave: monthly 1/day, carryforward cap 12
        is_cl_accrual = (
            leave_type.name in CASUAL_LEAVE_NAMES
            and leave_type.reset_based == "monthly"
            and round(float(leave_type.total_days or 0), 2) == 1.0
        )
        # Probation Leave & Interns Leave: 1 per month, no carryforward
        is_probation_accrual = (
            leave_type.name in PROBATION_LEAVE_NAMES
            and leave_type.reset_based == "monthly"
            and round(float(leave_type.total_days or 0), 2) == 1.0
        )
        is_interns_accrual = (
            leave_type.name in INTERNS_LEAVE_NAMES
            and leave_type.reset_based == "monthly"
            and round(float(leave_type.total_days or 0), 2) == 1.0
        )
        is_comp_off_yearly = (
            _is_comp_off_leave_type(leave_type)
            and leave_type.reset_based == "yearly"
            and leave_type.reset
        )
        accrual_amount = float(leave_type.total_days or 0)
        accrual_cap = leave_type.carryforward_max if leave_type.carryforward_max is not None else 9999
        # CL cap is typically 12
        cl_cap = 12 if is_cl_accrual else accrual_cap

        for available_leave in available_leaves:
            reset_date = available_leave.reset_date
            expired_date = available_leave.expired_date

            # Casual Leave: yearly wipe on 1 Jan — unused balance cleared, January accrual credited
            if is_cl_accrual and today_date.month == 1 and today_date.day == 1:
                available_leave.available_days = 1.0
                available_leave.carryforward_days = 0
                available_leave.reset_date = available_leave.set_reset_date(
                    assigned_date=today_date, available_leave=available_leave
                )
                available_leave.save()
                if expired_date and expired_date <= today_date:
                    new_expired_date = available_leave.set_expired_date(
                        available_leave=available_leave, assigned_date=today_date
                    )
                    available_leave.expired_date = new_expired_date
                    available_leave.save()
                continue

            # Comp Off Leave: yearly lapse on 1 Jan — unused balance cleared (no carryforward)
            if is_comp_off_yearly and today_date.month == 1 and today_date.day == 1:
                available_leave.available_days = 0
                available_leave.carryforward_days = 0
                available_leave.reset_date = available_leave.set_reset_date(
                    assigned_date=today_date, available_leave=available_leave
                )
                available_leave.save()
                if expired_date and expired_date <= today_date:
                    new_expired_date = available_leave.set_expired_date(
                        available_leave=available_leave, assigned_date=today_date
                    )
                    available_leave.expired_date = new_expired_date
                    available_leave.save()
                continue

            # On 1st of month: Earned Leave catch-up
            if (
                is_el_accrual
                and accrual_amount > 0
                and today_date >= EL_EPOCH_DATE
                and today_date.day == 1
                and reset_date is not None
                and reset_date <= today_date
            ):
                # First accrual 1st = max(reset_date, Jan 1 2026)
                first_1st = max(reset_date.replace(day=1), EL_EPOCH_DATE)
                months_to_accrue = (today_date.year - first_1st.year) * 12 + (today_date.month - first_1st.month) + 1
                months_to_accrue = max(0, months_to_accrue)
                if months_to_accrue > 0:
                    current = (available_leave.available_days or 0) + (available_leave.carryforward_days or 0)
                    add_days = accrual_amount * months_to_accrue
                    new_total = min(current + add_days, accrual_cap)
                    available_leave.available_days = round(new_total, 3)
                    available_leave.carryforward_days = 0
                    new_reset_date = available_leave.set_reset_date(
                        assigned_date=today_date, available_leave=available_leave
                    )
                    available_leave.reset_date = new_reset_date
                    available_leave.save()
            # On 1st of month: Probation Leave / Interns Leave (1 per month, no carryforward).
            # Add 1 for the new month but keep previous month's unused balance so employee can
            # still apply for the previous month (e.g. in Feb apply for Jan). Cap at 2 so we
            # don't accumulate indefinitely (at most: previous + current month).
            elif (
                (is_probation_accrual or is_interns_accrual)
                and today_date.day == 1
                and reset_date is not None
                and reset_date <= today_date
            ):
                current_total = (available_leave.available_days or 0) + (
                    available_leave.carryforward_days or 0
                )
                available_leave.available_days = min(current_total + 1.0, 2.0)
                available_leave.carryforward_days = 0
                new_reset_date = available_leave.set_reset_date(
                    assigned_date=today_date, available_leave=available_leave
                )
                available_leave.reset_date = new_reset_date
                available_leave.save()
            # On 1st of month: Casual Leave catch-up (add 1 per month from reset_date to today, cap 12)
            elif (
                is_cl_accrual
                and today_date.day == 1
                and reset_date is not None
                and reset_date <= today_date
            ):
                first_1st = reset_date.replace(day=1)
                months_to_accrue = (today_date.year - first_1st.year) * 12 + (today_date.month - first_1st.month) + 1
                months_to_accrue = max(0, months_to_accrue)
                if months_to_accrue > 0:
                    current = (available_leave.available_days or 0) + (available_leave.carryforward_days or 0)
                    add_days = 1.0 * months_to_accrue
                    new_total = min(current + add_days, cl_cap)
                    available_leave.available_days = round(new_total, 3)
                    available_leave.carryforward_days = 0
                    new_reset_date = available_leave.set_reset_date(
                        assigned_date=today_date, available_leave=available_leave
                    )
                    available_leave.reset_date = new_reset_date
                    available_leave.save()
            elif reset_date == today_date:
                if is_comp_off_yearly:
                    available_leave.available_days = 0
                    available_leave.carryforward_days = 0
                elif is_el_accrual and accrual_amount > 0 and today_date >= EL_EPOCH_DATE and today_date.day == 1:
                    # Exact match (1st of month): add 1.25 once, cap at max
                    current = (available_leave.available_days or 0) + (available_leave.carryforward_days or 0)
                    new_total = min(current + accrual_amount, accrual_cap)
                    available_leave.available_days = round(new_total, 3)
                    available_leave.carryforward_days = 0
                elif is_el_accrual and accrual_amount > 0:
                    pass
                elif is_cl_accrual and today_date.day == 1:
                    # Exact match (1st of month): add 1 once, cap at 12
                    current = (available_leave.available_days or 0) + (available_leave.carryforward_days or 0)
                    new_total = min(current + 1.0, cl_cap)
                    available_leave.available_days = round(new_total, 3)
                    available_leave.carryforward_days = 0
                elif not is_comp_off_yearly:
                    available_leave.update_carryforward()

                new_reset_date = available_leave.set_reset_date(
                    assigned_date=today_date, available_leave=available_leave
                )
                available_leave.reset_date = new_reset_date
                available_leave.save()

            if expired_date and expired_date <= today_date:
                new_expired_date = available_leave.set_expired_date(
                    available_leave=available_leave, assigned_date=today_date
                )
                available_leave.expired_date = new_expired_date
                available_leave.save()

        if (
            leave_type.carryforward_expire_date
            and leave_type.carryforward_expire_date <= today_date
        ):
            leave_type.carryforward_expire_date = leave_type.set_expired_date(
                today_date
            )
            leave_type.save()


if not any(
    cmd in sys.argv
    for cmd in ["makemigrations", "migrate", "compilemessages", "flush", "shell"]
):
    """
    Initializes and starts background tasks using APScheduler when the server is running.
    """
    scheduler = BackgroundScheduler()
    # Run leave reset every 5 minutes instead of 20 seconds to reduce load
    # misfire_grace_time allows job to run even if slightly delayed
    scheduler.add_job(
        leave_reset, 
        "interval", 
        minutes=5,
        misfire_grace_time=300,  # 5 minutes grace time
        id="leave_reset",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
