"""
requests.py

This module is used to register the endpoints to the attendance requests
"""

import copy
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, time
from types import SimpleNamespace
from urllib.parse import parse_qs

from django.contrib import messages
from django.utils.dateparse import parse_date, parse_time
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import CharField, ProtectedError, Q, Value
from django.db.models.functions import Concat, Trim
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from attendance.filters import AttendanceFilters, AttendanceRequestReGroup
from attendance.threading import (
    send_attendance_request_approved_emails,
    send_attendance_request_emails,
    send_attendance_request_rejected_emails,
)
from attendance.forms import (
    AttendanceExportForm,
    AttendanceRequestForm,
    BatchAttendanceForm,
    BulkAttendanceRequestForm,
    NewRequestForm,
)
from attendance.methods.utils import (
    get_diff_dict,
    get_employee_last_name,
    paginator_qry,
    parse_attendance_requested_data,
    recalculate_worked_hour_from_clock,
    shift_schedule_today,
)
from attendance.models import (
    Attendance,
    AttendanceActivity,
    AttendanceLateComeEarlyOut,
    AttendanceRequestLog,
    BatchAttendance,
)
from attendance.views.clock_in_out import early_out, late_come
from base.methods import (
    choosesubordinates,
    closest_numbers,
    eval_validate,
    export_data,
    filtersubordinates,
    filtersubordinatesemployeemodel,
    get_key_instances,
    get_pagination,
    is_reportingmanager,
)
from base.models import EmailLog, EmployeeShift, EmployeeShiftDay
from employee.models import Employee
from horilla.decorators import (
    hx_request_required,
    login_required,
    manager_can_enter,
    permission_required,
)
from notifications.signals import notify

logger = logging.getLogger(__name__)


def _coerce_requested_data_for_orm_update(requested_data):
    """serialize() uses '' for optional FKs; QuerySet.update may fail or mis-apply with ''."""
    data = dict(requested_data)
    for key in ("shift_id", "work_type_id", "batch_attendance_id"):
        if data.get(key) == "":
            data[key] = None
    for tkey in ("attendance_clock_in", "attendance_clock_out"):
        v = data.get(tkey)
        if v == "None":
            data[tkey] = None
            continue
        if v is None or v == "":
            continue
        if isinstance(v, str):
            parsed = parse_time(v.strip())
            if parsed is not None:
                data[tkey] = parsed
    for dkey in ("attendance_date", "attendance_clock_in_date", "attendance_clock_out_date"):
        v = data.get(dkey)
        if v == "None":
            data[dkey] = None
            continue
        if v is None or v == "":
            continue
        if isinstance(v, str):
            parsed = parse_date(v.strip())
            if parsed is not None:
                data[dkey] = parsed
    return data


def _reporting_manager_user(employee):
    """
    User record for the employee's reporting manager, or None if not set or manager has no login.
    django-notifications requires a non-null recipient_id.
    """
    if employee is None:
        return None
    ewi = getattr(employee, "employee_work_info", None)
    if ewi is None:
        return None
    rm = getattr(ewi, "reporting_manager_id", None)
    if rm is None:
        return None
    return getattr(rm, "employee_user_id", None)


