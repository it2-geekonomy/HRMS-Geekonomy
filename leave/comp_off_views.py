"""Views for Comp-Off requests."""

import contextlib
import json
from urllib.parse import parse_qs

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from notifications.signals import notify

from base.methods import (
    get_key_instances,
    paginator_qry,
    sortby,
)
from base.templatetags.basefilters import is_leave_approval_manager, is_reportingmanager
from horilla.decorators import hx_request_required, login_required
from leave.decorators import comp_off_approve_permission, comp_off_change_permission
from leave.filters import CompOffRequestFilter
from leave.forms import (
    CompOffRequestApproveForm,
    CompOffRequestForm,
    CompOffRequestRejectForm,
)
from leave.threading import (
    send_comp_off_approve_reject_email,
    send_comp_off_email,
)
from leave.models import CompOffRequest


def _comp_off_full_access(request):
    """Staff/superuser HR view — same scope as leave list for users with global view perm."""
    user = request.user
    return user.is_superuser or (
        user.is_staff and user.has_perm("leave.view_compoffrequest")
    )


def _can_view_team_comp_off_requests(request):
    user = request.user
    return (
        _comp_off_full_access(request)
        or is_leave_approval_manager(user)
        or is_reportingmanager(user)
    )


def _team_comp_off_queryset(request, get_data):
    """
    Reporting managers see only direct subordinates (same as leave/attendance).
    Do not grant full list access from view_compoffrequest alone — that permission
    is often assigned too broadly on employee roles.
    """
    queryset = CompOffRequestFilter(get_data).qs.order_by("-id")
    if _comp_off_full_access(request):
        return queryset
    manager = getattr(request.user, "employee_get", None)
    if not manager:
        return queryset.none()
    return queryset.filter(
        employee_id__employee_work_info__reporting_manager_id=manager
    )


def _can_view_comp_off_request_detail(request, comp_off_request, my_request=False):
    if my_request:
        return comp_off_request.employee_id == request.user.employee_get
    if _comp_off_full_access(request):
        return True
    if comp_off_request.employee_id == request.user.employee_get:
        return True
    return comp_off_request.reporting_manager() == request.user.employee_get


def _notify_reporting_manager(request, comp_off_request):
    reporting_manager = comp_off_request.reporting_manager()
    if not reporting_manager or not reporting_manager.employee_user_id:
        return
    with contextlib.suppress(Exception):
        notify.send(
            request.user.employee_get,
            recipient=reporting_manager.employee_user_id,
            verb="You have a new Comp-Off request to validate.",
            icon="people-circle",
            redirect=reverse("comp-off-request-view") + f"?id={comp_off_request.id}",
        )


def _notify_employee(request, comp_off_request, verb):
    with contextlib.suppress(Exception):
        notify.send(
            request.user.employee_get,
            recipient=comp_off_request.employee_id.employee_user_id,
            verb=verb,
            icon="people-circle",
            redirect=reverse("my-comp-off-request-view") + f"?id={comp_off_request.id}",
        )


@login_required
def my_comp_off_request_view(request):
    employee = request.user.employee_get
    queryset = CompOffRequest.objects.filter(employee_id=employee.id).order_by("-id")
    comp_off_filter = CompOffRequestFilter(request.GET, queryset=queryset)
    page_obj = paginator_qry(comp_off_filter.qs, request.GET.get("page"))
    request_ids = json.dumps(list(page_obj.object_list.values_list("id", flat=True)))
    previous_data = request.GET.urlencode()
    return render(
        request,
        "leave/comp_off_request/my_comp_off_request_view.html",
        {
            "comp_off_requests": page_obj,
            "form": comp_off_filter.form,
            "pd": previous_data,
            "request_ids": request_ids,
        },
    )


@login_required
@hx_request_required
def my_comp_off_request_filter(request):
    employee = request.user.employee_get
    queryset = CompOffRequest.objects.filter(employee_id=employee.id).order_by("-id")
    comp_off_filter = CompOffRequestFilter(request.GET, queryset=queryset)
    if request.GET.get("sortby"):
        queryset = sortby(request, comp_off_filter.qs, "sortby")
    else:
        queryset = comp_off_filter.qs
    page_obj = paginator_qry(queryset, request.GET.get("page"))
    request_ids = json.dumps(list(page_obj.object_list.values_list("id", flat=True)))
    previous_data = request.GET.urlencode()
    return render(
        request,
        "leave/comp_off_request/my_comp_off_requests.html",
        {
            "comp_off_requests": page_obj,
            "pd": previous_data,
            "request_ids": request_ids,
        },
    )


