"""
employee/context_processors.py

This module is used to write context processor methods
"""

import json
from datetime import date

from django import template
from django.apps import apps
from django.contrib import messages
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from base.backends import ConfiguredEmailBackend
from base.forms import MailTemplateForm
from base.methods import export_data, generate_pdf
from base.models import HorillaMailTemplate
from employee.filters import EmployeeFilter
from employee.models import Employee
from horilla import settings
from horilla.decorators import login_required, manager_can_enter


def paginator_qry(qryset, page_number):
    """
    This method is used to paginate query set
    """
    paginator = Paginator(qryset, 20)
    qryset = paginator.get_page(page_number)
    return qryset


@login_required
@manager_can_enter("employee.view_employee")
def not_in_yet(request):
    """
    Offline Employees: Teams presence preferred, else Slack, else attendance.
    """
    from employee.models import SlackPresence, TeamsPresence

    page_number = request.GET.get("page")
    previous_data = request.GET.urlencode()

    base_qs = EmployeeFilter({}).qs.filter(is_active=True)
    teams_linked = base_qs.filter(teams_user_id__isnull=False).exclude(teams_user_id="")
    use_teams = teams_linked.exists()
    slack_linked = base_qs.filter(slack_user_id__isnull=False).exclude(slack_user_id="")
    use_slack = (not use_teams) and slack_linked.exists()

    if use_teams:
        all_teams = list(teams_linked)
        teams_ids = [e.teams_user_id for e in all_teams]
        presences = {
            p.teams_user_id: p.presence
            for p in TeamsPresence.objects.filter(teams_user_id__in=teams_ids)
        }
        emps = [e for e in all_teams if presences.get(e.teams_user_id) != "active"]
        for e in emps:
            e.slack_status = "Offline"
        emps = sorted(emps, key=lambda e: e.get_full_name() or "")
    elif use_slack:
        all_slack = list(slack_linked)
        slack_ids = [e.slack_user_id for e in all_slack]
        presences = {
            p.slack_user_id: p.presence
            for p in SlackPresence.objects.filter(slack_user_id__in=slack_ids)
        }
        emps = [e for e in all_slack if presences.get(e.slack_user_id) != "active"]
        for e in emps:
            e.slack_status = "Offline"
        emps = sorted(emps, key=lambda e: e.get_full_name() or "")
    else:
        emps = (
            EmployeeFilter({"not_in_yet": date.today()})
            .qs.exclude(employee_work_info__isnull=True)
            .filter(is_active=True)
        )

    return render(
        request,
        "dashboard/not_in_yet.html",
        {
            "employees": paginator_qry(emps, page_number),
            "pd": previous_data,
        },
    )


@login_required
@manager_can_enter("employee.view_employee")
def not_out_yet(request):
    """
    Online Employees: Teams presence preferred, else Slack, else attendance.
    """
    from employee.models import SlackPresence, TeamsPresence

    base_qs = EmployeeFilter({}).qs.filter(is_active=True)
    teams_linked = base_qs.filter(teams_user_id__isnull=False).exclude(teams_user_id="")
    use_teams = teams_linked.exists()
    slack_linked = base_qs.filter(slack_user_id__isnull=False).exclude(slack_user_id="")
    use_slack = (not use_teams) and slack_linked.exists()

    if use_teams:
        emps = list(teams_linked)
        teams_ids = [e.teams_user_id for e in emps]
        presences = {
            p.teams_user_id: p.presence
            for p in TeamsPresence.objects.filter(teams_user_id__in=teams_ids)
        }
        for emp in emps:
            emp.slack_status = (
                "Online" if presences.get(emp.teams_user_id) == "active" else "Offline"
            )
        emps = [e for e in emps if e.slack_status == "Online"]
        emps = sorted(emps, key=lambda e: e.get_full_name() or "")
    elif use_slack:
        emps = list(slack_linked)
        slack_ids = [e.slack_user_id for e in emps]
        presences = {
            p.slack_user_id: p.presence
            for p in SlackPresence.objects.filter(slack_user_id__in=slack_ids)
        }
        for emp in emps:
            emp.slack_status = (
                "Online" if presences.get(emp.slack_user_id) == "active" else "Offline"
            )
        emps = [e for e in emps if e.slack_status == "Online"]
        emps = sorted(emps, key=lambda e: e.get_full_name() or "")
    else:
        # Fallback: attendance-based "not out yet" = still at work → Online
        emps = list(
            EmployeeFilter({"not_out_yet": date.today()})
            .qs.filter(is_active=True)
            .exclude(employee_work_info__isnull=True)
        )
        for emp in emps:
            emp.slack_status = "Online"
    return render(request, "dashboard/not_out_yet.html", {"employees": emps})


@login_required
@manager_can_enter("employee.change_employee")
def send_mail(request, emp_id=None):
    """
    This method used send mail to the employees
    """
    employee = None
    if emp_id:
        employee = Employee.objects.get(id=emp_id)
    employees = Employee.objects.all()
    templates = HorillaMailTemplate.objects.all()
    return render(
        request,
        "employee/send_mail.html",
        {
            "employee": employee,
            "templates": templates,
            "employees": employees,
            "searchWords": MailTemplateForm().get_employee_template_language(),
        },
    )


