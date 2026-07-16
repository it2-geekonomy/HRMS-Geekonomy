import json

from django import template
from django.apps import apps
from django.core.paginator import Page, Paginator
from django.template.defaultfilters import register

from base.methods import get_pagination
from base.models import MultipleApprovalManagers
from employee.models import Employee, EmployeeWorkInformation

register = template.Library()


@register.filter(name="cancel_request")
def cancel_request(user, request):
    employee = user.employee_get
    employee_manages = employee.reporting_manager.all()
    return bool(
        request.employee_id == employee
        or user.has_perm("perms.base.cancel_worktyperequest")
        or user.has_perm("perms.base.cancel_shiftrequest")
        or employee_manages.exists()
    )


@register.filter(name="update_request")
def update_request(user, request):
    employee = user.employee_get
    return bool(
        not request.canceled
        and not request.approved
        and (
            employee == request.employee_id
            or user.has_perm("perms.base.change_worktyperequest")
            or user.has_perm("perms.base.change_shiftrequest")
        )
    )


@register.filter(name="is_reportingmanager")
def is_reportingmanager(user):
    """{% load basefilters %}

    This method will return true if the user employee profile is reporting manager to any employee
    """
    employee = Employee.objects.filter(employee_user_id=user).first()
    return EmployeeWorkInformation.objects.filter(
        reporting_manager_id=employee
    ).exists()


@register.filter(name="is_leave_approval_manager")
def is_leave_approval_manager(user):
    """
    This method will return true if the user is comes in MultipleApprovalCondition model as approving manager
    """
    employee = Employee.objects.filter(employee_user_id=user).first()
    manager = (
        MultipleApprovalManagers.objects.filter(employee_id=employee.id).exists()
        if employee
        else False
    )
    return manager


@register.filter(name="check_manager")
def check_manager(user, instance):
    try:
        if isinstance(instance, Employee):
            return instance.employee_work_info.reporting_manager_id == user.employee_get
        return (
            user.employee_get
            == instance.employee_id.employee_work_info.reporting_manager_id
        )
    except:
        return False


@register.filter(name="filtersubordinates")
def filtersubordinates(user):
    """
    This method returns true if the user employee has corresponding related reporting manager object in EmployeeWorkInformation model
    args:
        user    : request.user
    """
    employee = user.employee_get
    employee_manages = employee.reporting_manager.all()
    return employee_manages.exists()


@register.filter(name="filter_field")
def filter_field(value):
    if value.endswith("_id"):
        value = value[:-3]
    if value.endswith("_ids"):
        value = value[:-4]
    splitted = value.split("__")

    return splitted[-1].replace("_", " ").capitalize()


@register.filter(name="user_perms")
def user_perms(perms):
    """
    permission names return method.
    Handles None (e.g. employee has no linked user) by returning empty list JSON.
    """
    if perms is None:
        return json.dumps([])
    return json.dumps(list(perms.values_list("codename", flat="True")))


@register.filter(name="abs_value")
def abs_value(value):
    """
    permission names return method
    """
    return abs(value)


@register.filter(name="config_perms")
def config_perms(user):
    app_permissions = {
        "leave": [
            "leave.view_restrictleave",
        ],
        "base": [
            "base.add_holiday",
            "base.change_holiday",
            "base.add_companyleaves",
            "base.change_companyleaves",
            "base.add_horillamailtemplates",
            "base.view_horillamailtemplates",
        ],
    }

    for app, perms in app_permissions.items():
        if apps.is_installed(app):
            for perm in perms:
                if user.has_perm(perm):
                    return True
    return False


@register.filter(name="startswith")
def startswith(value, arg):
    """Checks if the value starts with the provided argument."""
    return value.startswith(arg)


def _normalize_path_for_sidebar(path):
    """Strip optional language prefix (/en/, /de/) and trailing slash for consistent matching."""
    if not path:
        return ""
    path = path.strip()
    # Strip leading /LL/ (2-letter language code) if present
    if len(path) > 4 and path[0] == "/" and path[3] == "/" and path[1:3].isalpha():
        path = path[4:] or "/"
    return path.rstrip("/") or "/"


@register.filter(name="path_under")
def path_under(value, prefix):
    """Returns True if current path is the same as or under the given prefix (for sidebar highlight)."""
    if not value or not prefix:
        return False
    path = _normalize_path_for_sidebar(value)
    prefix = (prefix or "").strip().rstrip("/") or "/"
    return path == prefix or path.startswith(prefix + "/")


@register.filter(name="path_equals")
def path_equals(value, other):
    """Returns True if path equals other after normalizing (for dashboard/home highlight)."""
    if not value and not other:
        return True
    if not value or not other:
        return False
    return _normalize_path_for_sidebar(value) == _normalize_path_for_sidebar(other)


@register.filter(name="path_in_submenus")
def path_in_submenus(path, submenus):
    """Returns True if path is under any submenu redirect (for sidebar section highlight)."""
    if not path or not submenus:
        return False
    path_norm = _normalize_path_for_sidebar(path)
    for s in submenus:
        redirect = (s.get("redirect") or "").strip().rstrip("/") or "/"
        if path_norm == redirect or path_norm.startswith(redirect + "/"):
            return True
    return False


@register.filter(name="readable")
def readable(value):
    try:
        value = value.replace("_", " ").replace("id", "").title()
    except:
        value = value
    return value
