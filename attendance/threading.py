"""
Attendance request email notifications.
Sends email to employee, reporting manager, and HR (when configured).
Reporting manager's manager does not receive emails.
Runs in a background thread so the request returns immediately;
the thread sets request in thread locals so the email backend uses the same config.
"""

import logging
from threading import Thread

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from base.backends import ConfiguredEmailBackend

logger = logging.getLogger(__name__)

# HR notification email (hardcoded).
HR_EMAIL = "hr@thegeekonomy.com"


def _send_attendance_request_emails_sync(request, attendance, is_update_request=False):
    """
    Send attendance request emails to employee, reporting manager, and HR.
    Expects _thread_locals.request to be set (e.g. by _AttendanceRequestEmailThread).
    """
    employee = attendance.employee_id
    work_info = getattr(employee, "employee_work_info", None)
    reporting_manager_employee = getattr(work_info, "reporting_manager_id", None)

    if is_update_request:
        req_label = "attendance update request"
    else:
        req_label = "attendance request"

    employee_name = employee.get_full_name()
    attendance_id = attendance.id
    host = request.get_host()
    protocol = "https" if request.is_secure() else "http"

    # Use default backend (no connection=) so Django opens it in this request thread
    # and get_dynamic_email_config() sees _thread_locals.request (same as leave).
    email_backend = ConfiguredEmailBackend()
    display_email_name = email_backend.dynamic_from_email_with_display_name or getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@hrms"
    )
    logger.info(
        "Sending attendance request emails (attendance_id=%s, is_update=%s)",
        attendance_id, is_update_request,
    )

    def _send_one(to_email, instance, subject, content):
        if not to_email:
            return
        try:
            company_name = (
                instance.get_company().company
                if instance and getattr(instance, "get_company", None)
                else "HRMS"
            )
        except Exception:
            company_name = "HRMS"
        html_message = render_to_string(
            "base/mail_templates/attendance_request_template.html",
            {
                "link": attendance_id,
                "instance": instance,
                "host": host,
                "protocol": protocol,
                "subject": subject,
                "content": content,
                "white_label_company_name": company_name,
            },
        )
        email = EmailMessage(
            subject=subject,
            body=html_message,
            from_email=display_email_name,
            to=[to_email],
            reply_to=[display_email_name],
        )
        email.content_subtype = "html"
        try:
            email.send()
            logger.info("Attendance request email sent to %s", to_email)
        except Exception as e:
            logger.error("Failed to send attendance request email to %s: %s", to_email, e, exc_info=True)

    # 1) Employee (owner) - confirmation email
    owner_email = getattr(employee, "get_mail", None) and employee.get_mail()
    subject_owner = f"Your {req_label} for {attendance.attendance_date}"
    content_owner = (
        f"This is to inform you that your {req_label} for date {attendance.attendance_date} "
        f"has been submitted successfully. It will be reviewed by your manager."
    )
    _send_one(owner_email, employee, subject_owner, content_owner)

    # 2) Reporting manager
    if reporting_manager_employee:
        subject_manager = f"{employee_name}'s {req_label} for {attendance.attendance_date}"
        content_manager = (
            f"This is to inform you that a {req_label} has been submitted by {employee_name} "
            f"for date {attendance.attendance_date}. Please take the necessary action."
        )
        manager_email = getattr(reporting_manager_employee, "get_mail", None) and reporting_manager_employee.get_mail()
        _send_one(manager_email, reporting_manager_employee, subject_manager, content_manager)

    # 3) HR (if configured)
    if HR_EMAIL:
        subject_hr = f"{employee_name}'s {req_label} for {attendance.attendance_date}"
        content_hr = (
            f"This is to inform you that a {req_label} has been submitted by {employee_name} "
            f"for date {attendance.attendance_date}. Please take the necessary action."
        )
        _send_one(HR_EMAIL, None, subject_hr, content_hr)


class _AttendanceRequestEmailThread(Thread):
    """Send attendance request emails in background so the HTTP response returns immediately."""

    def __init__(self, request, attendance, is_update_request=False):
        super().__init__(daemon=True)
        self.request = request
        self.attendance = attendance
        self.is_update_request = is_update_request

    def run(self):
        from horilla.horilla_middlewares import _thread_locals
        try:
            _thread_locals.request = self.request
            _send_attendance_request_emails_sync(
                self.request, self.attendance, self.is_update_request
            )
        except Exception as e:
            logger.exception("Attendance request email thread failed: %s", e)
        finally:
            try:
                del _thread_locals.request
            except AttributeError:
                pass


def send_attendance_request_emails(request, attendance, is_update_request=False):
    """
    Start sending attendance request emails in a background thread.
    Returns immediately so the request form can show success without waiting for SMTP.
    """
    _AttendanceRequestEmailThread(request, attendance, is_update_request).start()


