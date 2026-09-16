"""
mail.py

This module is used handle mail sent in thread
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.mime.image import MIMEImage
from pathlib import Path
from threading import Thread

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import close_old_connections
from django.template.loader import render_to_string

from base.backends import ConfiguredEmailBackend
from payroll.models.models import Payslip
from payroll.views.views import payslip_pdf_content

logger = logging.getLogger(__name__)

# On the 11th of every month, send unsent payslips (for previous month) to employees.
PAYSLIP_AUTO_SEND_DAY = 11
PAYSLIP_MAIL_LOGO_CID = "payslip-logo"


def _payslip_mail_logo_path():
    ui = Path(settings.BASE_DIR) / "static" / "images" / "ui"
    for name in ("geekonomy-logo-mail.png", "GeekonomyLogo (1).png", "Geekonomy Logo (2).png"):
        path = ui / name
        if path.is_file():
            return path
    return ui / "geekonomy-logo-mail.png"


def _payslip_mail_template_context(record, host, protocol):
    return {
        "record": record,
        "host": host,
        "protocol": protocol,
        "logo_cid": PAYSLIP_MAIL_LOGO_CID,
        "current_year": datetime.now().year,
    }


def _attach_payslip_mail_logo(email):
    logo_path = _payslip_mail_logo_path()
    if not logo_path.is_file():
        logger.warning("Payslip mail: logo not found at %s", logo_path)
        return
    with open(logo_path, "rb") as logo_file:
        img = MIMEImage(logo_file.read(), _subtype="png")
    img.add_header("Content-ID", f"<{PAYSLIP_MAIL_LOGO_CID}>")
    img.add_header("Content-Disposition", "inline", filename="geekonomy-logo.png")
    email.attach(img)


def _payslip_from_email():
    """Resolve From address: Resend requires verified DEFAULT_FROM_EMAIL."""
    email_backend = ConfiguredEmailBackend()
    if getattr(settings, "RESEND_API_KEY", None):
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(
            email_backend, "dynamic_from_email_with_display_name", None
        )
    else:
        from_email = getattr(
            email_backend, "dynamic_from_email_with_display_name", None
        )
    return from_email, email_backend


def _build_payslip_pdf_attachments(instances):
    """Generate PDFs without an HTTP request (works in Docker / background threads)."""
    attachments = []
    attached_ids = []
    for instance in instances:
        response = payslip_pdf_content(instance.id)
        if response is None or getattr(response, "status_code", 200) != 200:
            logger.warning(
                "Payslip mail: skipping invalid PDF for payslip id=%s (status=%s)",
                instance.id,
                getattr(response, "status_code", None),
            )
            continue
        content = getattr(response, "content", None) or b""
        if not content or not content.startswith(b"%PDF"):
            logger.warning(
                "Payslip mail: skipping non-PDF content for payslip id=%s (len=%s)",
                instance.id,
                len(content),
            )
            continue
        attachments.append(
            (
                f"{instance.get_payslip_title()}.pdf",
                content,
                "application/pdf",
            )
        )
        attached_ids.append(instance.id)
    return attachments, attached_ids


class MailSendThread(Thread):
    """
    MailSend
    """

    def __init__(self, request, result_dict, ids):
        Thread.__init__(self)
        self.result_dict = result_dict
        self.ids = ids
        # Capture host/protocol only — do not keep request for PDF/auth in the thread
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"
        # Snapshot payslip PKs so we re-fetch with a fresh DB connection in the thread
        self._grouped_ids = {}
        for key, record in result_dict.items():
            self._grouped_ids[key] = [p.id for p in record.get("instances") or []]

    def run(self) -> None:
        close_old_connections()
        try:
            from_email, email_backend = _payslip_from_email()
            if not from_email:
                logger.error("Payslip mail: from_email not configured, aborting send")
                return

            for emp_key, payslip_ids in self._grouped_ids.items():
                payslips = list(
                    Payslip.objects.filter(id__in=payslip_ids).select_related(
                        "employee_id"
                    )
                )
                if not payslips:
                    continue
                record = {
                    "employee_id": payslips[0].employee_id,
                    "instances": payslips,
                    "count": len(payslips),
                }

                html_message = render_to_string(
                    "payroll/mail_templates/default.html",
                    _payslip_mail_template_context(record, self.host, self.protocol),
                )
                attachments, attached_ids = _build_payslip_pdf_attachments(payslips)
                if not attachments:
                    logger.warning(
                        "Payslip mail: no valid PDFs for record, skipping email to %s",
                        payslips[0].employee_id,
                    )
                    continue

                employee = payslips[0].employee_id
                to_email = employee.get_mail() if employee else None
                if not to_email:
                    logger.warning(
                        "Payslip mail: no recipient email for employee %s", employee
                    )
                    continue

                email = EmailMessage(
                    f"Hello, {payslips[0].get_name()} Your Payslips is Ready!",
                    html_message,
                    from_email,
                    [to_email],
                    connection=email_backend,
                )
                email.attachments = attachments
                email.content_subtype = "html"
                _attach_payslip_mail_logo(email)

                try:
                    sent = email.send(fail_silently=False)
                    if sent:
                        if attached_ids:
                            Payslip.objects.filter(id__in=attached_ids).update(
                                sent_to_employee=True
                            )
                        logger.info(
                            "Payslip mail: sent payslip(s) %s to %s",
                            attached_ids,
                            to_email,
                        )
                    else:
                        logger.error(
                            "Payslip mail: send() returned 0 for payslip(s) %s to %s",
                            attached_ids,
                            to_email,
                        )
                except Exception as e:
                    logger.exception(
                        "Payslip mail: failed sending to %s: %s", to_email, e
                    )
        finally:
            close_old_connections()


def send_payslips_on_11th():
    """
    Send payslips automatically on the 11th of every month.
    Sends all unsent payslips for the previous month to each employee's email.
    Call this from the payroll scheduler when today is the 11th.
    """
    close_old_connections()
    try:
        today = date.today()
        if today.day != PAYSLIP_AUTO_SEND_DAY:
            return

        # Previous month's last day
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        first_prev_month = last_prev_month.replace(day=1)

        payslips = Payslip.objects.filter(
            start_date=first_prev_month,
            end_date=last_prev_month,
            sent_to_employee=False,
        )

        if not payslips.exists():
            return

        from_email, email_backend = _payslip_from_email()
        if not from_email or not str(from_email).strip():
            logger.warning("Payslip auto-send: email server not configured, skipping")
            return

        # Group by employee (same structure as send_slip view)
        result_dict = defaultdict(
            lambda: {"employee_id": None, "instances": [], "count": 0}
        )
        for payslip in payslips:
            emp = payslip.employee_id
            result_dict[emp]["employee_id"] = emp
            result_dict[emp]["instances"].append(payslip)
            result_dict[emp]["count"] += 1

        ids_to_mark = []
        for record in result_dict.values():
            if not record["instances"]:
                continue
            employee = record["instances"][0].employee_id
            email_to = (
                employee.get_mail()
                if hasattr(employee, "get_mail")
                else getattr(employee, "email", None)
            )
            if not email_to:
                logger.warning(
                    "Payslip auto-send: no email for employee %s", employee
                )
                continue

            attachments, attached_ids = _build_payslip_pdf_attachments(
                record["instances"]
            )
            if not attachments:
                continue

            html_message = render_to_string(
                "payroll/mail_templates/default.html",
                _payslip_mail_template_context(record, "", "https"),
            )

            email = EmailMessage(
                subject=f"Hello, {record['instances'][0].get_name()} Your Payslips is Ready!",
                body=html_message,
                from_email=from_email,
                to=[email_to],
                connection=email_backend,
            )
            email.attachments = attachments
            email.content_subtype = "html"
            _attach_payslip_mail_logo(email)

            try:
                sent = email.send(fail_silently=False)
                if sent:
                    ids_to_mark.extend(attached_ids)
                else:
                    logger.error(
                        "Payslip auto-send: send() returned 0 for %s", email_to
                    )
            except Exception as e:
                logger.exception(
                    "Payslip auto-send: failed to send email to %s: %s", email_to, e
                )

        if ids_to_mark:
            Payslip.objects.filter(id__in=ids_to_mark).update(sent_to_employee=True)
            logger.info(
                "Payslip auto-send: sent %d payslip(s) to employees.", len(ids_to_mark)
            )
    finally:
        close_old_connections()
