"""
Late / Early attendance notification emails to employees.
"""

import logging
from datetime import datetime
from email.mime.image import MIMEImage
from pathlib import Path
from threading import Thread

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from attendance.late_punch import punch_flag_for_clock_in
from attendance.models import Attendance
from base.backends import ConfiguredEmailBackend
from base.methods import filtersubordinates

logger = logging.getLogger(__name__)

LATE_PUNCH_MAIL_LOGO_CID = "late-punch-logo"

# Edit subject and body templates here (placeholders: {employee_name}, {attendance_date},
# {check_in_time}, {late_status}, {company_name}).
DEFAULT_MAIL_SUBJECT = "Late Arrival Notice – {attendance_date}"

DEFAULT_MAIL_BODY = """Dear {employee_name},

This is to inform you that our attendance records show you checked in at {check_in_time} on {attendance_date}.

{late_status}

As per company policy, the reporting time is 9:00 AM. We request you to plan your commute accordingly and ensure timely attendance on all working days.

If you have a valid reason for this delay, please reach out to your reporting manager or HR at the earliest.

Thank you for your cooperation.

Regards,
HR Team
{company_name}"""

LATE_STATUS_AMBER = (
    "Your check-in falls between 9:11 AM and 9:30 AM and has been noted as a late arrival."
)
LATE_STATUS_RED = (
    "Your check-in is from 9:31 AM onward and is recorded as a late arrival requiring attention."
)
LATE_STATUS_GENERIC = "This check-in is recorded as a late arrival."


def _logo_path():
    for name in ("geekonomy-logo-mail.png", "Geekonomy Logo (2).png"):
        path = Path(settings.BASE_DIR) / "static" / "images" / "ui" / name
        if path.is_file():
            return path
    return None


def _company_name(employee):
    try:
        if employee and getattr(employee, "get_company", None):
            return employee.get_company().company
    except Exception:
        pass
    return "Geekonomy Technology Private Limited"


def _format_check_in(attendance):
    clock_in = attendance.attendance_clock_in
    if not clock_in:
        return "N/A"
    return clock_in.strftime("%I:%M %p").lstrip("0")


def _late_status_message(attendance):
    flag = punch_flag_for_clock_in(attendance.attendance_clock_in)
    if flag == "amber":
        return LATE_STATUS_AMBER
    if flag == "red":
        return LATE_STATUS_RED
    return LATE_STATUS_GENERIC


def build_default_late_punch_mail_text(attendance):
    employee = attendance.employee_id
    attendance_date = attendance.attendance_date.strftime("%d-%m-%Y")
    placeholders = {
        "employee_name": employee.get_full_name(),
        "attendance_date": attendance_date,
        "check_in_time": _format_check_in(attendance),
        "late_status": _late_status_message(attendance),
        "company_name": _company_name(employee),
    }
    subject = DEFAULT_MAIL_SUBJECT.format(**placeholders)
    body = DEFAULT_MAIL_BODY.format(**placeholders)
    return subject, body


def can_send_late_punch_mail(request, attendance):
    if not request or not request.user.is_authenticated:
        return False
    if request.user.has_perm("attendance.view_attendancelatecomeearlyout"):
        return True
    qs = Attendance.objects.filter(id=attendance.id)
    return filtersubordinates(request, qs, "attendance.view_attendance").exists()


def _attach_logo(email):
    logo_path = _logo_path()
    if not logo_path:
        logger.warning("Late punch mail: logo file not found")
        return
    with open(logo_path, "rb") as logo_file:
        img = MIMEImage(logo_file.read(), _subtype="png")
    img.add_header("Content-ID", f"<{LATE_PUNCH_MAIL_LOGO_CID}>")
    img.add_header("Content-Disposition", "inline", filename="geekonomy-logo.png")
    email.attach(img)


def send_late_punch_mail_sync(request, attendance, subject, body):
    employee = attendance.employee_id
    to_email = employee.get_mail() if employee else None
    if not to_email:
        raise ValueError("Employee email is not configured.")

    host = request.get_host()
    protocol = "https" if request.is_secure() else "http"
    email_backend = ConfiguredEmailBackend()
    from_email = (
        email_backend.dynamic_from_email_with_display_name
        or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@hrms")
    )

    html_message = render_to_string(
        "base/mail_templates/late_punch_template.html",
        {
            "employee": employee,
            "attendance": attendance,
            "subject": subject,
            "body": body,
            "host": host,
            "protocol": protocol,
            "logo_cid": LATE_PUNCH_MAIL_LOGO_CID,
            "company_name": _company_name(employee),
            "current_year": datetime.now().year,
            "check_in_time": _format_check_in(attendance),
            "attendance_date": attendance.attendance_date.strftime("%d-%m-%Y"),
        },
    )

    email = EmailMessage(
        subject=subject,
        body=html_message,
        from_email=from_email,
        to=[to_email],
        reply_to=[from_email],
    )
    email.content_subtype = "html"
    _attach_logo(email)
    email.send()
    logger.info(
        "Late punch mail sent to %s for attendance id=%s",
        to_email,
        attendance.id,
    )


class LatePunchMailThread(Thread):
    """Send late punch mail in background with request on thread locals."""

    def __init__(self, request, attendance_id, subject, body):
        super().__init__(daemon=True)
        self.request = request
        self.attendance_id = attendance_id
        self.subject = subject
        self.body = body

    def run(self):
        from horilla.horilla_middlewares import _thread_locals

        _thread_locals.request = self.request
        try:
            attendance = Attendance.objects.select_related("employee_id").get(
                id=self.attendance_id
            )
            send_late_punch_mail_sync(
                self.request, attendance, self.subject, self.body
            )
        except Exception:
            logger.exception(
                "Failed to send late punch mail for attendance id=%s",
                self.attendance_id,
            )
        finally:
            _thread_locals.request = None
