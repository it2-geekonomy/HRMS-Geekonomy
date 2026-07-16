"""
Late punch-in display helpers for the Late / Early attendance page.

Punch-in from 9:11 AM (amber) through 9:30 AM and from 9:31 AM (red) are shown on the same list.
"""

from datetime import date, time

from django.utils.translation import gettext_lazy as _

from attendance.filters import AttendanceFilters, LateComeEarlyOutFilter
from attendance.models import Attendance, AttendanceLateComeEarlyOut
from base.methods import filtersubordinates, sortby

LATE_PUNCH_AMBER_FROM = time(9, 11)
LATE_PUNCH_RED_FROM = time(9, 31)
EARLY_OUT_CUTOFF = time(17, 0)  # 5:00 PM — leave before this counts as early out

SORT_FIELD_MAP = {
    "attendance_id__attendance_date": "attendance_date",
    "attendance_id__attendance_clock_in_date": "attendance_clock_in_date",
    "attendance_id__attendance_clock_out_date": "attendance_clock_out_date",
    "attendance_id__at_work_second": "at_work_second",
}


def punch_flag_for_clock_in(clock_in):
    """Return 'amber' (9:11–9:30), 'red' (9:31 AM onward), or None."""
    if not clock_in:
        return None
    if clock_in >= LATE_PUNCH_RED_FROM:
        return "red"
    if clock_in >= LATE_PUNCH_AMBER_FROM:
        return "amber"
    return None


def is_early_out_clock(clock_out):
    """True when checkout is before 5:00 PM."""
    return bool(clock_out and clock_out < EARLY_OUT_CUTOFF)


class LateEarlyDisplayRow:
    """Row wrapper compatible with late come / early out list templates."""

    def __init__(self, attendance, late_record=None, row_type="late_come"):
        self._late_record = late_record
        self.attendance_id = attendance
        self.employee_id = attendance.employee_id
        self.type = row_type
        if row_type == "late_come":
            self.punch_flag = punch_flag_for_clock_in(attendance.attendance_clock_in)
        elif row_type == "early_out":
            self.punch_flag = (
                "early" if is_early_out_clock(attendance.attendance_clock_out) else None
            )
        else:
            self.punch_flag = None

    @property
    def id(self):
        return self._late_record.id if self._late_record else None

    @property
    def has_record(self):
        return self._late_record is not None

    @property
    def mail_attendance_id(self):
        return self.attendance_id.id

    def get_type_display(self):
        if self.type == "early_out":
            return str(_("Early Out"))
        return str(_("Late Come"))

    def get_penalties_count(self):
        if self._late_record:
            return self._late_record.get_penalties_count()
        return 0


def punch_flag_label(flag):
    if flag == "amber":
        return str(_("Late in: 9:11–9:30 AM"))
    if flag == "red":
        return str(_("Late in: From 9:31 AM"))
    if flag == "early":
        return str(_("Early out: Before 5:00 PM"))
    return ""


def build_late_early_export_rows(display_rows):
    """Build flat rows for Excel export (matches Late / Early list UI)."""
    export_rows = []
    for row in display_rows:
        att = row.attendance_id
        export_rows.append(
            {
                str(_("Employee")): str(row.employee_id),
                str(_("Status")): punch_flag_label(row.punch_flag),
                str(_("Type")): str(row.get_type_display()),
                str(_("Attendance Date")): att.attendance_date or "",
                str(_("Check-In")): att.attendance_clock_in or "",
                str(_("In Date")): att.attendance_clock_in_date or "",
                str(_("Check-Out")): att.attendance_clock_out or "",
                str(_("Out Date")): att.attendance_clock_out_date or "",
                str(_("Min Hour")): att.minimum_hour or "",
            }
        )
    return export_rows


