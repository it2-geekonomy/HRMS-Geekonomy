"""
Public CRM API: employee list and summary counts for CRM integration.
Authenticated via API key (X-API-Key or Authorization: Api-Key <key>).
"""

import os
from datetime import timedelta
from types import SimpleNamespace

from django.core.paginator import InvalidPage
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import AuthenticationFailed, NotFound

from base.models import Department
from employee.models import Employee

from ...api_serializers.crm.serializers import (
    CRMDepartmentSerializer,
    CRMEmployeeSerializer,
)


def get_crm_api_key():
    """CRM API key from environment (set CRM_API_KEY in .env)."""
    return os.environ.get("CRM_API_KEY", "").strip()


def request_has_valid_api_key(request):
    """Check X-API-Key header, Authorization: Api-Key <key>, or query param (X-API-Key / api_key)."""
    key = get_crm_api_key()
    if not key:
        return False
    header_key = request.META.get("HTTP_X_API_KEY", "").strip()
    if header_key and header_key == key:
        return True
    auth = request.META.get("HTTP_AUTHORIZATION", "").strip()
    if auth.lower().startswith("api-key "):
        return auth[7:].strip() == key
    # Query param: try common names (some clients normalize to lowercase)
    query_key = (
        request.GET.get("X-API-Key")
        or request.GET.get("api_key")
        or request.GET.get("x-api-key")
        or ""
    ).strip()
    if query_key and query_key == key:
        return True
    return False


class IsCRMApiKey(BasePermission):
    """Allow only requests with valid CRM_API_KEY. Returns 401 when key is missing or invalid."""

    def has_permission(self, request, view):
        key = get_crm_api_key()
        if not key:
            raise AuthenticationFailed("CRM API key is not configured.")
        if not request_has_valid_api_key(request):
            raise AuthenticationFailed("Invalid or missing API key. Use X-API-Key header or Authorization: Api-Key <key>.")
        return True


class CRMPagination(PageNumberPagination):
    """CRM list pagination: ?page=1&page_size=50 (page_size optional; max 200)."""

    page_query_param = "page"
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class CRMDepartmentsPagination(CRMPagination):
    """
    Same as CRMPagination, but page beyond the last returns 200 with an empty
    departments list (instead of 404 Invalid page). Headers still show true totals.
    """

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        paginator = self.django_paginator_class(queryset, page_size)
        page_number = self.get_page_number(request, paginator)

        try:
            self.page = paginator.page(page_number)
        except InvalidPage as exc:
            try:
                pn = int(page_number)
            except (TypeError, ValueError):
                msg = self.invalid_page_message.format(
                    page_number=page_number, message=str(exc)
                )
                raise NotFound(msg) from exc
            if pn < 1:
                msg = self.invalid_page_message.format(
                    page_number=page_number, message=str(exc)
                )
                raise NotFound(msg) from exc
            if paginator.num_pages > 0 and pn > paginator.num_pages:
                self.page = SimpleNamespace(number=pn, paginator=paginator)
                return []
            msg = self.invalid_page_message.format(
                page_number=page_number, message=str(exc)
            )
            raise NotFound(msg) from exc

        if paginator.num_pages > 1 and self.template is not None:
            self.display_page_controls = True

        return list(self.page)


class CRMDashboardView(APIView):
    """
    Public CRM API: summary counts and employee list.

    GET /api/crm/
    Headers: X-API-Key: <your-CRM_API_KEY>   (or Authorization: Api-Key <key>)

    Response:
      - summary: active_employees_count, inactive_employees_count, new_hires_count
      - employees: list of { id, name, email, department, job_position, joining_date, reporting_manager, is_active }

    Query params:
      - active_only: if "true", list only active employees
      - new_hire_days: number of days for "new hire" (default 90)
      - page, page_size: pagination (optional)
    """

    permission_classes = [IsCRMApiKey]
    pagination_class = CRMPagination

    # Badge IDs to exclude from CRM API (e.g. internal/test accounts)
    CRM_EXCLUDE_BADGE_IDS = []

    def get(self, request):
        # Use .entire() to bypass company filter (no request user company)
        all_employees = Employee.objects.entire()
        # Exclude specific employees (e.g. Arjun Sindhia GEEKY0001) from CRM data
        all_employees = all_employees.exclude(badge_id__in=self.CRM_EXCLUDE_BADGE_IDS)
        active_only = request.query_params.get("active_only", "").lower() == "true"
        new_hire_days = 90
        try:
            new_hire_days = max(1, int(request.query_params.get("new_hire_days", 90)))
        except ValueError:
            pass

        cutoff = timezone.now().date() - timedelta(days=new_hire_days)

        # Summary counts (from same base queryset, excluding excluded badge IDs)
        active_count = all_employees.filter(is_active=True).count()
        inactive_count = all_employees.filter(is_active=False).count()
        new_hires_count = all_employees.filter(
            is_active=True,
            employee_work_info__date_joining__gte=cutoff,
        ).count()

        # Employee list: optional active filter (already excludes CRM_EXCLUDE_BADGE_IDS)
        qs = all_employees.select_related(
            "employee_work_info",
            "employee_work_info__department_id",
            "employee_work_info__job_position_id",
            "employee_work_info__reporting_manager_id",
        )
        if active_only:
            qs = qs.filter(is_active=True)
        qs = qs.order_by("id")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = CRMEmployeeSerializer(page, many=True, context={"request": request})

        return Response({
            "summary": {
                "active_employees_count": active_count,
                "inactive_employees_count": inactive_count,
                "new_hires_count": new_hires_count,
            },
            "employees": serializer.data,
            "pagination": {
                "page": paginator.page.number,
                "page_size": paginator.page.paginator.per_page,
                "total_count": paginator.page.paginator.count,
                "total_pages": paginator.page.paginator.num_pages,
            } if page is not None else None,
        })


class CRMDepartmentsView(APIView):
    """
    Public CRM API: all departments (for picklists / sync with CRM).

    GET /api/crm/departments/
    Headers: X-API-Key: <your-CRM_API_KEY>   (or Authorization: Api-Key <key>)

    Response JSON:
      - departments: list of { id, name }

    Pagination (when paginator applies) is in response headers:
      - X-Pagination-Page
      - X-Pagination-Page-Size
      - X-Pagination-Total-Count
      - X-Pagination-Total-Pages

    Query params:
      - company_id: if set, only departments linked to this company (Horilla M2M)
      - active_only: if "true", only departments with is_active=True
      - page: page number (default 1), e.g. ?page=2
      - page_size: items per page (default 50, max 200), e.g. ?page_size=20
        If page is past the last page, departments is [] and headers show real totals.
    """

    permission_classes = [IsCRMApiKey]
    pagination_class = CRMDepartmentsPagination

    def get(self, request):
        qs = Department.objects.entire().prefetch_related("department_teams").order_by("department", "id")
        if request.query_params.get("active_only", "").lower() == "true":
            qs = qs.filter(is_active=True)
        company_id = request.query_params.get("company_id")
        if company_id is not None and str(company_id).strip() != "":
            try:
                cid = int(company_id)
            except ValueError:
                return Response(
                    {"detail": "company_id must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(company_id=cid)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = CRMDepartmentSerializer(page, many=True)

        response = Response({"departments": serializer.data})
        if page is not None:
            p = paginator.page
            response["X-Pagination-Page"] = str(p.number)
            response["X-Pagination-Page-Size"] = str(p.paginator.per_page)
            response["X-Pagination-Total-Count"] = str(p.paginator.count)
            response["X-Pagination-Total-Pages"] = str(p.paginator.num_pages)
        return response
