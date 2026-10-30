"""
Probation reminders:
- Reporting manager: 7 days before an employee's Probation Will Complete Date.
- HR (settings.HR_EMAIL): 1 day before the Probation Will Complete Date.
"""

from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from dateutil.relativedelta import relativedelta

from employee.models import EmployeeWorkInformation

MANAGER_REMINDER_DAYS = 7
HR_REMINDER_DAYS = 1


def _probation_completing_on(target_complete_date):
    """Active full-time employees with no probation action whose probation completes on the date."""
    # Default probation completes at probation_start (or date_joining) + 3 months
    target_start_date = target_complete_date - relativedelta(months=3)

    full_time_q = (
        Q(employee_type_id__employee_type__iexact="Full Time")
        | Q(employee_type_id__employee_type__iexact="Fulltime")
        | Q(employee_type_id__employee_type__iexact="Full-time")
        | Q(employee_type_id__isnull=True)
    )
    no_intern = ~Q(employee_type_id__employee_type__icontains="Intern")

    return (
        EmployeeWorkInformation.objects.filter(
            employee_id__is_active=True,
            probation_action__isnull=True,
        )
        .filter(
            Q(probation_end_date=target_complete_date)
            | Q(probation_end_date__isnull=True, probation_start_date=target_start_date)
            | Q(
                probation_end_date__isnull=True,
                probation_start_date__isnull=True,
                date_joining=target_start_date,
            )
        )
        .filter(full_time_q)
        .filter(no_intern)
        .select_related(
            "employee_id",
            "reporting_manager_id",
            "reporting_manager_id__employee_user_id",
            "employee_type_id",
        )
    )


def _send(subject, body, to_email):
    try:
        EmailMessage(subject=subject, body=body, to=[to_email]).send(
            fail_silently=False
        )
    except Exception:
        pass  # fail silently in scheduler to avoid breaking other jobs


def send_manager_probation_reminders():
    """Email each reporting manager 7 days before their report's probation completes."""
    target_complete_date = timezone.now().date() + timedelta(days=MANAGER_REMINDER_DAYS)
    date_str = target_complete_date.strftime("%d/%m/%Y")

    for work_info in _probation_completing_on(target_complete_date):
        manager = work_info.reporting_manager_id
        if not manager:
            continue
        manager_user = getattr(manager, "employee_user_id", None)
        if not manager_user:
            continue
        to_email = getattr(manager_user, "email", None)
        if not to_email or not to_email.strip():
            continue
        employee_name = str(work_info.employee_id)
        subject = _("Probation reminder: %(name)s's probation will complete on %(date)s") % {
            "name": employee_name,
            "date": date_str,
        }
        body = _(
            "Hello,\n\n"
            "This is a reminder that %(name)s's probation will complete on %(date)s (7 days from today).\n\n"
            "As their reporting manager, please take necessary action before or on that date: Extend, Confirm, or Reject in the Probation Employees section (Employee > Probation Employees).\n\n"
            "Regards,\n"
            "HRMS"
        ) % {"name": employee_name, "date": date_str}
        _send(subject, body, to_email)


def send_hr_probation_reminders():
    """Email HR 1 day before an employee's probation completes."""
    to_email = (getattr(settings, "HR_EMAIL", "") or "").strip()
    if not to_email:
        return
    target_complete_date = timezone.now().date() + timedelta(days=HR_REMINDER_DAYS)
    date_str = target_complete_date.strftime("%d/%m/%Y")

    for work_info in _probation_completing_on(target_complete_date):
        employee_name = str(work_info.employee_id)
        manager_name = (
            str(work_info.reporting_manager_id)
            if work_info.reporting_manager_id
            else _("Not assigned")
        )
        subject = _("Probation reminder: %(name)s's probation will complete tomorrow (%(date)s)") % {
            "name": employee_name,
            "date": date_str,
        }
        body = _(
            "Hello HR,\n\n"
            "%(name)s's probation will complete tomorrow, %(date)s.\n"
            "Reporting manager: %(manager)s\n\n"
            "No action has been taken yet. Please follow up so it is Extended, Confirmed, or Rejected in the Probation Employees section (Employee > Probation Employees).\n\n"
            "Regards,\n"
            "HRMS"
        ) % {"name": employee_name, "date": date_str, "manager": manager_name}
        _send(subject, body, to_email)


def send_probation_reminder_emails():
    """Run all probation reminders (manager 7 days before, HR 1 day before)."""
    send_manager_probation_reminders()
    send_hr_probation_reminders()
