"""
spring_verification/views.py
Dashboard and Candidate Data (Spring Verify API) views.
"""

import json
import os
from datetime import datetime

import requests
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _

from horilla.decorators import login_required

from .models import BGVCandidate


def _find_employee_by_email(email):
    """Return Employee for the given email (personal or work), or None."""
    if not email or not str(email).strip():
        return None
    from employee.models import Employee
    email_clean = str(email).strip().lower()
    return Employee.objects.filter(
        Q(email__iexact=email_clean) | Q(employee_work_info__email__iexact=email_clean)
    ).first()


def _parse_date(value):
    """Parse API date string to datetime or None."""
    if value is None:
        return None
    if hasattr(value, "year"):  # already date/datetime
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt, size in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:size], fmt)
        except (ValueError, TypeError):
            continue
    return None


def _sync_candidates_to_db(candidates):
    """Sync API candidate list to BGVCandidate and link to Employee by email."""
    for c in candidates:
        cid = c.get("candidate_id")
        if cid is None:
            continue
        email = (c.get("email") or "").strip() or None
        employee = _find_employee_by_email(email) if email else None
        BGVCandidate.objects.update_or_create(
            candidate_id=int(cid),
            defaults={
                "employee_id": employee.id if employee else None,
                "name": (c.get("name") or "")[:255],
                "email": (c.get("email") or "")[:254],
                "phone_number": (c.get("phone_number") or "")[:50],
                "overall_status": (c.get("overall_status") or "")[:100],
                "candidate_uuid": (c.get("candidate_uuid") or "")[:64],
                "initiation_date": _parse_date(c.get("initiation_date")),
                "completion_date": _parse_date(c.get("completion_date")),
                "report_url": (c.get("report_url") or "")[:500],
                "meta_data": c if isinstance(c, dict) else None,
            },
        )


# API base URL and token - prefer env; fallback to settings or default for development
SPRING_VERIFY_API_BASE = getattr(
    settings, "SPRING_VERIFY_API_BASE", "https://api-sa.in.springverify.com"
)
SPRING_VERIFY_API_TOKEN = getattr(
    settings,
    "SPRING_VERIFY_API_TOKEN",
    os.environ.get(
        "SPRING_VERIFY_API_TOKEN",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImNvbXBhbnlJZCI6NTc3OSwidG9rZW5JZCI6MTI0NSwiY29tcGFueVV1aWQiOiJjOWUzMDZhNC01OWQxLTQzMWMtODhkMi00MzY4NTFmMjU0ZDgifSwiaWF0IjoxNzcwMDQyMTIwfQ.QlwXX_61DVJ8lPfWVAe7K4MR9_DajVNkoTJWXkYhnus",
    ),
)


def _spring_verification_required(view_func):
    """Decorator: allow staff or users with BGV view permission."""
    def wrapped(request, *args, **kwargs):
        if request.user.is_staff:
            return view_func(request, *args, **kwargs)
        if request.user.has_perm("spring_verification.view_springverificationaccess"):
            return view_func(request, *args, **kwargs)
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden(_("You do not have permission to access BGV."))
    return wrapped


def _fetch_candidates(limit=100, offset=0):
    """Fetch candidate list from Spring Verify API. Returns (list, error_message)."""
    url = (
        f"{SPRING_VERIFY_API_BASE.rstrip('/')}/external/v1/candidate/details"
        f"?limit={limit}&offset={offset}"
    )
    headers = {"Authorization": f"Bearer {SPRING_VERIFY_API_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") and isinstance(data.get("data"), list):
            return data["data"], None
        return [], None
    except requests.RequestException as e:
        return [], str(e)
    except (ValueError, KeyError) as e:
        return [], str(e)


