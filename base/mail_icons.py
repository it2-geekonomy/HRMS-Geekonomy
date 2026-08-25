"""Static paths for leave/attendance transactional email center icons."""

MAIL_ICON_SUCCESS = "images/ui/attendances-mail.png"
MAIL_ICON_REJECT = "images/ui/mail-reject.png"


def request_mail_icon(*, mail_type=None, rejected=False):
    """Checkmark for create/approve/cancel; X in circle only for reject."""
    if rejected or mail_type == "reject":
        return MAIL_ICON_REJECT
    return MAIL_ICON_SUCCESS