def _send_attendance_outcome_emails_sync(request, attendance, approved=True):
    """
    Send emails when an attendance request is approved or rejected.
    Recipients: employee (owner), reporting manager, HR. Not reporting manager's manager.
    Expects _thread_locals.request to be set (e.g. by outcome thread).
    """
    employee = attendance.employee_id
    work_info = getattr(employee, "employee_work_info", None)
    reporting_manager_employee = getattr(work_info, "reporting_manager_id", None)
    employee_name = employee.get_full_name()
    attendance_date = attendance.attendance_date
    attendance_id = getattr(attendance, "id", None) or "#"
    host = request.get_host()
    protocol = "https" if request.is_secure() else "http"
    emp = getattr(request.user, "employee_get", None)
    if emp and callable(getattr(emp, "get_full_name", None)):
        approver_name = emp.get_full_name()
    elif getattr(request.user, "get_full_name", None):
        approver_name = request.user.get_full_name()
    else:
        approver_name = str(request.user)

    if approved:
        action = "approved"
        subject_owner = f"Your attendance request for {attendance_date} has been approved"
        content_owner = (
            f"This is to inform you that your attendance request for {attendance_date} "
            f"has been approved by {approver_name}."
        )
        subject_others = f"Attendance request by {employee_name} for {attendance_date} has been approved"
        content_others = (
            f"The attendance request submitted by {employee_name} for {attendance_date} "
            f"has been approved by {approver_name}."
        )
    else:
        action = "rejected"
        subject_owner = f"Your attendance request for {attendance_date} has been rejected"
        content_owner = (
            f"This is to inform you that your attendance request for {attendance_date} "
            f"has been rejected by {approver_name}. You may contact {approver_name} for more information."
        )
        subject_others = f"Attendance request by {employee_name} for {attendance_date} has been rejected"
        content_others = (
            f"The attendance request submitted by {employee_name} for {attendance_date} "
            f"has been rejected by {approver_name}."
        )

    email_backend = ConfiguredEmailBackend()
    display_email_name = email_backend.dynamic_from_email_with_display_name or getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@hrms"
    )
    logger.info(
        "Sending attendance request %s emails (attendance_id=%s)",
        action, attendance_id,
    )

    def _send_one(to_email, instance, subject, content, link_id):
        if not to_email:
            return
        try:
            company_name = (
                instance.get_company().company
                if instance and getattr(instance, "get_company", None)
                else "HRMS"
            )
        except Exception:
            company_name = "HRMS"
        html_message = render_to_string(
            "base/mail_templates/attendance_request_template.html",
            {
                "link": link_id,
                "instance": instance,
                "host": host,
                "protocol": protocol,
                "subject": subject,
                "content": content,
                "white_label_company_name": company_name,
            },
        )
        email = EmailMessage(
            subject=subject,
            body=html_message,
            from_email=display_email_name,
            to=[to_email],
            reply_to=[display_email_name],
        )
        email.content_subtype = "html"
        try:
            email.send()
            logger.info("Attendance request %s email sent to %s", action, to_email)
        except Exception as e:
            logger.error(
                "Failed to send attendance %s email to %s: %s",
                action, to_email, e, exc_info=True,
            )

    # 1) Employee (owner)
    owner_email = getattr(employee, "get_mail", None) and employee.get_mail()
    _send_one(owner_email, employee, subject_owner, content_owner, attendance_id)

    # 2) Reporting manager only (not their manager)
    recipients = []
    if reporting_manager_employee:
        recipients.append(reporting_manager_employee)
    for recipient in recipients:
        if not recipient:
            continue
        to_email = getattr(recipient, "get_mail", None) and recipient.get_mail()
        if not to_email:
            continue
        _send_one(to_email, recipient, subject_others, content_others, attendance_id)

    # 3) HR (if configured)
    if HR_EMAIL:
        _send_one(HR_EMAIL, None, subject_others, content_others, attendance_id)


class _AttendanceOutcomeEmailThread(Thread):
    """Send approve/reject emails in background."""

    def __init__(self, request, attendance, approved=True):
        super().__init__(daemon=True)
        self.request = request
        self.attendance = attendance
        self.approved = approved

    def run(self):
        from horilla.horilla_middlewares import _thread_locals
        try:
            _thread_locals.request = self.request
            _send_attendance_outcome_emails_sync(
                self.request, self.attendance, approved=self.approved
            )
        except Exception as e:
            logger.exception("Attendance outcome email thread failed: %s", e)
        finally:
            try:
                del _thread_locals.request
            except AttributeError:
                pass


def send_attendance_request_approved_emails(request, attendance):
    """Start sending 'request approved' emails in a background thread."""
    _AttendanceOutcomeEmailThread(request, attendance, approved=True).start()


def send_attendance_request_rejected_emails(request, attendance):
    """Start sending 'request rejected' emails in a background thread."""
    _AttendanceOutcomeEmailThread(request, attendance, approved=False).start()