def _parse_attendance_date_fragment(raw: str):
    """Parse a date string as it appears in attendance approval email subjects."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        from dateutil import parser as dateutil_parser

        return dateutil_parser.parse(raw, dayfirst=True).date()
    except Exception:
        return None


def _parse_attendance_date_from_owner_approval_subject(subject: str):
    """
    Parse date from subject used in threading._send_attendance_outcome_emails_sync:
    "Your attendance request for {attendance_date} has been approved"
    """
    if not subject:
        return None
    subject = subject.strip()
    m = re.match(
        r"^Your attendance request for\s+(.+?)\s+has been approved\.?\s*$",
        subject,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    return _parse_attendance_date_fragment(m.group(1))


def _parse_employee_and_date_from_by_name_approval_subject(subject: str):
    """
    Manager/HR copy from threading: "Attendance request by {name} for {date} has been approved"
    """
    if not subject:
        return None, None
    subject = subject.strip()
    m = re.match(
        r"^Attendance request by\s+(.+?)\s+for\s+(.+?)\s+has been approved\.?\s*$",
        subject,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None, None
    name_part = m.group(1).strip()
    att_date = _parse_attendance_date_fragment(m.group(2))
    return name_part, att_date


def _normalize_email_log_to(raw):
    """EmailLog.to should be a single address; tolerate legacy list-like strings."""
    if raw is None or raw == "":
        return ""
    if isinstance(raw, (list, tuple)) and raw:
        raw = raw[0]
    s = str(raw).strip()
    if s.startswith("[") and "]" in s:
        inner = s.strip("[]").strip()
        if inner.startswith(("'", '"')):
            try:
                import ast

                parsed = ast.literal_eval(s)
                if isinstance(parsed, (list, tuple)) and parsed:
                    s = str(parsed[0]).strip()
            except (SyntaxError, ValueError, TypeError):
                pass
    if "<" in s and ">" in s:
        m = re.search(r"<([^>]+)>", s)
        if m:
            s = m.group(1).strip()
    return s.lower()


def _employee_name_lookup_maps():
    """Maps for resolving employee from approval email subject (manager/HR copy)."""
    by_full = defaultdict(list)
    by_first_last = defaultdict(list)
    qs = (
        Employee.objects.filter(is_active=True)
        .select_related("employee_work_info")
        .annotate(
            _fn=Trim(
                Concat(
                    Trim("employee_first_name"),
                    Value(" ", output_field=CharField()),
                    Trim("employee_last_name"),
                    output_field=CharField(),
                )
            )
        )
    )
    for emp in qs:
        fn = (getattr(emp, "_fn", None) or "").strip()
        if fn:
            by_full[fn.lower()].append(emp)
        first = (emp.employee_first_name or "").strip()
        last = (emp.employee_last_name or "").strip()
        if first and last:
            by_first_last[(first.lower(), last.lower())].append(emp)
    return by_full, by_first_last


def _resolve_employee_from_subject_name(name_part, by_full, by_first_last):
    if not name_part:
        return None
    name_part = " ".join(name_part.split())
    if not name_part:
        return None
    lst = by_full.get(name_part.lower())
    if lst:
        return lst[0]
    parts = name_part.split()
    if len(parts) >= 2:
        key = (parts[0].lower(), parts[-1].lower())
        lst = by_first_last.get(key)
        if lst:
            return lst[0]
    return None


def _employee_from_recipient_email(addr: str):
    if not addr:
        return None
    addr = _normalize_email_log_to(addr)
    if not addr:
        return None
    return (
        Employee.objects.filter(is_active=True)
        .filter(Q(email__iexact=addr) | Q(employee_work_info__email__iexact=addr))
        .select_related("employee_work_info")
        .first()
    )


def _employee_visible_for_attendance_logs(request, employee) -> bool:
    if request.user.has_perm("attendance.view_attendance"):
        return True
    if employee.employee_user_id_id == request.user.id:
        return True
    vis = filtersubordinatesemployeemodel(
        request,
        Employee.objects.filter(pk=employee.pk),
        "attendance.view_attendance",
    )
    return vis.filter(pk=employee.pk).exists()


def _plain_text_from_html_fragment(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _parse_approver_from_approval_email_body(body: str):
    """
    Threading approval copy: "... has been approved by {approver_name}."
    """
    plain = _plain_text_from_html_fragment(body or "")
    m = re.search(r"approved\s+by\s+(.+?)(?:\.(?:\s|$)|$)", plain, flags=re.IGNORECASE)
    if not m:
        return None
    name = m.group(1).strip()
    return name or None


def _approver_display_for_email_recovery_row(attendance_pk, body: str):
    parsed = _parse_approver_from_approval_email_body(body or "")
    if parsed:
        return parsed
    if not attendance_pk:
        return None
    log = (
        AttendanceRequestLog.objects.filter(
            action=AttendanceRequestLog.ACTION_APPROVED,
            attendance_id_id=attendance_pk,
            performed_by__isnull=False,
        )
        .select_related("performed_by")
        .order_by("-performed_at")
        .first()
    )
    if not log or not log.performed_by:
        return None
    u = log.performed_by
    return u.get_full_name() or u.get_username() or u.email


def _log_attendance_request_action(
    employee_id,
    action,
    request_user,
    attendance=None,
    description="",
    employee_request_note="",
    requested_data_snapshot=None,
    attendance_snapshot=None,
):
    """Create an AttendanceRequestLog entry for requested/approved/rejected/edited."""
    if attendance is not None:
        if requested_data_snapshot is None:
            requested_data_snapshot = parse_attendance_requested_data(
                getattr(attendance, "requested_data", None)
            )
        if attendance_snapshot is None:
            try:
                attendance_snapshot = attendance.serialize()
            except Exception:
                attendance_snapshot = None
    AttendanceRequestLog.objects.create(
        employee_id=employee_id,
        attendance_id=attendance,
        action=action,
        performed_by=request_user,
        description=(description[:2000] if description else ""),
        employee_request_note=(employee_request_note[:4000] if employee_request_note else ""),
        requested_data_snapshot=requested_data_snapshot,
        attendance_snapshot=attendance_snapshot,
    )


@login_required
def get_all_attendances_for_request_view(request):
    """Same queryset as the 'All Attendances' tab on request-attendance-view."""
    attendances = filtersubordinates(
        request=request,
        perm="attendance.view_attendance",
        queryset=Attendance.objects.all(),
    )
    attendances = attendances | Attendance.objects.filter(
        employee_id__employee_user_id=request.user
    )
    return attendances.distinct()


@login_required
def request_attendance_export(request):
    """
    Export All Attendances (request-attendance-view) to Excel with date range
    and selectable columns.
    """
    if (
        request.resolver_match
        and request.resolver_match.url_name == "request-attendance-export-form"
    ):
        return render(
            request,
            "requests/attendance/export_filter.html",
            {"export_form": AttendanceExportForm()},
        )
    date_from = request.GET.get("attendance_date__gte")
    date_to = request.GET.get("attendance_date__lte")
    if not date_from or not date_to:
        messages.error(
            request,
            _("Please select both 'Date from' and 'Date to' for export."),
        )
        return redirect(reverse("request-attendance-view") + "?tab=all")
    return export_data(
        request=request,
        model=Attendance,
        filter_class=AttendanceFilters,
        form_class=AttendanceExportForm,
        file_name="All_Attendances_export",
        base_queryset=get_all_attendances_for_request_view(request),
    )


def request_attendance(request):
    """
    This method is used to render template to register new attendance for a normal user
    """
    if request.GET.get("previous_url"):
        form = AttendanceRequestForm(initial=request.GET.dict())
    else:
        form = AttendanceRequestForm()
    if request.method == "POST":
        form = AttendanceRequestForm(request.POST)
        if form.is_valid():
            instance = form.save(commit=False)
            instance.save()
    return render(request, "requests/attendance/form.html", {"form": form})


@login_required
def request_attendance_view(request):
    """
    This method is used to view the attendances for to request
    """
    requests = Attendance.objects.filter(
        is_validate_request=True,
    )
    requests = filtersubordinates(
        request=request,
        perm="attendance.view_attendance",
        queryset=requests,
    )
    requests = requests | Attendance.objects.filter(
        employee_id__employee_user_id=request.user,
        is_validate_request=True,
    )
    requests = AttendanceFilters(request.GET, requests).qs
    previous_data = request.GET.urlencode()
    data_dict = parse_qs(previous_data)
    get_key_instances(Attendance, data_dict)

    keys_to_remove = [key for key, value in data_dict.items() if value == ["unknown"]]
    for key in keys_to_remove:
        data_dict.pop(key)
    attendances = get_all_attendances_for_request_view(request)
    attendances = AttendanceFilters(request.GET, attendances).qs
    filter_obj = AttendanceFilters()
    check_attendance = Attendance.objects.all()
    if check_attendance.exists():
        template = "requests/attendance/view-requests.html"
    else:
        template = "requests/attendance/requests_empty.html"
    requests_ids = json.dumps(
        [instance.id for instance in paginator_qry(requests, None).object_list]
    )
    attendances_ids = json.dumps(
        [instance.id for instance in paginator_qry(attendances, None).object_list]
    )
    requests = requests.filter(
        employee_id__is_active=True,
    )
    return render(
        request,
        template,
        {
            "requests": paginator_qry(requests, None),
            "attendances": paginator_qry(attendances, None),
            "requests_ids": requests_ids,
            "attendances_ids": attendances_ids,
            "f": filter_obj,
            "filter_dict": data_dict,
            "gp_fields": AttendanceRequestReGroup.fields,
        },
    )


@login_required
@hx_request_required
def request_new(request):
    """
    This method is used to create new attendance requests
    """

    if request.GET.get("bulk") and eval_validate(request.GET.get("bulk")):
        employee = request.user.employee_get
        if request.GET.get("employee_id"):
            form = BulkAttendanceRequestForm(initial=request.GET)
        else:
            form = BulkAttendanceRequestForm(initial={"employee_id": employee})
        if request.method == "POST":
            form = BulkAttendanceRequestForm(request.POST)
            form.instance.attendance_clock_in_date = request.POST.get("from_date")
            form.instance.attendance_date = request.POST.get("from_date")
            if form.is_valid():
                instance = form.save(commit=False)
                messages.success(request, _("Attendance request created"))
                return HttpResponse(
                    render(
                        request,
                        "requests/attendance/request_new_form.html",
                        {"form": form},
                    ).content.decode("utf-8")
                    + "<script>location.reload();</script>"
                )
        return render(
            request,
            "requests/attendance/request_new_form.html",
            {"form": form, "bulk": True},
        )
    if request.GET.get("employee_id"):
        initial = request.GET.dict()
    else:
        initial = {}
    # Pre-fill from existing attendance when attendance_id is passed (e.g. from My Attendances row click)
    attendance_id = request.GET.get("attendance_id")
    if attendance_id:
        try:
            att = Attendance.objects.get(id=attendance_id, employee_id__employee_user_id=request.user)
            initial["employee_id"] = att.employee_id.id
            initial["attendance_date"] = att.attendance_date.strftime("%Y-%m-%d")
            initial["attendance_clock_in"] = att.attendance_clock_in.strftime("%H:%M") if att.attendance_clock_in else ""
            initial["attendance_clock_out"] = (
                att.attendance_clock_out.strftime("%H:%M") if att.attendance_clock_out else ""
            )
        except (Attendance.DoesNotExist, ValueError):
            pass
    initial["_employee_form"] = True
    form = NewRequestForm(initial=initial)
    form = choosesubordinates(request, form, "attendance.change_attendance")
    form.fields["employee_id"].queryset = form.fields[
        "employee_id"
    ].queryset | Employee.objects.filter(employee_user_id=request.user)
    form.fields["employee_id"].initial = request.user.employee_get.id
    if request.method == "POST":
        # Non-bulk is always employee form: Shift, Worked Hours, Min hour are optional
        post_initial = {"_employee_form": True}
        form = NewRequestForm(request.POST, initial=post_initial)
        form = choosesubordinates(request, form, "attendance.change_attendance")
        form.fields["employee_id"].queryset = form.fields[
            "employee_id"
        ].queryset | Employee.objects.filter(employee_user_id=request.user)
        if form.is_valid():
            if form.new_instance is not None:
                attendance = form.new_instance
                attendance.save()
                _log_attendance_request_action(
                    attendance.employee_id,
                    AttendanceRequestLog.ACTION_REQUESTED,
                    request.user,
                    attendance=attendance,
                    description=_("Attendance request for %(date)s") % {"date": attendance.attendance_date},
                    employee_request_note=(attendance.request_description or "").strip(),
                )
                # Send notification to reporting manager when new attendance request is created
                reporting_manager = _reporting_manager_user(attendance.employee_id)
                if reporting_manager:
                    user_last_name = get_employee_last_name(attendance)
                    actor = getattr(request.user, "employee_get", None) or request.user
                    notify_kw = dict(
                        verb=f"{attendance.employee_id.employee_first_name} {user_last_name}'s attendance request for {attendance.attendance_date} is created",
                        verb_ar=f"تم إنشاء طلب الحضور لـ {attendance.employee_id.employee_first_name} {user_last_name} في {attendance.attendance_date}",
                        verb_de=f"Die Anwesenheitsanfrage von {attendance.employee_id.employee_first_name} {user_last_name} für den {attendance.attendance_date} wurde erstellt",
                        verb_es=f"Se ha creado la solicitud de asistencia de {attendance.employee_id.employee_first_name} {user_last_name} para el {attendance.attendance_date}",
                        verb_fr=f"La demande de présence de {attendance.employee_id.employee_first_name} {user_last_name} pour le {attendance.attendance_date} a été créée",
                        redirect=reverse("request-attendance-view") + f"?id={attendance.id}",
                        icon="checkmark-circle-outline",
                    )
                    if actor == request.user:
                        notify_kw["label"] = request.user.get_full_name() or request.user.username
                    notify.send(actor, recipient=reporting_manager, **notify_kw)
                
                # Email: reporting manager, their manager, HR (runs in request thread so backend gets config)
                try:
                    send_attendance_request_emails(request, attendance, is_update_request=False)
                except Exception as e:
                    logger.exception("Attendance request email failed: %s", e)
                messages.success(request, _("New attendance request created"))
                return HttpResponse(
                    render(
                        request,
                        "requests/attendance/request_new_form.html",
                        {"form": form},
                    ).content.decode("utf-8")
                    + "<script>location.reload();</script>"
                )
            # Updated existing attendance (form set new_instance=None, updated_attendance=attendance)
            updated_attendance = getattr(form, "updated_attendance", None)
            if updated_attendance is not None:
                _log_attendance_request_action(
                    updated_attendance.employee_id,
                    AttendanceRequestLog.ACTION_REQUESTED,
                    request.user,
                    attendance=updated_attendance,
                    description=_("Update request for %(date)s") % {"date": updated_attendance.attendance_date},
                    employee_request_note=(updated_attendance.request_description or "").strip(),
                )
                try:
                    send_attendance_request_emails(request, updated_attendance, is_update_request=True)
                except Exception as e:
                    logger.exception("Attendance request email failed (update): %s", e)
            messages.success(request, _("Update request updated"))
            return HttpResponse(
                render(
                    request,
                    "requests/attendance/request_new_form.html",
                    {"form": form},
                ).content.decode("utf-8")
                + "<script>location.reload();</script>"
            )
    return render(
        request,
        "requests/attendance/request_new_form.html",
        {"form": form, "bulk": False},
    )


@login_required
def create_batch_attendance(request):
    form = BatchAttendanceForm()
    previous_form_data = request.GET.urlencode()
    previous_url = request.GET.get("previous_url")
    # Split the string at "?" and extract the first part, then reattach the "?"
    previous_url = previous_url.split("?")[0] + "?"
    if "attendance-update" in previous_url:
        hx_target = "#updateAttendanceModalBody"
    elif "edit-validate-attendance" in previous_url:
        hx_target = "#editValidateAttendanceRequestModalBody"
    elif "request-attendance" in previous_url:
        hx_target = "#objectUpdateModalTarget"
    elif "attendance-create" in previous_url:
        hx_target = "#addAttendanceModalBody"
    else:
        hx_target = "#objectCreateModalTarget"
    if request.method == "POST":
        form = BatchAttendanceForm(request.POST)
        if form.is_valid():
            batch = form.save()
            messages.success(request, _("Attendance batch created successfully."))
            previous_form_data += f"&batch_attendance_id={batch.id}"
    return render(
        request,
        "attendance/attendance/batch_attendance_form.html",
        {
            "form": form,
            "previous_form_data": previous_form_data,
            "previous_url": previous_url,
            "hx_target": hx_target,
        },
    )


@login_required
def get_batches(request):
    batches = BatchAttendance.objects.all()
    return render(
        request, "attendance/attendance/batches_list.html", {"batches": batches}
    )


@login_required
def update_title(request):
    batch_id = request.POST.get("batch_id")
    try:
        batch = BatchAttendance.objects.filter(id=batch_id).first()
        if (
            request.user.has_perm("attendance.change_attendancegeneralsettings")
            or request.user == batch.created_by
        ):
            title = request.POST.get("title")
            batch.title = title
            batch.save()
            messages.success(request, _("Batch attendance title updated sucessfully."))
        else:
            messages.info(request, _("You don't have permission."))
    except:
        messages.error(request, _("Something went wrong."))
    return redirect(reverse("get-batches"))


@login_required
@permission_required("attendance.delete_batchattendance")
def delete_batch(request, batch_id):
    try:
        batch_name = BatchAttendance.objects.filter(id=batch_id).first().__str__()
        BatchAttendance.objects.filter(id=batch_id).first().delete()
        messages.success(
            request, _(f"{batch_name} - batch has been deleted sucessfully")
        )
    except ProtectedError as e:
        model_verbose_names_set = set()
        for obj in e.protected_objects:
            # Convert the lazy translation proxy to a string.
            model_verbose_names_set.add(str(_(obj._meta.verbose_name.capitalize())))
        model_names_str = ", ".join(model_verbose_names_set)
        messages.error(
            request,
            _("This {} is already in use for {}.").format(batch_name, model_names_str),
        ),
    except:
        messages.error(request, _("Something went wrong."))

    return redirect(reverse("get-batches"))


@login_required
def attendance_request_changes(request, attendance_id):
    """
    This method is used to store the requested changes to the instance
    """
    attendance = Attendance.objects.get(id=attendance_id)
    if request.GET.get("previous_url"):
        form = AttendanceRequestForm(initial=request.GET.dict())
    else:
        form = AttendanceRequestForm(instance=attendance, simplified_update=True)
    if request.method == "POST":
        form = AttendanceRequestForm(
            request.POST, instance=copy.copy(attendance), simplified_update=True
        )
        if form.is_valid():
            # commit already set to False
            # so the changes not affected to the db
            instance = form.save()
            instance.employee_id = attendance.employee_id
            instance.id = attendance.id
            if attendance.request_type != "create_request":
                attendance.requested_data = json.dumps(instance.serialize())
                attendance.request_description = instance.request_description
                # set the user level validation here
                attendance.is_validate_request = True
                attendance.save()
            else:
                instance.is_validate_request_approved = False
                instance.is_validate_request = True
                instance.save()
            _log_attendance_request_action(
                attendance.employee_id,
                AttendanceRequestLog.ACTION_REQUESTED,
                request.user,
                attendance=attendance,
                description=_("Update request for %(date)s") % {"date": attendance.attendance_date},
                employee_request_note=(attendance.request_description or "").strip(),
            )
            messages.success(request, _("Attendance update request created."))
            employee = attendance.employee_id
            reporting_manager = _reporting_manager_user(employee)
            if reporting_manager:
                user_last_name = get_employee_last_name(attendance)
                actor = getattr(request.user, "employee_get", None) or request.user
                notify_kw = dict(
                    verb=f"{employee.employee_first_name} {user_last_name}'s attendance update request for {attendance.attendance_date} is created",
                    verb_ar=f"تم إنشاء طلب تحديث الحضور لـ {employee.employee_first_name} {user_last_name} في {attendance.attendance_date}",
                    verb_de=f"Die Anfrage zur Aktualisierung der Anwesenheit von {employee.employee_first_name} {user_last_name} für den {attendance.attendance_date} wurde erstellt",
                    verb_es=f"Se ha creado la solicitud de actualización de asistencia para {employee.employee_first_name} {user_last_name} el {attendance.attendance_date}",
                    verb_fr=f"La demande de mise à jour de présence de {employee.employee_first_name} {user_last_name} pour le {attendance.attendance_date} a été créée",
                    redirect=reverse("request-attendance-view") + f"?id={attendance.id}",
                    icon="checkmark-circle-outline",
                )
                if actor == request.user:
                    notify_kw["label"] = request.user.get_full_name() or request.user.username
                notify.send(actor, recipient=reporting_manager, **notify_kw)
            # Email: reporting manager, their manager, HR (runs in request thread so backend gets config)
            try:
                send_attendance_request_emails(request, attendance, is_update_request=True)
            except Exception:
                pass  # do not block response if email fails
            return HttpResponse(
                render(
                    request,
                    "requests/attendance/form.html",
                    {"form": form, "attendance_id": attendance_id},
                ).content.decode("utf-8")
                + "<script>location.reload();</script>"
            )
    return render(
        request,
        "requests/attendance/form.html",
        {"form": form, "attendance_id": attendance_id},
    )


@login_required
def validate_attendance_request(request, attendance_id):
    """
    This method to validate the requested attendance
    args:
        attendance_id : attendance id
    """
    attendance = Attendance.objects.get(id=attendance_id)
    first_dict = attendance.serialize()
    empty_data = {
        "employee_id": None,
        "attendance_date": None,
        "attendance_clock_in_date": None,
        "attendance_clock_in": None,
        "attendance_clock_out": None,
        "attendance_clock_out_date": None,
        "shift_id": None,
        "work_type_id": None,
        "attendance_worked_hour": None,
        "batch_attendance_id": None,
    }
    if attendance.request_type == "create_request":
        other_dict = first_dict
        first_dict = empty_data
    else:
        other_dict = parse_attendance_requested_data(attendance.requested_data) or {}
    requests_ids_json = request.GET.get("requests_ids")
    previous_instance_id = next_instance_id = attendance.pk
    if requests_ids_json:
        previous_instance_id, next_instance_id = closest_numbers(
            json.loads(requests_ids_json), attendance_id
        )
    # Show Approve/Edit only for others' requests (not own)
    can_approve = (
        (is_reportingmanager(request) or request.user.has_perm("attendance.change_attendance"))
        and getattr(attendance.employee_id, "employee_user_id", None) != request.user
    )
    # Exclude Worked Hours and Batch Attendance from the diff
    diff_data = get_diff_dict(
        first_dict,
        other_dict,
        Attendance,
        exclude_fields=["attendance_worked_hour", "batch_attendance_id"],
    )
    # Always show Date and Day (current vs requested)
    def format_date(d):
        if not d or d == "None":
            return d or "-"
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").strftime("%d %b %Y")
        except (ValueError, TypeError):
            return str(d)

    def format_day(d):
        if not d or d == "None":
            return d or "-"
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").strftime("%A")
        except (ValueError, TypeError):
            return str(d)

    current_date = first_dict.get("attendance_date")
    requested_date = other_dict.get("attendance_date")
    data = {
        _("Date"): (format_date(current_date), format_date(requested_date)),
        _("Day"): (format_day(current_date), format_day(requested_date)),
        **diff_data,
    }
    no_biometric_data = attendance.request_type == "create_request"
    return render(
        request,
        "requests/attendance/individual_view.html",
        {
            "data": data,
            "attendance": attendance,
            "previous": previous_instance_id,
            "next": next_instance_id,
            "requests_ids": requests_ids_json,
            "can_approve_attendance": can_approve,
            "no_biometric_data": no_biometric_data,
        },
    )


@login_required
@manager_can_enter("attendance.change_attendance")
@transaction.atomic
def approve_validate_attendance_request(request, attendance_id):
    """
    This method is used to validate the attendance requests.
    Reporting managers cannot approve their own request; only their manager can.
    """
    attendance = Attendance.objects.get(id=attendance_id)
    if getattr(request.user, "employee_get", None) and attendance.employee_id_id == request.user.employee_get.id:
        error_msg = _(
            "You cannot approve your own attendance request. Your reporting manager must approve it."
        )
        messages.error(request, error_msg)
        if request.headers.get("HX-Request"):
            return render(
                request,
                "requests/attendance/validate_response.html",
                {"message": error_msg},
            )
        return redirect(reverse("request-attendance-view"))
    approval_employee_note = (attendance.request_description or "").strip()
    prev_attendance_date = attendance.attendance_date
    prev_attendance_clock_in_date = attendance.attendance_clock_in_date
    prev_attendance_clock_in = attendance.attendance_clock_in
    attendance.attendance_validated = True
    attendance.is_validate_request_approved = True
    attendance.is_validate_request = False
    attendance.request_description = None
    attendance.save()
    if attendance.requested_data is not None:
        requested_data = parse_attendance_requested_data(attendance.requested_data)
        if requested_data:
            requested_data = _coerce_requested_data_for_orm_update(requested_data)
            if requested_data.get("attendance_clock_out") == "None":
                requested_data["attendance_clock_out"] = None
            if requested_data.get("attendance_clock_out_date") == "None":
                requested_data["attendance_clock_out_date"] = None
            # Use entire() to bypass company scoping; otherwise updates can silently
            # no-op when selected_company/session filter doesn't match.
            Attendance.objects.entire().filter(id=attendance_id).update(**requested_data)
            attendance = Attendance.objects.get(id=attendance_id)
            recalculate_worked_hour_from_clock(attendance)
            attendance.save()
            # Explicitly trigger the signal to update WorkRecords after approval
            from attendance.signals import attendance_post_save as _attendance_sync_work_record
            _attendance_sync_work_record(sender=Attendance, instance=attendance, created=False)

    if (
        attendance.attendance_clock_out is None
        or attendance.attendance_clock_out_date is None
    ):
        attendance.attendance_validated = True
        activity = AttendanceActivity.objects.filter(
            employee_id=attendance.employee_id,
            attendance_date=prev_attendance_date,
            clock_in_date=prev_attendance_clock_in_date,
            clock_in=prev_attendance_clock_in,
        )
        if activity:
            activity.update(
                employee_id=attendance.employee_id,
                attendance_date=attendance.attendance_date,
                clock_in_date=attendance.attendance_clock_in_date,
                clock_in=attendance.attendance_clock_in,
            )

        else:
            AttendanceActivity.objects.create(
                employee_id=attendance.employee_id,
                attendance_date=attendance.attendance_date,
                clock_in_date=attendance.attendance_clock_in_date,
                clock_in=attendance.attendance_clock_in,
            )

    # Create late come or early out objects
    shift = attendance.shift_id
    day = attendance.attendance_date.strftime("%A").lower()
    day = EmployeeShiftDay.objects.get(day=day)

    minimum_hour, start_time_sec, end_time_sec = shift_schedule_today(
        day=day, shift=shift
    )
    if attendance.attendance_clock_in:
        late_come(
            attendance, start_time=start_time_sec, end_time=end_time_sec, shift=shift
        )
    if attendance.attendance_clock_out:
        early_out(
            attendance, start_time=start_time_sec, end_time=end_time_sec, shift=shift
        )

    _log_attendance_request_action(
        attendance.employee_id,
        AttendanceRequestLog.ACTION_APPROVED,
        request.user,
        attendance=attendance,
        description=_("Approved for %(date)s") % {"date": attendance.attendance_date},
        employee_request_note=approval_employee_note,
    )
    messages.success(request, _("Attendance request has been approved"))
    employee = attendance.employee_id
    actor = getattr(request.user, "employee_get", None) or request.user
    notify_kw = dict(
        verb=f"Your attendance request for {attendance.attendance_date} is validated",
        verb_ar=f"تم التحقق من طلب حضورك في تاريخ {attendance.attendance_date}",
        verb_de=f"Ihr Anwesenheitsantrag für das Datum {attendance.attendance_date} wurde bestätigt",
        verb_es=f"Se ha validado su solicitud de asistencia para la fecha {attendance.attendance_date}",
        verb_fr=f"Votre demande de présence pour la date {attendance.attendance_date} est validée",
        redirect=reverse("request-attendance-view") + f"?id={attendance.id}",
        icon="checkmark-circle-outline",
    )
    if actor == request.user:
        notify_kw["label"] = request.user.get_full_name() or request.user.username
    if employee.employee_user_id:
        notify.send(actor, recipient=employee.employee_user_id, **notify_kw)
    reporting_manager = _reporting_manager_user(attendance.employee_id)
    if reporting_manager:
        user_last_name = get_employee_last_name(attendance)
        notify_kw_rm = dict(
            verb=f"{employee.employee_first_name} {user_last_name}'s attendance request for {attendance.attendance_date} is validated",
            verb_ar=f"تم التحقق من طلب الحضور لـ {employee.employee_first_name} {user_last_name} في {attendance.attendance_date}",
            verb_de=f"Die Anwesenheitsanfrage von {employee.employee_first_name} {user_last_name} für den {attendance.attendance_date} wurde validiert",
            verb_es=f"Se ha validado la solicitud de asistencia de {employee.employee_first_name} {user_last_name} para el {attendance.attendance_date}",
            verb_fr=f"La demande de présence de {employee.employee_first_name} {user_last_name} pour le {attendance.attendance_date} a été validée",
            redirect=reverse("request-attendance-view") + f"?id={attendance.id}",
            icon="checkmark-circle-outline",
        )
        if actor == request.user:
            notify_kw_rm["label"] = request.user.get_full_name() or request.user.username
        notify.send(actor, recipient=reporting_manager, **notify_kw_rm)
    try:
        send_attendance_request_approved_emails(request, attendance)
    except Exception as e:
        logger.exception("Attendance request approved email failed: %s", e)
    if request.headers.get("HX-Request"):
        return render(
            request,
            "requests/attendance/validate_response.html",
            {"message": _("Attendance request has been approved")},
        )
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


@login_required
def cancel_attendance_request(request, attendance_id):
    """
    This method is used to cancel attendance request
    """
    response_message = _("Attendance request not found")
    try:
        attendance = Attendance.objects.get(id=attendance_id)
        if (
            attendance.employee_id.employee_user_id == request.user
            or is_reportingmanager(request)
            or request.user.has_perm("attendance.change_attendance")
        ):
            # Snapshot requested data before it is cleared (so logs show requested times even after rejection).
            _requested_snap = parse_attendance_requested_data(attendance.requested_data)
            _attendance_snap = None
            try:
                _attendance_snap = attendance.serialize()
            except Exception:
                _attendance_snap = None
            was_create_request = attendance.request_type == "create_request"
            attendance.is_validate_request = False
            attendance.request_description = None
            attendance.requested_data = None
            attendance.request_type = None
            # Pending update requests set attendance_validated=False via
            # Attendance.handle_overtime_conditions(); restore validated state so
            # WorkRecords is FDP/HDP again (not CONF → calendar AR).
            if not was_create_request:
                attendance.attendance_validated = True
                attendance.is_validate_request_approved = True
            else:
                attendance.is_validate_request_approved = False

            attendance.save()
            if not was_create_request:
                # Belt-and-suspenders: custom Attendance.save() is heavy; force DB flags so the
                # calendar never keeps AR (pending uses is_validate_request; CONF uses !validated).
                # Use entire() so company-scoped manager cannot skip the row.
                Attendance.objects.entire().filter(pk=attendance.pk).update(
                    is_validate_request=False,
                    attendance_validated=True,
                    is_validate_request_approved=True,
                )
                # Re-load without company filter (same as update) so instance matches DB.
                attendance = Attendance.objects.entire().get(pk=attendance.pk)
                from attendance.signals import attendance_post_save as _attendance_sync_work_record

                _attendance_sync_work_record(
                    sender=Attendance, instance=attendance, created=False
                )
            _log_attendance_request_action(
                attendance.employee_id,
                AttendanceRequestLog.ACTION_REJECTED,
                request.user,
                attendance=attendance,
                description=_("Rejected for %(date)s") % {"date": attendance.attendance_date},
                requested_data_snapshot=_requested_snap,
                attendance_snapshot=_attendance_snap,
            )
            employee = attendance.employee_id
            actor = getattr(request.user, "employee_get", None) or request.user
            notify_kw = dict(
                verb=f"Your attendance request for {attendance.attendance_date} is rejected",
                verb_ar=f"تم رفض طلبك للحضور في تاريخ {attendance.attendance_date}",
                verb_de=f"Ihre Anwesenheitsanfrage für {attendance.attendance_date} wurde abgelehnt",
                verb_es=f"Tu solicitud de asistencia para el {attendance.attendance_date} ha sido rechazada",
                verb_fr=f"Votre demande de présence pour le {attendance.attendance_date} est rejetée",
                icon="close-circle-outline",
            )
            if actor == request.user:
                notify_kw["label"] = request.user.get_full_name() or request.user.username
            if employee.employee_user_id:
                notify.send(actor, recipient=employee.employee_user_id, **notify_kw)
            try:
                send_attendance_request_rejected_emails(request, attendance)
            except Exception as e:
                logger.exception("Attendance request rejected email failed: %s", e)
            if was_create_request:
                attendance.delete()
                response_message = _("The requested attendance is removed.")
                messages.success(request, response_message)
            else:
                response_message = _("Attendance request has been rejected")
                messages.success(request, response_message)
    except (Attendance.DoesNotExist, OverflowError):
        messages.error(request, response_message)
    if request.headers.get("HX-Request"):
        return render(
            request,
            "requests/attendance/validate_response.html",
            {"message": response_message},
        )
    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


@login_required
def select_all_filter_attendance_request(request):
    page_number = request.GET.get("page")
    filtered = request.GET.get("filter")
    filters = json.loads(filtered) if filtered else {}

    if page_number == "all":
        if request.user.has_perm("attendance.view_attendance"):
            employee_filter = AttendanceFilters(
                request.GET,
                queryset=Attendance.objects.filter(is_validate_request=True),
            )
        else:
            employee_filter = AttendanceFilters(
                request.GET,
                queryset=Attendance.objects.filter(
                    employee_id__employee_user_id=request.user, is_validate_request=True
                )
                | Attendance.objects.filter(
                    employee_id__employee_work_info__reporting_manager_id__employee_user_id=request.user,
                    is_validate_request=True,
                ),
            )

        # Get the filtered queryset

        filtered_employees = employee_filter.qs

        employee_ids = [str(emp.id) for emp in filtered_employees]
        total_count = filtered_employees.count()

        context = {"employee_ids": employee_ids, "total_count": total_count}

        return JsonResponse(context)


@login_required
@manager_can_enter("attendance.change_attendance")
def bulk_approve_attendance_request(request):
    """
    This method is used to validate the attendance requests.
    Own requests are skipped; only subordinates' requests are approved.
    """
    ids = request.POST["ids"]
    ids = json.loads(ids)
    current_employee_id = getattr(request.user.employee_get, "id", None) if getattr(request.user, "employee_get", None) else None
    for attendance_id in ids:
        attendance = Attendance.objects.get(id=attendance_id)
        if current_employee_id is not None and attendance.employee_id_id == current_employee_id:
            continue
        approval_employee_note = (attendance.request_description or "").strip()
        prev_attendance_date = attendance.attendance_date
        prev_attendance_clock_in_date = attendance.attendance_clock_in_date
        prev_attendance_clock_in = attendance.attendance_clock_in
        attendance.attendance_validated = True
        attendance.is_validate_request_approved = True
        attendance.is_validate_request = False
        attendance.request_description = None
        attendance.save()
        if attendance.requested_data is not None:
            requested_data = parse_attendance_requested_data(attendance.requested_data)
            if requested_data:
                requested_data = _coerce_requested_data_for_orm_update(requested_data)
                if requested_data.get("attendance_clock_out") == "None":
                    requested_data["attendance_clock_out"] = None
                if requested_data.get("attendance_clock_out_date") == "None":
                    requested_data["attendance_clock_out_date"] = None
                # Use entire() to bypass company scoping; otherwise updates can silently
                # no-op when selected_company/session filter doesn't match.
                Attendance.objects.entire().filter(id=attendance_id).update(**requested_data)
                attendance = Attendance.objects.get(id=attendance_id)
                recalculate_worked_hour_from_clock(attendance)
                attendance.save()
        if (
            attendance.attendance_clock_out is None
            or attendance.attendance_clock_out_date is None
        ):
            attendance.attendance_validated = True
            activity = AttendanceActivity.objects.filter(
                employee_id=attendance.employee_id,
                attendance_date=prev_attendance_date,
                clock_in_date=prev_attendance_clock_in_date,
                clock_in=prev_attendance_clock_in,
            )
            if activity:
                activity.update(
                    employee_id=attendance.employee_id,
                    attendance_date=attendance.attendance_date,
                    clock_in_date=attendance.attendance_clock_in_date,
                    clock_in=attendance.attendance_clock_in,
                )

            else:
                AttendanceActivity.objects.create(
                    employee_id=attendance.employee_id,
                    attendance_date=attendance.attendance_date,
                    clock_in_date=attendance.attendance_clock_in_date,
                    clock_in=attendance.attendance_clock_in,
                )

        # Create late come or early out objects
        shift = attendance.shift_id
        day = attendance.attendance_date.strftime("%A").lower()
        day = EmployeeShiftDay.objects.get(day=day)

        minimum_hour, start_time_sec, end_time_sec = shift_schedule_today(
            day=day, shift=shift
        )
        if attendance.attendance_clock_in:
            late_come(
                attendance,
                start_time=start_time_sec,
                end_time=end_time_sec,
                shift=shift,
            )
        if attendance.attendance_clock_out:
            early_out(
                attendance,
                start_time=start_time_sec,
                end_time=end_time_sec,
                shift=shift,
            )

        _log_attendance_request_action(
            attendance.employee_id,
            AttendanceRequestLog.ACTION_APPROVED,
            request.user,
            attendance=attendance,
            description=_("Approved for %(date)s") % {"date": attendance.attendance_date},
            employee_request_note=approval_employee_note,
        )
        messages.success(request, _("Attendance request has been approved"))
        employee = attendance.employee_id
        actor = getattr(request.user, "employee_get", None) or request.user
        notify_kw = dict(
            verb=f"Your attendance request for {attendance.attendance_date} is validated",
            verb_ar=f"تم التحقق من طلب حضورك في تاريخ {attendance.attendance_date}",
            verb_de=f"Ihr Anwesenheitsantrag für das Datum {attendance.attendance_date} wurde bestätigt",
            verb_es=f"Se ha validado su solicitud de asistencia para la fecha {attendance.attendance_date}",
            verb_fr=f"Votre demande de présence pour la date {attendance.attendance_date} est validée",
            redirect=reverse("request-attendance-view") + f"?id={attendance.id}",
            icon="checkmark-circle-outline",
        )
        if actor == request.user:
            notify_kw["label"] = request.user.get_full_name() or request.user.username
        if employee.employee_user_id:
            notify.send(actor, recipient=employee.employee_user_id, **notify_kw)
        reporting_manager = _reporting_manager_user(attendance.employee_id)
        if reporting_manager:
            user_last_name = get_employee_last_name(attendance)
            notify_kw_rm = dict(
                verb=f"{employee.employee_first_name} {user_last_name}'s attendance request for {attendance.attendance_date} is validated",
                verb_ar=f"تم التحقق من طلب الحضور لـ {employee.employee_first_name} {user_last_name} في {attendance.attendance_date}",
                verb_de=f"Die Anwesenheitsanfrage von {employee.employee_first_name} {user_last_name} für den {attendance.attendance_date} wurde validiert",
                verb_es=f"Se ha validado la solicitud de asistencia de {employee.employee_first_name} {user_last_name} para el {attendance.attendance_date}",
                verb_fr=f"La demande de présence de {employee.employee_first_name} {user_last_name} pour le {attendance.attendance_date} a été validée",
                redirect=reverse("request-attendance-view") + f"?id={attendance.id}",
                icon="checkmark-circle-outline",
            )
            if actor == request.user:
                notify_kw_rm["label"] = request.user.get_full_name() or request.user.username
            notify.send(actor, recipient=reporting_manager, **notify_kw_rm)
        try:
            send_attendance_request_approved_emails(request, attendance)
        except Exception as e:
            logger.exception("Attendance request approved email failed (bulk): %s", e)
    return HttpResponse("success")


@login_required
@manager_can_enter("attendance.delete_attendance")
def bulk_reject_attendance_request(request):
    """
    This method is used to delete bulk attendance request
    """
    ids = request.POST["ids"]
    ids = json.loads(ids)
    for attendance_id in ids:
        try:
            attendance = Attendance.objects.get(id=attendance_id)
            if (
                attendance.employee_id.employee_user_id == request.user
                or is_reportingmanager(request)
                or request.user.has_perm("attendance.change_attendance")
            ):
                # Snapshot requested data before it is cleared (so logs show requested times even after rejection).
                _requested_snap = parse_attendance_requested_data(attendance.requested_data)
                _attendance_snap = None
                try:
                    _attendance_snap = attendance.serialize()
                except Exception:
                    _attendance_snap = None
                attendance.is_validate_request_approved = False
                attendance.is_validate_request = False
                attendance.request_description = None
                attendance.requested_data = None
                is_create_request = attendance.request_type == "create_request"
                attendance.request_type = None
                attendance.save()
                _log_attendance_request_action(
                    attendance.employee_id,
                    AttendanceRequestLog.ACTION_REJECTED,
                    request.user,
                    attendance=attendance,
                    description=_("Rejected for %(date)s") % {"date": attendance.attendance_date},
                    requested_data_snapshot=_requested_snap,
                    attendance_snapshot=_attendance_snap,
                )
                employee = attendance.employee_id
                actor = getattr(request.user, "employee_get", None) or request.user
                notify_kw = dict(
                    verb=f"Your attendance request for {attendance.attendance_date} is rejected",
                    verb_ar=f"تم رفض طلبك للحضور في تاريخ {attendance.attendance_date}",
                    verb_de=f"Ihre Anwesenheitsanfrage für {attendance.attendance_date} wurde abgelehnt",
                    verb_es=f"Tu solicitud de asistencia para el {attendance.attendance_date} ha sido rechazada",
                    verb_fr=f"Votre demande de présence pour le {attendance.attendance_date} est rejetée",
                    icon="close-circle-outline",
                )
                if actor == request.user:
                    notify_kw["label"] = request.user.get_full_name() or request.user.username
                if employee.employee_user_id:
                    notify.send(actor, recipient=employee.employee_user_id, **notify_kw)
                try:
                    send_attendance_request_rejected_emails(request, attendance)
                except Exception as e:
                    logger.exception("Attendance request rejected email failed (bulk): %s", e)
                if is_create_request:
                    attendance.delete()
                    messages.success(request, _("The requested attendance is removed."))
                else:
                    messages.success(
                        request, _("The requested attendance is rejected.")
                    )
        except (Attendance.DoesNotExist, OverflowError):
            messages.error(request, _("Attendance request not found"))
    return HttpResponse("success")


@login_required
@manager_can_enter("attendance.change_attendance")
def edit_validate_attendance(request, attendance_id):
    """
    This method is used to edit and update the validate request attendance
    """
    attendance = Attendance.objects.get(id=attendance_id)
    initial = attendance.serialize()
    if request.GET.get("previous_url"):
        initial = request.GET.dict()
    else:
        if attendance.request_type != "create_request":
            parsed = parse_attendance_requested_data(attendance.requested_data)
            initial = parsed if parsed else attendance.serialize()
        initial["request_description"] = attendance.request_description
    form = AttendanceRequestForm(initial=initial)
    form.instance.id = attendance.id
    hx_target = request.META.get("HTTP_HX_TARGET")
    if request.method == "POST":
        form = AttendanceRequestForm(request.POST, instance=copy.copy(attendance))
        if form.is_valid():
            instance = form.save()
            instance.employee_id = attendance.employee_id
            instance.id = attendance.id
            if attendance.request_type != "create_request":
                attendance.requested_data = json.dumps(instance.serialize())
                attendance.request_description = instance.request_description
                # set the user level validation here
                attendance.is_validate_request = True
                attendance.save()
            else:
                instance.is_validate_request_approved = False
                instance.is_validate_request = True
                instance.save()
            _log_attendance_request_action(
                attendance.employee_id,
                AttendanceRequestLog.ACTION_EDITED,
                request.user,
                attendance=attendance,
                description=_("Request edited for %(date)s") % {"date": attendance.attendance_date},
            )
            return HttpResponse(
                f"""
                                <script>
                                $('#editValidateAttendanceRequest').removeClass('oh-modal--show');
                                $('[data-target="#validateAttendanceRequest"][data-attendance-id={attendance.id}]').click();
                                $('#messages').html(
                                `
                                <div class="oh-alert-container">
                                <div class="oh-alert oh-alert--animated oh-alert--success">
                                Attendance request updated.
                                </div>
                                </div>
                                `
                                )
                                </script>
                                """
            )
    return render(
        request,
        "requests/attendance/update_form.html",
        {"form": form, "hx_target": hx_target},
    )


@login_required
@hx_request_required
def get_employee_shift(request):
    """
    method used to get employee shift
    """
    employee_id = request.GET.get("employee_id")
    shift = None
    if employee_id:
        employee = Employee.objects.get(id=employee_id)
        shift = employee.get_shift
    form = NewRequestForm()
    if request.GET.get("bulk") and eval_validate(request.GET.get("bulk")):
        form = BulkAttendanceRequestForm()
    form.fields["shift_id"].queryset = EmployeeShift.objects.all()
    form.fields["shift_id"].widget.attrs["hx-trigger"] = "load,change"
    form.fields["shift_id"].initial = shift
    shift_id = render_to_string(
        "requests/attendance/form_field.html",
        {
            "field": form["shift_id"],
            "shift": shift,
        },
    )
    return HttpResponse(f"{shift_id}")


def _attendance_request_log_row_matches_search(row, needle: str) -> bool:
    """Case-insensitive match across employee, badge, date, approver, and time shown in the list."""
    if not needle:
        return True
    n = needle.lower()
    parts = []
    if row.kind == "log":
        parts.append(str(row.log.employee_id))
        emp = row.log.employee_id
        if emp:
            if getattr(emp, "badge_id", None):
                parts.append(str(emp.badge_id))
            parts.append(emp.employee_first_name or "")
            parts.append(emp.employee_last_name or "")
        if row.log.performed_by:
            u = row.log.performed_by
            parts.append(u.get_full_name() or "")
            parts.append(u.username or "")
            parts.append(getattr(u, "email", "") or "")
        if row.log.attendance_id:
            att = row.log.attendance_id
            parts.append(str(att.attendance_date))
            parts.append(str(att.attendance_clock_in or ""))
            parts.append(str(att.attendance_clock_out or ""))
        # Include requested vs final snapshots (so search finds requested/approved times too)
        req = getattr(row, "requested_snapshot", None) or {}
        fin = getattr(row, "attendance_snapshot", None) or {}
        for k in ("attendance_clock_in", "attendance_clock_out", "attendance_date"):
            if k in req:
                parts.append(str(req.get(k) or ""))
            if k in fin:
                parts.append(str(fin.get(k) or ""))
        parts.append(str(row.log.description or ""))
        parts.append(str(getattr(row.log, "employee_request_note", None) or ""))
        parts.append(str(getattr(row, "display_request_note", None) or ""))
        parts.append(str(row.log.performed_at))
    else:
        parts.append(str(row.employee))
        emp = row.employee
        if emp:
            if getattr(emp, "badge_id", None):
                parts.append(str(emp.badge_id))
            parts.append(emp.employee_first_name or "")
            parts.append(emp.employee_last_name or "")
        parts.append(str(row.attendance_date))
        parts.append(row.performed_by_display or "")
        parts.append(str(row.performed_at))
        att = getattr(row, "attendance", None)
        if att:
            parts.append(str(att.attendance_clock_in or ""))
            parts.append(str(att.attendance_clock_out or ""))
    blob = " ".join(parts).lower()
    return n in blob


@login_required
def attendance_request_logs_view(request):
    """
    Attendance request logs (approved + rejected) from AttendanceRequestLog.

    Fast path: filter + paginate in the database, then hydrate request-note /
    snapshot detail only for the current page. EmailLog gap-filling is opt-in
    (?email_gaps=1) because scanning thousands of mail rows made this page slow.
    """
    base = AttendanceRequestLog.objects.filter(
        action__in=[AttendanceRequestLog.ACTION_APPROVED, AttendanceRequestLog.ACTION_REJECTED],
        employee_id__is_active=True,
    ).select_related(
        "employee_id",
        "attendance_id",
        "performed_by",
    )
    logs_qs = filtersubordinates(
        request=request,
        perm="attendance.view_attendance",
        queryset=base,
    )
    logs_qs = logs_qs | base.filter(employee_id__employee_user_id=request.user)
    logs_qs = logs_qs.distinct().order_by("-performed_at")

    search_q = (request.GET.get("q") or "").strip()
    if search_q:
        logs_qs = logs_qs.filter(
            Q(employee_id__employee_first_name__icontains=search_q)
            | Q(employee_id__employee_last_name__icontains=search_q)
            | Q(employee_id__badge_id__icontains=search_q)
            | Q(description__icontains=search_q)
            | Q(employee_request_note__icontains=search_q)
            | Q(performed_by__username__icontains=search_q)
            | Q(performed_by__first_name__icontains=search_q)
            | Q(performed_by__last_name__icontains=search_q)
            | Q(performed_by__email__icontains=search_q)
        )

    paginator = Paginator(logs_qs, get_pagination())
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    page_logs = list(page_obj.object_list)

    # Requested-note / snapshot lookup only for this page (not the full history).
    att_ids_for_notes = [
        log.attendance_id_id for log in page_logs if log.attendance_id_id
    ]
    requested_from_by_att_id = {}
    if att_ids_for_notes:
        for req_log in (
            AttendanceRequestLog.objects.filter(
                attendance_id__in=att_ids_for_notes,
                action__in=[
                    AttendanceRequestLog.ACTION_REQUESTED,
                    AttendanceRequestLog.ACTION_EDITED,
                ],
            )
            .order_by("-performed_at")
            .only(
                "attendance_id_id",
                "employee_request_note",
                "performed_at",
                "performed_by",
                "requested_data_snapshot",
            )
        ):
            aid = req_log.attendance_id_id
            if aid in requested_from_by_att_id:
                continue
            requested_from_by_att_id[aid] = req_log

    combined_rows = []
    for log in page_logs:
        display_note = (log.employee_request_note or "").strip()
        if not display_note and log.attendance_id_id:
            req_log = requested_from_by_att_id.get(log.attendance_id_id)
            if req_log:
                display_note = (req_log.employee_request_note or "").strip()
        req_log = (
            requested_from_by_att_id.get(log.attendance_id_id)
            if log.attendance_id_id
            else None
        )
        requested_snap = None
        if req_log and req_log.requested_data_snapshot:
            requested_snap = req_log.requested_data_snapshot
        elif log.requested_data_snapshot:
            requested_snap = log.requested_data_snapshot
        if not requested_snap and log.attendance_id_id:
            requested_snap = parse_attendance_requested_data(
                getattr(log.attendance_id, "requested_data", None)
            )

        attendance_snap = log.attendance_snapshot
        if not attendance_snap and log.attendance_id_id:
            try:
                attendance_snap = log.attendance_id.serialize()
            except Exception:
                attendance_snap = None
        combined_rows.append(
            SimpleNamespace(
                kind="log",
                sort_at=log.performed_at,
                log=log,
                display_request_note=display_note,
                requested_log=req_log,
                requested_snapshot=requested_snap or {},
                attendance_snapshot=attendance_snap or {},
            )
        )

    # Optional legacy gap-fill from approval emails (slow). Off by default.
    if request.GET.get("email_gaps", "").lower() in ("1", "true", "yes"):
        covered_pairs = set()
        for row in combined_rows:
            log = row.log
            if log.attendance_id_id and log.employee_id_id:
                covered_pairs.add(
                    (log.employee_id_id, log.attendance_id.attendance_date)
                )
        owner_subj_q = Q(subject__icontains="Your attendance request") & Q(
            subject__icontains="has been approved"
        )
        by_name_subj_q = Q(subject__icontains="Attendance request by") & Q(
            subject__icontains="has been approved"
        )
        email_candidates = (
            EmailLog.objects.filter(status="sent")
            .filter(owner_subj_q | by_name_subj_q)
            .exclude(subject__icontains="rejected")
            .order_by("-created_at")[:200]
        )
        by_full, by_first_last = _employee_name_lookup_maps()
        seen_email_pair = set()
        for el in email_candidates:
            subj = el.subject or ""
            emp = None
            att_date = None

            owner_date = _parse_attendance_date_from_owner_approval_subject(subj)
            if owner_date is not None:
                att_date = owner_date
                emp = _employee_from_recipient_email(el.to)

            if not emp:
                name_part, by_name_date = (
                    _parse_employee_and_date_from_by_name_approval_subject(subj)
                )
                if by_name_date and name_part:
                    att_date = by_name_date
                    emp = _resolve_employee_from_subject_name(
                        name_part, by_full, by_first_last
                    )

            if not att_date or not emp:
                continue
            if not _employee_visible_for_attendance_logs(request, emp):
                continue
            key = (emp.id, att_date)
            if key in covered_pairs or key in seen_email_pair:
                continue
            seen_email_pair.add(key)
            attendance = (
                Attendance.objects.filter(employee_id=emp, attendance_date=att_date)
                .order_by("-id")
                .first()
            )
            att_pk = attendance.id if attendance else None
            combined_rows.append(
                SimpleNamespace(
                    kind="email",
                    sort_at=el.created_at,
                    log=None,
                    employee=emp,
                    attendance_date=att_date,
                    performed_at=el.created_at,
                    performed_by_display=_approver_display_for_email_recovery_row(
                        att_pk, el.body or ""
                    ),
                    attendance_pk=att_pk,
                    email_note=True,
                    attendance=attendance,
                    action=AttendanceRequestLog.ACTION_APPROVED,
                )
            )
        combined_rows.sort(key=lambda r: r.sort_at, reverse=True)

    page_obj.object_list = combined_rows

    return render(
        request,
        "requests/attendance/attendance_request_logs.html",
        {"logs": page_obj, "search_q": search_q},
    )
