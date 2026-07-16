"""
Offboarding report with month-wise filtering.
"""

from calendar import month_name
from datetime import date

from django.apps import apps
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

if apps.is_installed("offboarding"):

    from base.models import Company
    from horilla.decorators import login_required
    from offboarding.filters import LetterFilter
    from offboarding.models import OffboardingEmployee, ResignationLetter
    from offboarding.templatetags.offboarding_filter import (
        any_manager,
        is_offboarding_employee,
    )

    RESIGNATION_STATUS = {
        "requested": "Requested",
        "approved": "Approved",
        "rejected": "Rejected",
    }

    def _can_access_offboarding_report(request):
        """Use same access logic as Offboarding sidebar so report matches tab access."""
        user = request.user
        if user.has_perm("offboarding.view_resignationletter") or user.has_perm(
            "offboarding.view_offboarding"
        ):
            return True
        if user.has_module_perms("offboarding"):
            return True
        try:
            employee = user.employee_get
            if any_manager(employee) or is_offboarding_employee(employee):
                return True
        except Exception:
            pass
        return False

    @login_required
    def offboarding_report(request):
        if not _can_access_offboarding_report(request):
            from django.contrib import messages

            messages.info(request, "You dont have permission.")
            previous_url = request.META.get("HTTP_REFERER", "/")
            script = f'<script>window.location.href = "{previous_url}"</script>'
            return HttpResponse(script)
        company = "all"
        selected_company = request.session.get("selected_company")
        if selected_company != "all":
            company = Company.objects.filter(id=selected_company).first()

        today = date.today()
        months = [(i, month_name[i]) for i in range(1, 13)]
        years = list(range(today.year, today.year - 6, -1))

        return render(
            request,
            "report/offboarding_report.html",
            {
                "company": company,
                "form": LetterFilter().form,
                "months": months,
                "years": years,
                "current_month": today.month,
                "current_year": today.year,
            },
        )

    @login_required
    def offboarding_pivot(request):
        if not _can_access_offboarding_report(request):
            return JsonResponse({"error": "Permission denied"}, status=403)
        model_type = request.GET.get("model", "resignation_letters")
        month = request.GET.get("month")
        year = request.GET.get("year")

        today = date.today()
        if not month or not year:
            month = today.month
            year = today.year
        else:
            try:
                month = int(month)
                year = int(year)
            except (TypeError, ValueError):
                month = today.month
                year = today.year

        if model_type == "resignation_letters":
            qs = ResignationLetter.objects.filter(
                planned_to_leave_on__month=month,
                planned_to_leave_on__year=year,
            )
            letter_filter = LetterFilter(request.GET, queryset=qs)
            qs = letter_filter.qs

            data = list(
                qs.values(
                    "employee_id__employee_first_name",
                    "employee_id__employee_last_name",
                    "employee_id__email",
                    "employee_id__phone",
                    "employee_id__gender",
                    "title",
                    "description",
                    "planned_to_leave_on",
                    "status",
                    "created_at",
                    "employee_id__employee_work_info__department_id__department",
                    "employee_id__employee_work_info__job_position_id__job_position",
                    "employee_id__employee_work_info__job_role_id__job_role",
                    "employee_id__employee_work_info__company_id__company",
                )
            )
            choice_gender = {"male": "Male", "female": "Female", "other": "Other"}
            data_list = [
                {
                    "Name": f"{item['employee_id__employee_first_name'] or ''} {item['employee_id__employee_last_name'] or ''}".strip(),
                    "Gender": choice_gender.get(item["employee_id__gender"], "-"),
                    "Email": item["employee_id__email"] or "-",
                    "Phone": item["employee_id__phone"] or "-",
                    "Department": item[
                        "employee_id__employee_work_info__department_id__department"
                    ]
                    or "-",
                    "Job Position": item[
                        "employee_id__employee_work_info__job_position_id__job_position"
                    ]
                    or "-",
                    "Job Role": item[
                        "employee_id__employee_work_info__job_role_id__job_role"
                    ]
                    or "-",
                    "Title": item["title"] or "-",
                    "Planned to leave on": item["planned_to_leave_on"],
                    "Status": RESIGNATION_STATUS.get(item["status"], item["status"]),
                    "Requested on": str(item["created_at"].date())
                    if item["created_at"]
                    else "-",
                    "Company": item[
                        "employee_id__employee_work_info__company_id__company"
                    ]
                    or "-",
                }
                for item in data
            ]

        elif model_type == "exit_process":
            qs = OffboardingEmployee.objects.filter(
                notice_period_starts__month=month,
                notice_period_starts__year=year,
            )
            from offboarding.filters import PipelineEmployeeFilter

            pipeline_filter = PipelineEmployeeFilter(request.GET, queryset=qs)
            qs = pipeline_filter.qs

            data = list(
                qs.values(
                    "employee_id__employee_first_name",
                    "employee_id__employee_last_name",
                    "employee_id__email",
                    "employee_id__phone",
                    "employee_id__gender",
                    "notice_period_starts",
                    "notice_period_ends",
                    "notice_period",
                    "unit",
                    "stage_id__title",
                    "stage_id__offboarding_id__title",
                    "created_at",
                    "employee_id__employee_work_info__department_id__department",
                    "employee_id__employee_work_info__job_position_id__job_position",
                    "employee_id__employee_work_info__company_id__company",
                )
            )
            choice_gender = {"male": "Male", "female": "Female", "other": "Other"}
            data_list = [
                {
                    "Name": f"{item['employee_id__employee_first_name'] or ''} {item['employee_id__employee_last_name'] or ''}".strip(),
                    "Gender": choice_gender.get(item["employee_id__gender"], "-"),
                    "Email": item["employee_id__email"] or "-",
                    "Phone": item["employee_id__phone"] or "-",
                    "Department": item[
                        "employee_id__employee_work_info__department_id__department"
                    ]
                    or "-",
                    "Job Position": item[
                        "employee_id__employee_work_info__job_position_id__job_position"
                    ]
                    or "-",
                    "Stage": item["stage_id__title"] or "-",
                    "Offboarding": item["stage_id__offboarding_id__title"] or "-",
                    "Notice starts": item["notice_period_starts"],
                    "Notice ends": item["notice_period_ends"],
                    "Notice period": f"{item['notice_period'] or '-'} {item['unit'] or ''}".strip(),
                    "Company": item[
                        "employee_id__employee_work_info__company_id__company"
                    ]
                    or "-",
                }
                for item in data
            ]
        else:
            data_list = []

        return JsonResponse(data_list, safe=False)
