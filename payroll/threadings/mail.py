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
from django.template.loader import render_to_string

from base.backends import ConfiguredEmailBackend
from employee.models import EmployeeWorkInformation
from payroll.models.models import Payslip
from payroll.views.views import payslip_pdf, payslip_pdf_content

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


class MailSendThread(Thread):
    """
    MailSend
    """

    def __init__(self, request, result_dict, ids):
        Thread.__init__(self)
        self.result_dict = result_dict
        self.ids = ids
        self.request = request
        self.host = request.get_host()
        self.protocol = "https" if request.is_secure() else "http"

    def run(self) -> None:
        super().run()
        for record in list(self.result_dict.values()):
            html_message = render_to_string(
                "payroll/mail_templates/default.html",
                _payslip_mail_template_context(record, self.host, self.protocol),
                request=self.request,
            )
            attachments = []
            attached_ids = []
            for instance in record["instances"]:
                response = payslip_pdf(self.request, instance.id)
                # Only attach if response is a valid PDF (avoid attaching error pages as .pdf)
                if getattr(response, "status_code", 0) != 200:
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
            if not attachments:
                logger.warning(
                    "Payslip mail: no valid PDFs for record, skipping email to %s",
                    record["instances"][0].employee_id,
                )
                continue

            employee = record["instances"][0].employee_id
            email_backend = ConfiguredEmailBackend()
            display_email_name = email_backend.dynamic_from_email_with_display_name
            if self.request:
                try:
                    display_email_name = f"{self.request.user.employee_get.get_full_name()} <{self.request.user.employee_get.email}>"
                except Exception:
                    logger.error("Payslip mail: failed to get display name", exc_info=True)

            email = EmailMessage(
                f"Hello, {record['instances'][0].get_name()} Your Payslips is Ready!",
                html_message,
                display_email_name,
                [employee.get_mail()],
                reply_to=[display_email_name],
            )
            email.attachments = attachments
            email.content_subtype = "html"
            _attach_payslip_mail_logo(email)

            try:
                email.send()
                # Only mark as sent the payslips we actually attached
                if attached_ids:
                    Payslip.objects.filter(id__in=attached_ids).update(sent_to_employee=True)
            except Exception as e:
                logger.exception(e)

        return


def send_payslips_on_11th():
    """
    Send payslips automatically on the 11th of every month.
    Sends all unsent payslips for the previous month to each employee's email.
    Call this from the payroll scheduler when today is the 11th.
    """
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

    email_backend = ConfiguredEmailBackend()
    from_email = getattr(
        email_backend,
        "dynamic_from_email_with_display_name",
        None,
    ) or "HR <noreply@example.com>"
    if not from_email or not str(from_email).strip():
        logger.warning("Payslip auto-send: email server not configured, skipping")
        return

    # Group by employee (same structure as send_slip view)
    result_dict = defaultdict(lambda: {"employee_id": None, "instances": [], "count": 0})
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
        email_to = employee.get_mail() if hasattr(employee, "get_mail") else getattr(employee, "email", None)
        if not email_to:
            logger.warning("Payslip auto-send: no email for employee %s", employee)
            continue

        attachments = []
        for instance in record["instances"]:
            response = payslip_pdf_content(instance.id)
            if response is None or getattr(response, "status_code", 200) != 200:
                logger.warning("Payslip auto-send: failed to generate PDF for payslip id=%s", instance.id)
                continue
            attachments.append(
                (
                    f"{instance.get_payslip_title()}.pdf",
                    response.content,
                    "application/pdf",
                )
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
            reply_to=[from_email],
        )
        email.attachments = attachments
        email.content_subtype = "html"
        _attach_payslip_mail_logo(email)

        try:
            email.send()
            ids_to_mark.extend(p.id for p in record["instances"])
        except Exception as e:
            logger.exception("Payslip auto-send: failed to send email to %s: %s", email_to, e)

    if ids_to_mark:
        Payslip.objects.filter(id__in=ids_to_mark).update(sent_to_employee=True)
        logger.info("Payslip auto-send: sent %d payslip(s) to employees.", len(ids_to_mark))
