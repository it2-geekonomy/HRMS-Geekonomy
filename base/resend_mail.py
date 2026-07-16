"""
Resend API helpers for sending mail through ConfiguredEmailBackend.
"""

from __future__ import annotations

import base64
import logging
import re
from email.mime.base import MIMEBase
from email.utils import parseaddr

from django.conf import settings

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _extract_email(value):
    """Return a bare email, or None if invalid."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    _name, addr = parseaddr(raw)
    candidate = (addr or raw).strip()
    if "<" in candidate and ">" in candidate:
        match = re.search(r"<([^>]+)>", candidate)
        if match:
            candidate = match.group(1).strip()
    if _EMAIL_RE.match(candidate):
        return candidate
    return None


def _normalize_addresses(addresses):
    if not addresses:
        return []
    if isinstance(addresses, str):
        addresses = [addresses]
    cleaned = []
    for item in addresses:
        email = _extract_email(item)
        if email:
            cleaned.append(email)
        else:
            logger.warning("Skipping invalid email address for Resend: %r", item)
    return cleaned


def _attachment_payload(attachment):
    """
    Convert a Django EmailMessage attachment into Resend's attachment format.
    """
    if isinstance(attachment, MIMEBase):
        payload = attachment.get_payload(decode=True) or b""
        filename = attachment.get_filename() or "attachment"
        content_type = attachment.get_content_type() or "application/octet-stream"
        return {
            "filename": filename,
            "content": base64.b64encode(payload).decode("ascii"),
            "content_type": content_type,
        }

    if isinstance(attachment, (tuple, list)):
        if len(attachment) == 2:
            filename, content = attachment
            mimetype = "application/octet-stream"
        else:
            filename, content, mimetype = attachment[:3]
        if isinstance(content, str):
            content = content.encode("utf-8")
        return {
            "filename": filename or "attachment",
            "content": base64.b64encode(content or b"").decode("ascii"),
            "content_type": mimetype or "application/octet-stream",
        }

    return None


def build_resend_params(message, default_from_email):
    """Build the dict passed to resend.Emails.send()."""
    # Always send From from settings/.env when Resend is active.
    from_email = default_from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    params = {
        "from": from_email,
        "to": _normalize_addresses(message.to),
        "subject": message.subject or "",
    }

    cc = _normalize_addresses(getattr(message, "cc", None))
    bcc = _normalize_addresses(getattr(message, "bcc", None))
    # Do not use dynamic reply-to that may be invalid; keep From as contact.
    reply_to = _normalize_addresses(getattr(message, "reply_to", None))
    if cc:
        params["cc"] = cc
    if bcc:
        params["bcc"] = bcc
    if reply_to:
        params["reply_to"] = reply_to

    body = message.body or ""
    html = None
    alternatives = getattr(message, "alternatives", None) or []
    for content, mimetype in alternatives:
        if mimetype == "text/html":
            html = content
            break

    if html:
        params["html"] = html
        if body:
            params["text"] = body
    elif getattr(message, "content_subtype", "plain") == "html":
        params["html"] = body
    else:
        params["text"] = body

    attachments = []
    for attachment in getattr(message, "attachments", None) or []:
        payload = _attachment_payload(attachment)
        if payload:
            attachments.append(payload)
    if attachments:
        params["attachments"] = attachments

    return params


def send_messages_via_resend(email_messages, default_from_email, fail_silently=False):
    """
    Send Django email messages through Resend's HTTP API.
    Returns the number of messages accepted by Resend.
    """
    api_key = getattr(settings, "RESEND_API_KEY", None) or ""
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")

    import resend

    resend.api_key = api_key
    sent = 0
    for message in email_messages:
        try:
            params = build_resend_params(message, default_from_email)
            if not params.get("to"):
                logger.warning("Skipping Resend mail with empty recipients: %s", message.subject)
                continue
            resend.Emails.send(params)
            sent += 1
        except Exception:
            logger.exception("Resend failed to send mail: %s", getattr(message, "subject", ""))
            if not fail_silently:
                raise
    return sent