@login_required
def comp_off_request_view(request):
    if not _can_view_team_comp_off_requests(request):
        messages.info(request, _("You dont have permission."))
        return redirect(reverse("my-comp-off-request-view"))
    get_data = request.GET.copy()
    if "status" not in get_data:
        get_data.setdefault("status", "requested")
    queryset = _team_comp_off_queryset(request, get_data)
    page_obj = paginator_qry(queryset, request.GET.get("page"))
    request_ids = json.dumps(list(page_obj.object_list.values_list("id", flat=True)))
    previous_data = request.GET.urlencode()
    data_dict = parse_qs(previous_data)
    data_dict = get_key_instances(CompOffRequest, data_dict)
    return render(
        request,
        "leave/comp_off_request/comp_off_request_view.html",
        {
            "comp_off_requests": page_obj,
            "form": CompOffRequestFilter(get_data).form,
            "pd": previous_data,
            "filter_dict": data_dict,
            "request_ids": request_ids,
        },
    )


@login_required
@hx_request_required
def comp_off_request_filter(request):
    if not _can_view_team_comp_off_requests(request):
        return HttpResponse(status=403)
    get_data = request.GET.copy()
    queryset = _team_comp_off_queryset(request, get_data)
    if request.GET.get("sortby"):
        queryset = sortby(request, queryset, "sortby")
    page_obj = paginator_qry(queryset, request.GET.get("page"))
    request_ids = json.dumps(list(page_obj.object_list.values_list("id", flat=True)))
    previous_data = request.GET.urlencode()
    data_dict = parse_qs(previous_data)
    data_dict = get_key_instances(CompOffRequest, data_dict)
    return render(
        request,
        "leave/comp_off_request/comp_off_requests.html",
        {
            "comp_off_requests": page_obj,
            "pd": previous_data,
            "filter_dict": data_dict,
            "request_ids": request_ids,
        },
    )


@login_required
@hx_request_required
def comp_off_request_create(request):
    employee = request.user.employee_get
    form = CompOffRequestForm()
    if request.method == "POST":
        form = CompOffRequestForm(request.POST)
        if form.is_valid():
            comp_off_request = form.save(commit=False)
            comp_off_request.employee_id = employee
            comp_off_request.created_by = employee
            comp_off_request.status = "requested"
            comp_off_request.save()
            messages.success(request, _("Comp-Off request created successfully."))
            _notify_reporting_manager(request, comp_off_request)
            send_comp_off_email(request, comp_off_request, "request")
            return HttpResponse("<script>window.location.reload();</script>")
    return render(
        request,
        "leave/comp_off_request/comp_off_form.html",
        {"form": form, "pd": request.GET.urlencode()},
    )


@login_required
@hx_request_required
@comp_off_change_permission()
def comp_off_request_update(request, req_id):
    comp_off_request = get_object_or_404(CompOffRequest, id=req_id)
    if comp_off_request.status != "requested":
        messages.error(request, _("Only requested Comp-Off requests can be edited."))
        return HttpResponse("<script>window.location.reload();</script>")
    form = CompOffRequestForm(instance=comp_off_request)
    if request.method == "POST":
        form = CompOffRequestForm(request.POST, instance=comp_off_request)
        if form.is_valid():
            form.save()
            messages.success(request, _("Comp-Off request updated successfully."))
            return HttpResponse("<script>window.location.reload();</script>")
    return render(
        request,
        "leave/comp_off_request/comp_off_form.html",
        {"form": form, "pd": request.GET.urlencode(), "edit": True},
    )


@login_required
@hx_request_required
@comp_off_change_permission()
def comp_off_request_delete(request, req_id):
    comp_off_request = get_object_or_404(CompOffRequest, id=req_id)
    if comp_off_request.status == "approved":
        messages.error(request, _("Approved Comp-Off requests cannot be deleted."))
        return HttpResponse("<script>window.location.reload();</script>")
    comp_off_request.delete()
    messages.success(request, _("Comp-Off request deleted successfully."))
    return HttpResponse("<script>window.location.reload();</script>")


