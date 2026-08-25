import logging
from threading import Thread

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage, send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from base.backends import ConfiguredEmailBackend
from base.mail_icons import request_mail_icon

logger = logging.getLogger(__name__)

# HR notification email for leave (hardcoded).
HR_EMAIL = "it1@geekonomy.in"


def _send_leave_approve_reject_fallback(request, leave_request, to_email, approved=True):
    """Fallback: send plain-text email using Django default backend when main path fails."""
    action = "approved" if approved else "rejected"
    subject = f"Leave request {action}"
    body = (
        f"Your leave request (id={leave_request.id}, {leave_request.start_date} - {leave_request.end_date}) "
        f"has been {action}."
    )
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@hrms"),
            recipient_list=[to_email],
            fail_silently=False,
        )
        logger.info("Leave %s fallback email sent to %s", action, to_email)
    except Exception as e:
        logger.exception("Leave %s fallback email also failed: %s", action, e)


def send_leave_approve_reject_email(request, leave_request, approved=True):
    """
    Send approve or reject email in the current (request) thread so the email
    backend has request context. Call from the view after approve/reject.
    Returns True if email was sent or attempted, False if skipped (e.g. employee has no email).
    """
    action = "approve" if approved else "reject"
    logger.info(
        "Leave %s email: request id=%s, employee=%s",
        action, leave_request.id, leave_request.employee_id,
    )
    owner = leave_request.employee_id
    to_email = getattr(owner, "get_mail", None)
    to_email = to_email() if callable(to_email) else None
    if not to_email:
        logger.warning(
            "Leave %s email NOT sent: employee %s has no email (set in Employee or Work Info)",
            action, getattr(owner, "get_full_name", lambda: owner)(),
        )
        return False
    thread = LeaveMailSendThread(request, leave_request, type=action)
    try:
        thread._run_send()
        logger.info("Leave %s email sent successfully to %s", action, to_email)
        return True
    except Exception as e:
        logger.exception("Leave %s email failed: %s", action, e)
        _send_leave_approve_reject_fallback(request, leave_request, to_email, approved)
        return True