@login_required
@_spring_verification_required
def dashboard(request):
    """BGV dashboard with summary cards and status chart."""
    candidates, fetch_error = _fetch_candidates(limit=100, offset=0)
    if not fetch_error and candidates:
        try:
            _sync_candidates_to_db(candidates)
        except Exception:
            pass

    total = len(candidates)
    status_counts = {}
    for c in candidates:
        st = (c.get("overall_status") or _("Unknown")).strip() or _("Unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    # Sorted for chart and breakdown: list of (label, count) for template
    status_sorted = sorted(status_counts.items(), key=lambda x: -x[1])
    status_chart_labels = [str(s[0]) for s in status_sorted]
    status_chart_data = [s[1] for s in status_sorted]
    # Colours for pie chart (use a small palette)
    chart_colors = [
        "#4e73df", "#1cc88a", "#36b9cc", "#f6c23e", "#e74a3b",
        "#858796", "#5a5c69", "#2e59d9", "#17a673", "#2c9faf",
    ]
    status_chart_colors = [chart_colors[i % len(chart_colors)] for i in range(len(status_sorted))]

    # Top status for cards (e.g. "Awaiting Input", "Complete")
    awaiting = status_counts.get("Awaiting Input", 0)
    complete = sum(v for k, v in status_counts.items() if "complete" in (k or "").lower() or "completed" in (k or "").lower())

    context = {
        "total_candidates": total,
        "status_counts": status_counts,
        "status_breakdown": status_sorted,
        "awaiting_input": awaiting,
        "completed_count": complete,
        "status_chart_labels": json.dumps(status_chart_labels),
        "status_chart_data": json.dumps(status_chart_data),
        "status_chart_colors": json.dumps(status_chart_colors),
        "fetch_error": fetch_error,
    }
    return render(request, "spring_verification/dashboard.html", context)


def _filter_candidates(candidates, search, status):
    """Filter candidate list by search text and status."""
    if search:
        search_lower = search.strip().lower()
        if search_lower:
            def matches(c):
                return (
                    (c.get("name") or "").lower().find(search_lower) >= 0
                    or (c.get("email") or "").lower().find(search_lower) >= 0
                    or (c.get("phone_number") or "").lower().find(search_lower) >= 0
                    or (c.get("overall_status") or "").lower().find(search_lower) >= 0
                    or str(c.get("candidate_id") or "").find(search_lower) >= 0
                )
            candidates = [c for c in candidates if matches(c)]
    if status and status.strip():
        status_val = status.strip()
        candidates = [c for c in candidates if (c.get("overall_status") or "") == status_val]
    return candidates


@login_required
@_spring_verification_required
def candidate_data(request):
    """Fetch candidates from Spring Verify API and display in a table. Supports search and filter via GET."""
    limit = request.GET.get("limit", "50")
    offset = request.GET.get("offset", "0")
    search = request.GET.get("search", "").strip()
    status = request.GET.get("status", "").strip()

    url = (
        f"{SPRING_VERIFY_API_BASE.rstrip('/')}/external/v1/candidate/details"
        f"?limit={limit}&offset={offset}"
    )
    headers = {"Authorization": f"Bearer {SPRING_VERIFY_API_TOKEN}"}
    candidates = []
    error_message = None
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success") and isinstance(data.get("data"), list):
            candidates = data["data"]
    except requests.RequestException as e:
        error_message = _("Failed to load candidate data: %(error)s") % {"error": str(e)}
    except (ValueError, KeyError) as e:
        error_message = _("Invalid API response: %(error)s") % {"error": str(e)}

    # Sync to DB and link to employees by email (for showing BGV on employee profile)
    if not error_message and candidates:
        try:
            _sync_candidates_to_db(candidates)
        except Exception:
            pass  # do not break the page if sync fails
    # Unique statuses for filter dropdown (from fetched list before we apply search/status filter)
    status_choices = sorted(
        {c.get("overall_status") for c in candidates if c.get("overall_status")},
        key=lambda x: (x or "").lower(),
    )
    if not error_message and candidates:
        candidates = _filter_candidates(candidates, request.GET.get("search", ""), status)

    context = {
        "candidates": candidates,
        "error_message": error_message,
        "status_choices": status_choices,
        "search": request.GET.get("search", ""),
        "status_filter": status,
    }
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return render(request, "spring_verification/candidate_data_table.html", context)
    return render(request, "spring_verification/candidate_data.html", context)


@login_required
def employee_bgv_tab(request, emp_id):
    """HTMX fragment: BGV candidate data for an employee (for profile tab).
    Visible to: staff, users with BGV permission, or the employee viewing their own profile.
    For employee viewing own profile: Candidate ID and View report are hidden.
    """
    from employee.models import Employee
    employee = get_object_or_404(Employee, pk=emp_id)
    is_own_profile = employee.employee_user_id == request.user
    has_bgv_access = request.user.is_staff or request.user.has_perm(
        "spring_verification.view_springverificationaccess"
    )
    if not (is_own_profile or has_bgv_access):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden(_("You do not have permission to access this."))
    candidates = list(BGVCandidate.objects.filter(employee_id=emp_id).order_by("-initiation_date"))
    # Hide Candidate ID and Report when employee is viewing their own profile
    show_sensitive_fields = has_bgv_access
    context = {
        "employee": employee,
        "candidates": candidates,
        "show_sensitive_fields": show_sensitive_fields,
    }
    return render(request, "spring_verification/employee_bgv_tab.html", context)
