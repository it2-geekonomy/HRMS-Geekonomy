"""
Views for Closers Fellowship applications submitted from the website form.
"""

from datetime import datetime

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from horilla.decorators import any_permission_required, login_required
from recruitment.models import ClosersFellowshipApplication
from recruitment.views.paginator_qry import paginator_qry


def _filter_params(request):
    return {
        "search": (request.GET.get("search") or "").strip(),
        "seat": (request.GET.get("seat") or "").strip(),
        "campaign": (request.GET.get("campaign") or "").strip(),
        "utm_source": (request.GET.get("utm_source") or "").strip(),
        "date_from": (request.GET.get("date_from") or "").strip(),
        "date_to": (request.GET.get("date_to") or "").strip(),
    }


def _apply_filters(queryset, params):
    search = params["search"]
    if search:
        queryset = queryset.filter(
            Q(full_name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
        )
    if params["seat"]:
        queryset = queryset.filter(seat=params["seat"])
    if params["campaign"]:
        queryset = queryset.filter(utm_campaign=params["campaign"])
    if params["utm_source"]:
        queryset = queryset.filter(utm_source=params["utm_source"])
    if params["date_from"]:
        try:
            date_from = datetime.strptime(params["date_from"], "%Y-%m-%d").date()
            queryset = queryset.filter(created_at__date__gte=date_from)
        except ValueError:
            pass
    if params["date_to"]:
        try:
            date_to = datetime.strptime(params["date_to"], "%Y-%m-%d").date()
            queryset = queryset.filter(created_at__date__lte=date_to)
        except ValueError:
            pass
    return queryset


def _distinct_values(field_name):
    return (
        ClosersFellowshipApplication.objects.exclude(**{f"{field_name}__isnull": True})
        .exclude(**{field_name: ""})
        .values_list(field_name, flat=True)
        .distinct()
        .order_by(field_name)
    )


@login_required
@any_permission_required(
    perms=[
        "recruitment.view_closersfellowshipapplication",
        "recruitment.view_candidate",
    ]
)
def closers_fellowship_list(request):
    """List all Closers Fellowship applications."""
    params = _filter_params(request)
    applications = _apply_filters(
        ClosersFellowshipApplication.objects.all().order_by("-created_at"),
        params,
    )
    query_params = request.GET.copy()
    query_params.pop("page", None)
    has_filters = any(params.values())
    return render(
        request,
        "closers_fellowship/closers_fellowship_list.html",
        {
            "data": paginator_qry(applications, request.GET.get("page")),
            "filters": params,
            "has_filters": has_filters,
            "query_string": query_params.urlencode(),
            "seat_options": _distinct_values("seat"),
            "campaign_options": _distinct_values("utm_campaign"),
            "utm_source_options": _distinct_values("utm_source"),
        },
    )


@login_required
@any_permission_required(
    perms=[
        "recruitment.view_closersfellowshipapplication",
        "recruitment.view_candidate",
    ]
)
def closers_fellowship_detail(request, app_id):
    """View a single Closers Fellowship application."""
    application = get_object_or_404(ClosersFellowshipApplication, id=app_id)
    return render(
        request,
        "closers_fellowship/closers_fellowship_detail.html",
        {"application": application},
    )


@login_required
@any_permission_required(
    perms=[
        "recruitment.delete_closersfellowshipapplication",
        "recruitment.delete_candidate",
    ]
)
@require_http_methods(["POST"])
def closers_fellowship_delete(request, app_id):
    """Delete a Closers Fellowship application."""
    application = get_object_or_404(ClosersFellowshipApplication, id=app_id)
    name = application.full_name
    application.delete()
    messages.success(request, _("Application for %(name)s deleted.") % {"name": name})
    return redirect(reverse("closers-fellowship-list"))