class LeaveMailSendThread(Thread):

    def __init__(self, request, leave_request, type):
        Thread.__init__(self)
        self.request = request
        self.leave_request = leave_request
        self.type = type
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"

    def _get_approver_name(self):
        """Return the full name of the user who approved/rejected (request.user)."""
        emp = getattr(self.request.user, "employee_get", None)
        if emp and callable(getattr(emp, "get_full_name", None)):
            return emp.get_full_name()
        if callable(getattr(self.request.user, "get_full_name", None)):
            return self.request.user.get_full_name()
        return str(self.request.user)

    def send_email(self, subject, content, recipients, leave_request_id="#"):
        email_backend = ConfiguredEmailBackend()
        display_email_name = (
            email_backend.dynamic_from_email_with_display_name
            or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@hrms")
        )

        host = self.host
        protocol = self.protocol
        link = "#" if leave_request_id == "#" else int(leave_request_id)
        for recipient in recipients:
            if not recipient:
                continue
            to_email = getattr(recipient, "get_mail", None)
            to_email = to_email() if callable(to_email) else None
            if not to_email:
                logger.warning(
                    "Leave email: skipping %s (no email)",
                    getattr(recipient, "get_full_name", lambda: str(recipient))(),
                )
                continue
            # Do not pass request so context processors (e.g. sidebar with reverse()) don't run
            # in this thread and cause NoReverseMatch for optional app URLs.
            try:
                company_name = recipient.get_company().company if getattr(recipient, "get_company", None) else "HRMS"
            except Exception:
                company_name = "HRMS"
            html_message = render_to_string(
                    "base/mail_templates/leave_request_template.html",
                    {
                        "link": link,
                        "instance": recipient,
                        "host": host,
                        "protocol": protocol,
                        "subject": subject,
                        "content": content,
                        "white_label_company_name": company_name,
                        "mail_icon": request_mail_icon(mail_type=self.type),
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
                logger.info("Leave email sent to %s (type=%s)", to_email, self.type)
            except Exception as e:
                logger.error(
                    "Failed to send leave email to %s: %s", to_email, e, exc_info=True
                )
                try:
                    messages.error(
                        self.request, f"Mail not sent to {recipient.get_full_name()}"
                    )
                except Exception:
                    pass
    
    def send_email_to_hr(self, subject, content, hr_email, leave_request_id="#"):
        """
        Send email directly to HR email address (not an employee object)
        """
        email_backend = ConfiguredEmailBackend()
        display_email_name = (
            email_backend.dynamic_from_email_with_display_name
            or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@hrms")
        )

        host = self.host
        protocol = self.protocol
        link = "#" if leave_request_id == "#" else int(leave_request_id)

        # Get company name and employee info from leave request
        try:
            owner = self.leave_request.employee_id
            company_name = owner.get_company().company if getattr(owner, "get_company", None) else "HRMS"
            employee_name = owner.get_full_name() if owner else ""
            # Get company icon URL
            try:
                company_icon_url = f"{protocol}://{host}{owner.get_company().icon.url}" if owner and getattr(owner, "get_company", None) and owner.get_company().icon else None
            except:
                company_icon_url = None
        except Exception:
            company_name = "HRMS"
            employee_name = ""
            company_icon_url = None
        
        # Create HTML message for HR (using owner as instance for template compatibility)
        # The template expects an instance, so we'll use the owner but address it to HR
        html_message = render_to_string(
            "base/mail_templates/leave_request_template.html",
            {
                "link": link,
                "instance": owner,  # Use owner for template compatibility, but email goes to HR
                "host": host,
                "protocol": protocol,
                "subject": subject,
                "content": content,
                "white_label_company_name": company_name,
                "mail_icon": request_mail_icon(mail_type=self.type),
            },
        )
        
        # Replace the greeting to address HR instead of the employee
        # Template format: "Hello {{ instance.get_full_name }}, {{subject}}!"
        if employee_name:
            html_message = html_message.replace(
                f"Hello {employee_name},",
                "Hello HR Team,"
            )
        # Also handle case where name might be empty or different format
        html_message = html_message.replace(
            "Hello ,",
            "Hello HR Team,"
        )

        email = EmailMessage(
            subject=subject,
            body=html_message,
            from_email=display_email_name,
            to=[hr_email],
            reply_to=[display_email_name],
        )
        email.content_subtype = "html"
        try:
            email.send()
            logger.info(f"Leave request email sent to HR: {hr_email}")
        except Exception as e:
            logger.error(f"Failed to send email to HR ({hr_email}): {e}")
            try:
                messages.error(
                    self.request, f"Mail not sent to HR ({hr_email})"
                )
            except:
                pass  # If request is not available in thread context

    def run(self) -> None:
        super().run()
        # Set request in thread locals so ConfiguredEmailBackend gets correct email config
        # (same as request thread / attendance emails). Without this, backend may have no config.
        from horilla.horilla_middlewares import _thread_locals
        try:
            _thread_locals.request = self.request
            self._run_send()
        except Exception as e:
            logger.exception("Leave mail thread failed (type=%s): %s", self.type, e)
        finally:
            try:
                del _thread_locals.request
            except AttributeError:
                pass

    def _run_send(self):
        """Actual email logic; run with _thread_locals.request set."""
        if self.type == "request":
            owner = self.leave_request.employee_id
            reporting_manager = self.leave_request.employee_id.get_reporting_manager()

            # Format date display: single date for one-day, range for multiple days
            if self.leave_request.start_date == self.leave_request.end_date:
                date_display = f"{self.leave_request.start_date}"
            else:
                date_display = f"{self.leave_request.start_date} to {self.leave_request.end_date}"

            content_manager = f"This is to inform you that a leave request has been requested by {owner} for {date_display}. Take the necessary actions for the leave request. Should you have any additional information or updates, please feel free to communicate directly with the {owner}."
            subject_manager = f"Leave request has been requested by {owner} for {date_display}"

            # Collect all email recipients
            email_recipients = []

            # 1. Reporting manager only (not their manager)
            if reporting_manager:
                email_recipients.append(reporting_manager)
                logger.info(f"Added reporting manager: {reporting_manager}")

            # Send emails to managers
            if email_recipients:
                self.send_email(
                    subject_manager,
                    content_manager,
                    email_recipients,
                    self.leave_request.id,
                )

            # 3. Send email to HR (if configured)
            if HR_EMAIL:
                try:
                    self.send_email_to_hr(
                        subject_manager,
                        content_manager,
                        HR_EMAIL,
                        self.leave_request.id,
                    )
                except Exception as e:
                    logger.error("Failed to send email to HR: %s", e)

            content_owner = f"This is to inform you that the leave request you created has been successfully logged into our system. The manager will now take the necessary actions to address the leave request on {date_display}. Should you have any additional information or updates, please feel free to communicate directly with {reporting_manager}."
            subject_owner = "Leave request created successfully"

            self.send_email(
                subject_owner, content_owner, [owner], self.leave_request.id
            )

        elif self.type == "approve":
            owner = self.leave_request.employee_id
            try:
                reporting_manager = self.leave_request.employee_id.get_reporting_manager()
            except Exception:
                reporting_manager = None
            rm_text = str(reporting_manager) if reporting_manager else _("your manager")
            approver_name = self._get_approver_name()
            owner_name = getattr(owner, "get_full_name", lambda: str(owner))()

            subject_owner = f"The Leave request for {self.leave_request.start_date} to {self.leave_request.end_date} has been successfully approved"
            content_owner = f"This is to inform you that the leave request has been approved by {approver_name} for the period {self.leave_request.start_date} to {self.leave_request.end_date}. If you have any questions or require further information, feel free to reach out to {rm_text}."
            subject_others = f"Leave request by {owner_name} for {self.leave_request.start_date} to {self.leave_request.end_date} has been approved"
            content_others = f"The leave request submitted by {owner_name} for the period {self.leave_request.start_date} to {self.leave_request.end_date} has been approved by {approver_name}."

            self.send_email(subject_owner, content_owner, [owner], self.leave_request.id)
            email_recipients = [reporting_manager] if reporting_manager else []
            if email_recipients:
                self.send_email(subject_others, content_others, email_recipients, self.leave_request.id)
            if HR_EMAIL:
                self.send_email_to_hr(subject_others, content_others, HR_EMAIL, self.leave_request.id)

        elif self.type == "reject":
            owner = self.leave_request.employee_id
            try:
                reporting_manager = self.leave_request.employee_id.get_reporting_manager()
            except Exception:
                reporting_manager = None
            rm_text = str(reporting_manager) if reporting_manager else _("your manager")
            approver_name = self._get_approver_name()
            owner_name = getattr(owner, "get_full_name", lambda: str(owner))()

            subject_owner = f"The Leave request for {self.leave_request.start_date} to {self.leave_request.end_date} has been rejected"
            content_owner = f"This is to inform you that the leave request has been rejected by {approver_name} for the period {self.leave_request.start_date} to {self.leave_request.end_date}. If you have any questions or require further information, feel free to reach out to {rm_text}."
            subject_others = f"Leave request by {owner_name} for {self.leave_request.start_date} to {self.leave_request.end_date} has been rejected"
            content_others = f"The leave request submitted by {owner_name} for the period {self.leave_request.start_date} to {self.leave_request.end_date} has been rejected by {approver_name}."

            self.send_email(subject_owner, content_owner, [owner], self.leave_request.id)
            email_recipients = [reporting_manager] if reporting_manager else []
            if email_recipients:
                self.send_email(subject_others, content_others, email_recipients, self.leave_request.id)
            if HR_EMAIL:
                self.send_email_to_hr(subject_others, content_others, HR_EMAIL, self.leave_request.id)

        elif self.type == "cancel":
            owner = self.leave_request.employee_id
            reporting_manager = self.leave_request.employee_id.get_reporting_manager()

            content_manager = f"This is to inform you that a leave request has been requested to cancel by {owner}. Take the necessary actions for the leave request. Should you have any additional information or updates, please feel free to communicate directly with the {owner}."
            subject_manager = f"Leave request cancellation"

            self.send_email(
                subject_manager,
                content_manager,
                [reporting_manager],
                self.leave_request.id,
            )

            content_owner = f"This is to inform you that a cancellation request created for your leave request has been successfully logged into our system. The manager will now take the necessary actions to address the leave request. Should you have any additional information or updates, please feel free to communicate directly with the {reporting_manager}."
            subject_owner = "Leave request cancellation requested"

            self.send_email(
                subject_owner, content_owner, [owner], self.leave_request.id
            )

        return  # end _run_send


def _comp_off_date_display(comp_off_request):
    if comp_off_request.start_date == comp_off_request.end_date:
        return f"{comp_off_request.start_date}"
    return f"{comp_off_request.start_date} to {comp_off_request.end_date}"


def send_comp_off_email(request, comp_off_request, mail_type):
    """Send Comp-Off email in a background thread (create / cancel)."""
    CompOffMailSendThread(request, comp_off_request, mail_type).start()


def send_comp_off_approve_reject_email(request, comp_off_request, approved=True):
    """Send approve/reject email in a background thread (same as create/cancel)."""
    mail_type = "approve" if approved else "reject"
    CompOffMailSendThread(request, comp_off_request, mail_type).start()


class CompOffMailSendThread(LeaveMailSendThread):
    """Email notifications for Comp-Off requests (HR + reporting manager + employee)."""

    def __init__(self, request, comp_off_request, type):
        super().__init__(request, comp_off_request, type)
        self.comp_off_request = comp_off_request

    def _run_send(self):
        comp_off = self.comp_off_request
        date_display = _comp_off_date_display(comp_off)
        owner = comp_off.employee_id
        try:
            reporting_manager = owner.get_reporting_manager()
        except Exception:
            reporting_manager = comp_off.reporting_manager()

        if self.type == "request":
            content_manager = (
                f"This is to inform you that a Comp-Off request has been submitted by {owner} "
                f"for {date_display}. Please review and take the necessary action."
            )
            subject_manager = f"Comp-Off request submitted by {owner} for {date_display}"

            recipients = [reporting_manager] if reporting_manager else []
            if recipients:
                self.send_email(
                    subject_manager, content_manager, recipients, comp_off.id
                )
            if HR_EMAIL:
                self.send_email_to_hr(
                    subject_manager, content_manager, HR_EMAIL, comp_off.id
                )

            content_owner = (
                f"Your Comp-Off request for {date_display} has been submitted successfully. "
                f"Your reporting manager will review it shortly."
            )
            subject_owner = "Comp-Off request created successfully"
            self.send_email(subject_owner, content_owner, [owner], comp_off.id)

        elif self.type == "approve":
            approver_name = self._get_approver_name()
            owner_name = getattr(owner, "get_full_name", lambda: str(owner))()
            approved_days = comp_off.approved_days or comp_off.requested_days
            subject_owner = f"Your Comp-Off request for {date_display} has been approved"
            content_owner = (
                f"Your Comp-Off request for {date_display} has been approved by {approver_name}. "
                f"{approved_days} day(s) have been added to your Comp Off Leave balance."
            )
            subject_others = (
                f"Comp-Off request by {owner_name} for {date_display} has been approved"
            )
            content_others = (
                f"The Comp-Off request submitted by {owner_name} for {date_display} "
                f"has been approved by {approver_name}. {approved_days} day(s) credited."
            )
            self.send_email(subject_owner, content_owner, [owner], comp_off.id)
            if reporting_manager:
                self.send_email(
                    subject_others, content_others, [reporting_manager], comp_off.id
                )
            if HR_EMAIL:
                self.send_email_to_hr(
                    subject_others, content_others, HR_EMAIL, comp_off.id
                )

        elif self.type == "reject":
            approver_name = self._get_approver_name()
            owner_name = getattr(owner, "get_full_name", lambda: str(owner))()
            subject_owner = f"Your Comp-Off request for {date_display} has been rejected"
            content_owner = (
                f"Your Comp-Off request for {date_display} has been rejected by {approver_name}."
            )
            if comp_off.reject_reason:
                content_owner += f" Reason: {comp_off.reject_reason}"
            subject_others = (
                f"Comp-Off request by {owner_name} for {date_display} has been rejected"
            )
            content_others = (
                f"The Comp-Off request submitted by {owner_name} for {date_display} "
                f"has been rejected by {approver_name}."
            )
            self.send_email(subject_owner, content_owner, [owner], comp_off.id)
            if reporting_manager:
                self.send_email(
                    subject_others, content_others, [reporting_manager], comp_off.id
                )
            if HR_EMAIL:
                self.send_email_to_hr(
                    subject_others, content_others, HR_EMAIL, comp_off.id
                )

        elif self.type == "cancel":
            content_manager = (
                f"{owner} has cancelled their Comp-Off request for {date_display}."
            )
            subject_manager = "Comp-Off request cancelled"
            if reporting_manager:
                self.send_email(
                    subject_manager, content_manager, [reporting_manager], comp_off.id
                )
            if HR_EMAIL:
                self.send_email_to_hr(
                    subject_manager, content_manager, HR_EMAIL, comp_off.id
                )
            content_owner = (
                f"Your Comp-Off request for {date_display} has been cancelled successfully."
            )
            subject_owner = "Comp-Off request cancelled"
            self.send_email(subject_owner, content_owner, [owner], comp_off.id)


class LeaveClashThread(Thread):

    def __init__(self, leave_request):
        Thread.__init__(self)
        self.leave_request = leave_request

    def count_leave_clashes(self):
        from leave.models import LeaveRequest

        """
        Method to count leave clashes where this employee's leave request overlaps
        with other employees' requested dates.
        """
        overlapping_requests = LeaveRequest.objects.exclude(
            id=self.leave_request.id
        ).filter(
            Q(
                employee_id__employee_work_info__department_id=self.leave_request.employee_id.employee_work_info.department_id
            )
            | Q(
                employee_id__employee_work_info__job_position_id=self.leave_request.employee_id.employee_work_info.job_position_id
            ),
            start_date__lte=self.leave_request.end_date,
            end_date__gte=self.leave_request.start_date,
        )

        return overlapping_requests.count()

    def run(self) -> None:
        from leave.models import LeaveRequest

        super().run()
        dates = self.leave_request.requested_dates()
        leave_requests_to_update = LeaveRequest.objects.filter(
            Q(start_date__in=dates) | Q(end_date__in=dates)
        )

        for leave_request in leave_requests_to_update:
            leave_request.leave_clashes_count = self.count_leave_clashes()
            leave_request.save()