@login_required
@hx_request_required
@comp_off_approve_permission()
def comp_off_request_approve(request, req_id):
    comp_off_request = get_object_or_404(CompOffRequest, id=req_id)
    if comp_off_request.status != "requested":
        messages.error(request, _("This Comp-Off request cannot be approved."))
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))
    form = CompOffRequestApproveForm(
        initial={"approved_days": comp_off_request.requested_days}
    )
    if request.method == "POST":
        form = CompOffRequestApproveForm(request.POST)
        if form.is_valid():
            approved_days = form.cleaned_data["approved_days"]
            comp_off_request.approved_days = approved_days
            comp_off_request.status = "approved"
            comp_off_request.save()
            comp_off_request.credit_comp_off_balance(approved_days)
            messages.success(request, _("Comp-Off request approved successfully."))
            _notify_employee(
                request,
                comp_off_request,
                "Your Comp-Off request has been approved.",
            )
            send_comp_off_approve_reject_email(request, comp_off_request, approved=True)
            return HttpResponse("<script>window.location.reload();</script>")
    return render(
        request,
        "leave/comp_off_request/comp_off_approve_form.html",
        {"form": form, "req_id": req_id, "comp_off_request": comp_off_request},
    )


@login_required
@hx_request_required
@comp_off_approve_permission()
def comp_off_request_reject(request, req_id):
    comp_off_request = get_object_or_404(CompOffRequest, id=req_id)
    if comp_off_request.status not in ("requested", "approved"):
        messages.error(request, _("This Comp-Off request cannot be rejected."))
        return HttpResponse("<script>window.location.reload();</script>")
    form = CompOffRequestRejectForm()
    if request.method == "POST":
        form = CompOffRequestRejectForm(request.POST)
        if form.is_valid():
            if comp_off_request.status == "approved":
                comp_off_request.debit_comp_off_balance()
            comp_off_request.reject_reason = form.cleaned_data["reason"]
            comp_off_request.status = "rejected"
            comp_off_request.save()
            messages.success(request, _("Comp-Off request rejected successfully."))
            _notify_employee(
                request,
                comp_off_request,
                "Your Comp-Off request has been rejected.",
            )
            send_comp_off_approve_reject_email(request, comp_off_request, approved=False)
            return HttpResponse("<script>window.location.reload();</script>")
    return render(
        request,
        "leave/comp_off_request/comp_off_reject_form.html",
        {"form": form, "req_id": req_id},
    )


@login_required
@hx_request_required
def comp_off_request_cancel(request, req_id):
    comp_off_request = get_object_or_404(CompOffRequest, id=req_id)
    if comp_off_request.employee_id != request.user.employee_get:
        messages.error(request, _("You can only cancel your own Comp-Off requests."))
        return HttpResponse("<script>window.location.reload();</script>")
    if comp_off_request.status != "requested":
        messages.error(request, _("Only requested Comp-Off requests can be cancelled."))
        return HttpResponse("<script>window.location.reload();</script>")
    comp_off_request.status = "cancelled"
    comp_off_request.save()
    messages.success(request, _("Comp-Off request cancelled successfully."))
    send_comp_off_email(request, comp_off_request, "cancel")
    return HttpResponse("<script>window.location.reload();</script>")


@login_required
@hx_request_required
def comp_off_request_single_view(request, req_id):
    from base.methods import closest_numbers

    comp_off_request = get_object_or_404(CompOffRequest, id=req_id)
    my_request = request.GET.get("my_request") == "True"
    if not _can_view_comp_off_request_detail(request, comp_off_request, my_request=my_request):
        messages.error(request, _("Permission denied."))
        return HttpResponse("<script>window.location.reload();</script>")
    previous_id = next_id = None
    instances_ids_json = request.GET.get("instances_ids")
    if instances_ids_json:
        try:
            requests_ids = json.loads(instances_ids_json)
            previous_id, next_id = closest_numbers(requests_ids, req_id)
        except (json.JSONDecodeError, TypeError, ValueError):
            instances_ids_json = None
    return render(
        request,
        "leave/comp_off_request/comp_off_single_view.html",
        {
            "comp_off_request": comp_off_request,
            "my_request": my_request,
            "instances_ids": instances_ids_json,
            "previous": previous_id,
            "next": next_id,
        },
    )