def late_early_export_response(request, get_params):
    """Export filtered Late / Early rows shown in the UI to Excel."""
    import io
    from datetime import date as date_cls

    import pandas as pd
    from django.http import HttpResponse

    get_params = get_params.copy()
    attendance_ids = get_params.get("attendance_ids")
    if attendance_ids:
        import json

        try:
            selected_ids = {int(pk) for pk in json.loads(attendance_ids)}
        except (TypeError, ValueError, json.JSONDecodeError):
            selected_ids = set()
        if selected_ids:
            display_rows = [
                row
                for row in build_late_early_display_rows(request, get_params)
                if row.attendance_id.id in selected_ids
            ]
        else:
            display_rows = build_late_early_display_rows(request, get_params)
    else:
        display_rows = build_late_early_display_rows(request, get_params)

    columns = [
        str(_("Employee")),
        str(_("Status")),
        str(_("Type")),
        str(_("Attendance Date")),
        str(_("Check-In")),
        str(_("In Date")),
        str(_("Check-Out")),
        str(_("Out Date")),
        str(_("Min Hour")),
    ]
    export_rows = build_late_early_export_rows(display_rows)
    df = pd.DataFrame(export_rows, columns=columns)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        sheet_name = str(_("Late Early"))
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
        worksheet = writer.sheets[sheet_name[:31]]
        for col_idx, col in enumerate(columns):
            max_len = max(
                df[col].astype(str).map(len).max() if len(df) else 0,
                len(col),
            )
            worksheet.set_column(col_idx, col_idx, min(max_len + 2, 40))

    output.seek(0)
    filename = f"Late_Early_{date_cls.today().isoformat()}.xlsx"
    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def apply_default_date_filter(get_params):
    has_date_filter = (
        "attendance_date__gte" in get_params
        or "attendance_date__lte" in get_params
        or "attendance_date" in get_params
    )
    if not has_date_filter:
        today = date.today().isoformat()
        get_params["attendance_date__gte"] = today
        get_params["attendance_date__lte"] = today
    return get_params


def map_late_filter_params(get_params):
    mapped = get_params.copy()
    for key in list(mapped.keys()):
        if key.startswith("attendance_id__"):
            mapped[key.replace("attendance_id__", "", 1)] = mapped.pop(key)
    mapped.pop("type", None)
    return mapped


def _late_record_for(attendance):
    for record in attendance.late_come_early_out.all():
        if record.type == "late_come":
            return record
    return None


def _early_record_for(attendance):
    for record in attendance.late_come_early_out.all():
        if record.type == "early_out":
            return record
    return None


def _sort_attendance_queryset(request, queryset):
    sortby_val = request.GET.get("sortby")
    if not sortby_val or sortby_val == "type":
        return queryset.order_by(
            "-attendance_date", "employee_id__employee_first_name"
        )
    mapped = SORT_FIELD_MAP.get(sortby_val, sortby_val)
    if mapped.startswith("attendance_id__"):
        mapped = mapped.replace("attendance_id__", "", 1)
    patched_get = request.GET.copy()
    patched_get["sortby"] = mapped
    original_get = request.GET
    request.GET = patched_get
    try:
        return sortby(request, queryset, "sortby")
    finally:
        request.GET = original_get


def build_late_early_display_rows(request, get_params):
    get_params = apply_default_date_filter(get_params)
    att_params = map_late_filter_params(get_params)

    base_qs = AttendanceFilters(att_params, queryset=Attendance.objects.all()).qs
    base_qs = filtersubordinates(request, base_qs, "attendance.view_attendance")
    self_att = base_qs.filter(employee_id__employee_user_id=request.user)
    base_qs = (base_qs | self_att).distinct()

    late_qs = base_qs.filter(
        attendance_clock_in__gte=LATE_PUNCH_AMBER_FROM,
        attendance_clock_in__isnull=False,
    ).select_related("employee_id").prefetch_related("late_come_early_out")
    late_qs = _sort_attendance_queryset(request, late_qs)

    rows = [
        LateEarlyDisplayRow(attendance, _late_record_for(attendance))
        for attendance in late_qs
    ]

    early_attendance_ids = set()
    early_att_qs = base_qs.filter(
        attendance_clock_out__isnull=False,
        attendance_clock_out__lt=EARLY_OUT_CUTOFF,
    ).select_related("employee_id").prefetch_related("late_come_early_out")

    for attendance in early_att_qs:
        early_attendance_ids.add(attendance.id)
        rows.append(
            LateEarlyDisplayRow(
                attendance, _early_record_for(attendance), row_type="early_out"
            )
        )

    early_qs = LateComeEarlyOutFilter(get_params).qs.filter(type="early_out")
    early_qs = filtersubordinates(
        request, early_qs, "attendance.view_attendancelatecomeearlyout"
    )
    self_early = early_qs.filter(employee_id__employee_user_id=request.user)
    early_qs = (early_qs | self_early).distinct().select_related(
        "attendance_id", "employee_id"
    )

    for early_out in early_qs:
        if early_out.attendance_id_id not in early_attendance_ids:
            rows.append(
                LateEarlyDisplayRow(
                    early_out.attendance_id, early_out, row_type="early_out"
                )
            )
            early_attendance_ids.add(early_out.attendance_id_id)

    type_filter = get_params.get("type")
    if type_filter in ("late_come", "early_out"):
        rows = [row for row in rows if row.type == type_filter]

    return rows
