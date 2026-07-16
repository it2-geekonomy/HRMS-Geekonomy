"""
Probation reminder: send email to reporting manager 7 days before
an employee's Probation Will Complete Date.
"""

from datetime import timedelta

from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from dateutil.relativedelta import relativedelta

from employee.models import Employee, EmployeeWorkInformation


def send_probation_reminder_emails():
    """
    Find employees whose Probation Will Complete Date is exactly 7 days from today.
    Send a reminder email to each employee's reporting manager.
    """
    today = timezone.now().date()
    target_complete_date = today + timedelta(days=7)
    # Probation completes at date_joining + 3 months; we want that date = target_complete_date
    target_joining_date = target_complete_date - relativedelta(months=3)

    full_time_q = (
        Q(employee_type_id__employee_type__iexact="Full Time")
        | Q(employee_type_id__employee_type__iexact="Fulltime")
        | Q(employee_type_id__employee_type__iexact="Full-time")
        | Q(employee_type_id__isnull=True)
    )
    no_intern = ~Q(employee_type_id__employee_type__icontains="Intern")

    work_infos = (
        EmployeeWorkInformation.objects.filter(
            employee_id__is_active=True,
            date_joining=target_joining_date,
            probation_action__isnull=True,
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

    date_str = target_complete_date.strftime("%d/%m/%Y")
    for work_info in work_infos:
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
        email = EmailMessage(
            subject=subject,
            body=body,
            to=[to_email],
        )
        try:
            email.send(fail_silently=False)
        except Exception:
            pass  # fail silently in scheduler to avoid breaking other jobs
