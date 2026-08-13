"""
filters.py

This page is used to register filter for employee models

"""

import django
import django_filters
from django import forms
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.utils.translation import gettext as _
from django_filters import CharFilter

# from attendance.models import Attendance
from accessibility.methods import check_is_accessible
from accessibility.models import DefaultAccessibility
from base.methods import filtersubordinatesemployeemodel
from base.models import (
    Company,
    Department,
    EmployeeShift,
    EmployeeType,
    JobPosition,
    WorkType,
)
from employee.models import DisciplinaryAction, Employee, EmployeeTag, Policy
from horilla.filters import FilterSet, HorillaFilterSet, filter_by_name
from horilla.horilla_middlewares import _thread_locals
from horilla_documents.models import Document


class EmployeeFilter(HorillaFilterSet):
    """
    Filter set class for Candidate model

    Args:
        FilterSet (class): custom filter set class to apply styling
    """

    search = django_filters.CharFilter(method="filter_by_name")
    search_field = django_filters.CharFilter(method="search_in")
    selected_search_field = django_filters.ChoiceFilter(
        label="Search Field",
        choices=[
            ("employee", _("Search in : Employee")),
            ("reporting_manager", _("Search in : Reporting manager")),
            ("department", _("Search in : Department")),
            ("job_position", _("Search in : Job Position")),
        ],
        method="filter_by_name_and_field",
        widget=forms.Select(
            attrs={
                "size": 4,
                "class": "oh-input__icon",
                "style": "border: none; overflow: hidden; display: flex; position: absolute; z-index: 999; margin-left:8%;",
                "onclick": "$('.filterButton')[0].click();",
            }
        ),
    )
    employee_first_name = django_filters.CharFilter(lookup_expr="icontains")
    employee_last_name = django_filters.CharFilter(lookup_expr="icontains")
    country = django_filters.CharFilter(lookup_expr="icontains")
    department = django_filters.CharFilter(
        field_name="employee_work_info__department_id__department",
        lookup_expr="icontains",
    )

    is_active = django_filters.ChoiceFilter(
        field_name="is_active",
        label="Is Active",
        choices=[
            (True, "Yes"),
            (False, "No"),
        ],
        method="filter_is_active",
    )

    is_from_onboarding = django_filters.ChoiceFilter(
        field_name="is_from_onboarding",
        label="Is From Onboarding",
        choices=[
            (True, "Yes"),
            (False, "No"),
        ],
    )
    is_directly_converted = django_filters.ChoiceFilter(
        field_name="is_directly_converted",
        label="Is Directly Converted",
        choices=[
            (True, "Yes"),
            (False, "No"),
        ],
    )
    probation_from = django_filters.DateFilter(
        field_name="candidate_get__probation_end",
        lookup_expr="gte",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    probation_till = django_filters.DateFilter(
        field_name="candidate_get__probation_end",
        lookup_expr="lte",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    not_in_yet = django_filters.DateFilter(
        method="not_in_yet_func",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    not_out_yet = django_filters.DateFilter(
        method="not_out_yet_func",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    # Work Info: explicit filters for related fields (cannot be in Meta.fields)
    employee_work_info__company_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Company.objects.all(),
        field_name="employee_work_info__company_id",
        label=_("Company"),
    )
    employee_work_info__department_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Department.objects.all(),
        field_name="employee_work_info__department_id",
        label=_("Department"),
    )
    employee_work_info__shift_id = django_filters.ModelMultipleChoiceFilter(
        queryset=EmployeeShift.objects.all(),
        field_name="employee_work_info__shift_id",
        label=_("Shift"),
    )
    employee_work_info__tags = django_filters.ModelMultipleChoiceFilter(
        queryset=EmployeeTag.objects.all(),
        field_name="employee_work_info__tags",
        label=_("Employee tag"),
    )
    employee_work_info__reporting_manager_id = django_filters.ModelMultipleChoiceFilter(
        queryset=Employee.objects.all(),
        field_name="employee_work_info__reporting_manager_id",
        label=_("Reporting Manager"),
    )
    employee_work_info__job_position_id = django_filters.ModelMultipleChoiceFilter(
        queryset=JobPosition.objects.all(),
        field_name="employee_work_info__job_position_id",
        label=_("Job Position"),
    )
    employee_work_info__work_type_id = django_filters.ModelMultipleChoiceFilter(
        queryset=WorkType.objects.all(),
        field_name="employee_work_info__work_type_id",
        label=_("Work Type"),
    )
    employee_work_info__employee_type_id = django_filters.ModelMultipleChoiceFilter(
        queryset=EmployeeType.objects.all(),
        field_name="employee_work_info__employee_type_id",
        label=_("Employee Type"),
    )
    # Advanced
    employee_user_id__groups = django_filters.ModelMultipleChoiceFilter(
        queryset=Group.objects.all(),
        field_name="employee_user_id__groups",
        label=_("Groups"),
    )
    employee_user_id__user_permissions = django_filters.ModelMultipleChoiceFilter(
        queryset=Permission.objects.all(),
        field_name="employee_user_id__user_permissions",
        label=_("Permissions"),
    )

    class Meta:
        """
        Meta class to add the additional info.
        Only direct Employee model field names allowed; related lookups are declared as explicit filters elsewhere.
        """

        model = Employee
        fields = [
            "employee_first_name",
            "employee_last_name",
            "email",
            "badge_id",
            "phone",
            "country",
            "gender",
            "is_active",
        ]

    def filter_is_active(self, queryset, name, value):
        """Coerce is_active filter value from string (e.g. GET 'False' or 'No') to boolean so filter works."""
        if value is None or value == "":
            return queryset
        # "No" / False: inactive employees
        if value in (False, "False", "false", "0", "No", "no"):
            return queryset.filter(is_active=False)
        # "Yes" / True: active employees
        if value in (True, "True", "true", "1", "Yes", "yes"):
            return queryset.filter(is_active=True)
        return queryset

    def not_in_yet_func(self, queryset, _, value):
        """
        The method to filter out the not check-in yet employees
        """

        # Getting the queryset for those employees dont have any attendance for the date
        # in value.

        queryset1 = queryset.exclude(
            employee_attendances__attendance_date=value,
        )
        queryset2 = queryset.filter(
            employee_attendances__attendance_date=value,
            employee_attendances__attendance_clock_out__isnull=False,
        )

        queryset = (queryset1 | queryset2).distinct()

        return queryset

    def not_out_yet_func(self, queryset, _, value):
        """
        The method to filter out the not check-in yet employees
        """

        # Getting the queryset for those employees dont have any attendance for the date
        # in value.
        queryset = queryset.filter(
            employee_attendances__attendance_date=value,
            employee_attendances__attendance_clock_out__isnull=True,
        )
        return queryset

    def filter_in_probation_period(self, queryset, name, value):
        """
        Filter employees in or not in probation (first 3 months after date_joining).
        Yes = in probation (date_joining within last 3 months).
        No = not in probation (no date_joining or joined 3+ months ago).
        """
        from django.db.models import Q
        from django.utils import timezone

        from dateutil.relativedelta import relativedelta

        if not value:
            return queryset
        today = timezone.now().date()
        # Joined after this date => still in probation
        probation_cutoff = today - relativedelta(months=3)

        if value == "yes":
            return queryset.filter(
                employee_work_info__date_joining__isnull=False,
                employee_work_info__date_joining__gt=probation_cutoff,
            ).distinct()
        if value == "no":
            return queryset.filter(
                Q(employee_work_info__date_joining__isnull=True)
                | Q(employee_work_info__date_joining__lte=probation_cutoff)
            ).distinct()
        return queryset

    def filter_queryset(self, queryset):
        """
        Override the default filtering behavior to handle None option and filter queryset for reporting manager.
        """
        from django.db.models import Q

        # Strip non-integer FK values (e.g. "T1") to avoid DataError before any query runs
        data = self.form.cleaned_data
        if data:
            fk_like_keys = [
                k for k in data
                if k.endswith("_id") or "__id" in k
                or k.split("__")[-1].replace("_id", "") in (
                    "work_type", "shift", "department", "job_position",
                    "company", "job_role", "reporting_manager", "employee_type",
                )
            ]
            for key in fk_like_keys:
                val = data.get(key)
                if val is None:
                    continue
                if isinstance(val, (list, django.db.models.query.QuerySet)):
                    safe = []
                    for v in val:
                        if v == "not_set":
                            safe.append(v)
                        else:
                            try:
                                int(v)
                                safe.append(v)
                            except (ValueError, TypeError):
                                pass
                    if safe != list(val):
                        data = data.copy() if data is self.form.cleaned_data else data
                        if safe:
                            data[key] = safe
                        else:
                            del data[key]
                else:
                    try:
                        int(val)
                    except (ValueError, TypeError):
                        data = data.copy() if data is self.form.cleaned_data else data
                        del data[key]
            if hasattr(data, "copy") and data is not self.form.cleaned_data:
                self.form.cleaned_data = data

        # Handle default accessibility and filter based on reporting manager

        request = getattr(_thread_locals, "request", None)
        if request:
            employee = getattr(request.user, "employee_get", None)
            cache_key = request.session.session_key + "accessibility_filter"
            accessible = check_is_accessible("employee_view", cache_key, employee)
            if not accessible and employee.reporting_manager.exists():
                queryset = filtersubordinatesemployeemodel(
                    request=request, queryset=queryset, perm="employee.view_employee"
                )

        # Apply normal filters first (department, working_today, etc.)
        try:
            queryset = super().filter_queryset(queryset)
        except Exception:
            # Invalid filter values (e.g. "T1" for integer FK) must not crash the view
            return queryset.model.objects.none()

        # Then apply 'not_set' constraints (narrow by fields that are null / chosen "not set")
        data = self.form.cleaned_data
        not_set_dict = {}
        for key, value in data.items():
            if isinstance(value, (list, django.db.models.query.QuerySet)):
                if value and "not_set" in value:
                    not_set_dict[key] = value

        if not_set_dict:
            for key, values in not_set_dict.items():
                key_q = Q()
                for value in values:
                    if value == "not_set":
                        key_q |= Q(**{f"{key}__isnull": True})
                    else:
                        key_q |= Q(**{key: value})
                queryset = queryset.filter(key_q)

        return queryset

    def filter_by_name(self, queryset, name, value):
        """
        Employee search method — name, badge ID, and email.
        """
        if self.data.get("search_field"):
            return queryset

        value = (value or "").strip()
        if not value:
            return queryset

        return queryset.filter(
            Q(employee_first_name__icontains=value)
            | Q(employee_last_name__icontains=value)
            | Q(badge_id__icontains=value)
            | Q(email__icontains=value)
        )


class EmployeeReGroup:
    """
    Class to keep the field name for group by option
    """

    fields = [
        ("", "select"),
        ("employee_work_info__job_position_id", "Job Position"),
        ("employee_work_info__department_id", "Department"),
        ("employee_work_info__shift_id", "Shift"),
        ("employee_work_info__work_type_id", "Work Type"),
        ("employee_work_info__job_role_id", "Job Role"),
        ("employee_work_info__reporting_manager_id", "Reporting Manager"),
        ("employee_work_info__company_id", "Company"),
    ]


class PolicyFilter(FilterSet):
    """
    PolicyFilter filterset class
    """

    search = django_filters.CharFilter(field_name="title", lookup_expr="icontains")

    class Meta:
        model = Policy
        fields = "__all__"


class DocumentRequestFilter(FilterSet):
    """
    Custom filter for Document Requests.
    """

    search = CharFilter(field_name="title", lookup_expr="icontains")

    class Meta:
        """
        A nested class that specifies the model and fields for the filter.
        """

        model = Document
        fields = [
            "employee_id",
            "document_request_id",
            "status",
            "employee_id__employee_first_name",
            "employee_id__employee_last_name",
            "employee_id__is_active",
            "employee_id__gender",
            "employee_id__employee_work_info__job_position_id",
            "employee_id__employee_work_info__department_id",
            "employee_id__employee_work_info__work_type_id",
            "employee_id__employee_work_info__employee_type_id",
            "employee_id__employee_work_info__job_role_id",
            "employee_id__employee_work_info__reporting_manager_id",
            "employee_id__employee_work_info__company_id",
            "employee_id__employee_work_info__shift_id",
        ]


class DisciplinaryActionFilter(FilterSet):
    """
    Custom filter for Disciplinary Action.

    """

    search = CharFilter(method=filter_by_name)

    start_date = django_filters.DateFilter(
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    class Meta:
        model = DisciplinaryAction
        ordering = ["-id"]
        fields = [
            "employee_id",
            "action",
            "employee_id__employee_work_info__job_position_id",
            "employee_id__employee_work_info__department_id",
            "employee_id__employee_work_info__work_type_id",
            "employee_id__employee_work_info__job_role_id",
            "employee_id__employee_work_info__reporting_manager_id",
            "employee_id__employee_work_info__company_id",
            "employee_id__employee_work_info__shift_id",
        ]
