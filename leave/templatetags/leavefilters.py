from django import template

from leave.methods import can_user_approve_leave_request
from leave.models import LeaveGeneralSetting

register = template.Library()


@register.filter(name="can_approve_leave_request")
def can_approve_leave_request_filter(user, leave_request):
    return can_user_approve_leave_request(user, leave_request)


@register.filter(name="get_item")
def get_item(dictionary, key):
    """Access dict by key (e.g. computed_leave_display|get_item:user_leave.id)."""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter(name="can_approve_comp_off_request")
def can_approve_comp_off_request_filter(user, comp_off_request):
    try:
        reporting_manager = comp_off_request.reporting_manager()
        return bool(
            reporting_manager and user.employee_get == reporting_manager
        )
    except Exception:
        return False


@register.filter(name="is_compensatory")
def is_compensatory(user):
    if LeaveGeneralSetting.objects.exists():
        return LeaveGeneralSetting.objects.first().compensatory_leave
    else:
        return False