@login_required
@manager_can_enter("employee.change_employee")
def employee_data_export(request, emp_id=None):
    """
    This method used send mail to the employees
    """

    resolver_match = request.resolver_match
    if (
        resolver_match
        and resolver_match.url_name
        and resolver_match.url_name == "export-data-employee"
    ):
        employee = None
        if emp_id:
            employee = Employee.objects.get(id=emp_id)

        context = {"employee": employee}

        # IF LEAVE IS INSTALLED
        if apps.is_installed("leave"):
            from leave.filters import LeaveRequestFilter
            from leave.forms import LeaveRequestExportForm

            excel_column = LeaveRequestExportForm()
            export_filter = LeaveRequestFilter()
            context.update(
                {
                    "leave_excel_column": excel_column,
                    "leave_export_filter": export_filter.form,
                }
            )

        # IF ATTENDANCE IS INSTALLED
        if apps.is_installed("attendance"):
            from attendance.filters import AttendanceFilters
            from attendance.forms import AttendanceExportForm
            from attendance.models import Attendance

            excel_column = AttendanceExportForm()
            export_filter = AttendanceFilters()
            context.update(
                {
                    "attendance_excel_column": excel_column,
                    "attendance_export_filter": export_filter.form,
                }
            )

        # IF PAYROLL IS INSTALLED
        if apps.is_installed("payroll"):
            from payroll.filters import PayslipFilter
            from payroll.forms.component_forms import PayslipExportColumnForm

            context.update(
                {
                    "payroll_export_column": PayslipExportColumnForm(),
                    "payroll_export_filter": PayslipFilter(request.GET),
                }
            )

        return render(request, "employee/export_data_employee.html", context=context)
    return export_data(
        request=request,
        model=Attendance,
        filter_class=AttendanceFilters,
        form_class=AttendanceExportForm,
        file_name="Attendance_export",
    )


@login_required
def get_template(request, emp_id):
    """
    This method is used to return the mail template
    """
    body = HorillaMailTemplate.objects.get(id=emp_id).body
    return JsonResponse({"body": body})


@login_required
def get_mail_preview(request):
    """
    This method is used to return the mail template
    """
    body = request.GET.get("body")
    template_bdy = template.Template(body)
    emp_id = request.GET.get("emp_id")
    if emp_id:
        employee = Employee.objects.get(id=emp_id)
        context = template.Context(
            {
                "instance": employee,
                "self": request.user.employee_get,
                "request": request,
            }
        )
        body = template_bdy.render(context) or " "
    return JsonResponse({"body": body})


@login_required
@manager_can_enter(perm="recruitment.change_employee")
def send_mail_to_employee(request):
    """
    This method is used to send acknowledgement mail to the candidate
    """
    employee_id = request.POST["id"]
    subject = request.POST.get("subject")
    bdy = request.POST.get("body")

    employee_ids = request.POST.getlist("employees")
    employees = Employee.objects.filter(id__in=employee_ids)

    other_attachments = request.FILES.getlist("other_attachments")

    if employee_id:
        employee_obj = Employee.objects.filter(id=employee_id)
    else:
        employee_obj = Employee.objects.none()
    employees = (employees | employee_obj).distinct()

    template_attachment_ids = request.POST.getlist("template_attachments")
    for employee in employees:
        bodys = list(
            HorillaMailTemplate.objects.filter(
                id__in=template_attachment_ids
            ).values_list("body", flat=True)
        )
        attachments = [
            (file.name, file.read(), file.content_type) for file in other_attachments
        ]
        for html in bodys:
            # due to not having solid template we first need to pass the context
            template_bdy = template.Template(html)
            context = template.Context(
                {"instance": employee, "self": request.user.employee_get}
            )
            render_bdy = template_bdy.render(context)
            attachments.append(
                (
                    "Document",
                    generate_pdf(render_bdy, {}, path=False, title="Document").content,
                    "application/pdf",
                )
            )

        template_bdy = template.Template(bdy)
        context = template.Context(
            {"instance": employee, "self": request.user.employee_get}
        )
        render_bdy = template_bdy.render(context)
        send_to_mail = (
            employee.employee_work_info.email
            if employee.employee_work_info and employee.employee_work_info.email
            else employee.email
        )

        email = EmailMessage(
            subject=subject,
            body=render_bdy,
            to=[send_to_mail],
        )
        email.content_subtype = "html"

        email.attachments = attachments
        try:
            email.send()
            if employee.employee_work_info.email or employee.email:
                messages.success(request, f"Mail sent to {employee.get_full_name()}")
            else:
                messages.info(request, f"Email not set for {employee.get_full_name()}")
        except Exception as e:
            messages.error(request, "Something went wrong")
    return HttpResponse("<script>window.location.reload()</script>")
