"""
utils.py

This module is used write custom methods
"""

import calendar
import json
from datetime import date, datetime, time, timedelta

import pandas as pd
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from base.methods import get_pagination
from base.models import WEEK_DAYS, CompanyLeaves, Holidays
from employee.models import Employee
from horilla.horilla_settings import HORILLA_DATE_FORMATS, HORILLA_TIME_FORMATS

MONTH_MAPPING = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# One-time alternating Saturday cycle shift requested by business:
# - 2026-03-21 is treated as week off.
# - From 2026-03-28 onward, alternate Saturday parity is flipped so
#   2026-03-28 is working and 2026-04-04 becomes week off.
SATURDAY_ONE_TIME_WEEK_OFF = date(2026, 3, 21)
SATURDAY_ALTERNATE_SHIFT_START = date(2026, 3, 28)


def format_time(seconds):
    """
    this method is used to formate seconds to H:M and return it
    args:
        seconds : seconds
    """

    hour = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int((seconds % 3600) % 60)
    return f"{hour:02d}:{minutes:02d}"


def strtime_seconds(time):
    """
    this method is used reconvert time in H:M formate string back to seconds and return it
    args:
        time : time in H:M format
    """

    ftr = [3600, 60, 1]
    return sum(a * b for a, b in zip(ftr, map(int, time.split(":"))))


def get_diff_obj(first_instance, other_instance, exclude_fields=None):
    """
    Compare the fields of two instances and identify the changes.

    Args:
        first_instance: The first instance to compare.
        other_instance: The second instance to compare.
        exclude_fields: A list of field names to exclude from comparison (optional).

    Returns:
        A dictionary of changed fields with their old and new values.
    """
    difference = {}

    fields_to_compare = first_instance._meta.fields

    if exclude_fields:
        fields_to_compare = [
            field for field in fields_to_compare if field.name not in exclude_fields
        ]

    for field in fields_to_compare:
        old_value = getattr(first_instance, field.name)
        new_value = getattr(other_instance, field.name)

        if old_value != new_value:
            difference[field.name] = (old_value, new_value)

    return difference


def get_diff_dict(first_dict, other_dict, model=None, exclude_fields=None):
    """
    Compare two dictionaries and identify differing key-value pairs.

    Args:
        first_dict: The first dictionary to compare.
        other_dict: The second dictionary to compare.
        model: The model class (optional, for verbose names and type-specific formatting)
        exclude_fields: Optional list of field names to exclude from the diff.

    Returns:
        A dictionary of differing keys with their old and new values.
    """
    difference = {}
    exclude_fields = exclude_fields or []

    for key, value in first_dict.items():
        if key in exclude_fields:
            continue
        other_value = other_dict.get(key)
        if value == other_value:
            continue  # Skip if values are the same

        if not model:
            difference[key] = (value, other_value)
            continue

        # Fetch the model field metadata
        field = model._meta.get_field(key)
        verbose_key = field.verbose_name

        # Handle specific field types
        if isinstance(field, models.DateField):
            value = (
                datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
                if value and value != "None"
                else value
            )
            other_value = (
                datetime.strptime(other_value, "%Y-%m-%d").strftime("%d %b %Y")
                if other_value and other_value != "None"
                else other_value
            )
        elif isinstance(field, models.TimeField):

            def format_time(val):
                if val and val != "None":
                    val += ":00" if len(val.split(":")) == 2 else ""
                    return datetime.strptime(val, "%H:%M:%S").strftime("%I:%M %p")
                return val

            value = format_time(value)
            other_value = format_time(other_value)
        elif isinstance(field, models.ForeignKey):
            value = (
                field.related_model.objects.get(id=value)
                if value and str(value).isdigit()
                else value
            )
            other_value = (
                field.related_model.objects.get(id=other_value)
                if other_value and str(other_value).isdigit()
                else other_value
            )

        # Add the difference
        difference[verbose_key] = (value, other_value)

    return difference


def employee_exists(request):
    """
    This method return the employee instance and work info if not exists return None instead
    """
    employee, employee_work_info = None, None
    try:
        employee = request.user.employee_get
        employee_work_info = employee.employee_work_info
    finally:
        return (employee, employee_work_info)


def shift_schedule_today(day, shift):
    """
    This function is used to find shift schedules for the day,
    it will returns min hour,start time seconds  end time seconds
    args:
        shift   : shift instance
        day     : shift day object
    """
    schedule_today = day.day_schedule.filter(shift_id=shift)
    start_time_sec, end_time_sec, minimum_hour = 0, 0, "00:00"
    if schedule_today.exists():
        schedule_today = schedule_today[0]
        minimum_hour = schedule_today.minimum_working_hour
        start_time_sec = strtime_seconds(schedule_today.start_time.strftime("%H:%M"))
        end_time_sec = strtime_seconds(schedule_today.end_time.strftime("%H:%M"))
    return (minimum_hour, start_time_sec, end_time_sec)


def overtime_calculation(attendance):
    """
    This method is used to calculate overtime of the attendance, it will
    return difference between attendance worked hour and minimum hour if
    and only worked hour greater than minimum hour, else return 00:00
    args:
        attendance : attendance instance
    """

    minimum_hour = attendance.minimum_hour
    at_work = attendance.attendance_worked_hour
    at_work_sec = strtime_seconds(at_work)
    minimum_hour_sec = strtime_seconds(minimum_hour)
    if at_work_sec > minimum_hour_sec:
        return format_time((at_work_sec - minimum_hour_sec))
    return "00:00"


def is_reportingmanger(request, instance):
    """
    if the instance have employee id field then you can use this method to know the
    request user employee is the reporting manager of the instance
    args :
        request : request
        instance : an object or instance of any model contain employee_id foreign key field
    """

    manager = request.user.employee_get
    try:
        employee_workinfo_manager = (
            instance.employee_id.employee_work_info.reporting_manager_id
        )
    except Exception:
        return HttpResponse("This Employee Dont Have any work information")
    return manager == employee_workinfo_manager


def validate_hh_mm_ss_format(value):
    timeformat = "%H:%M:%S"
    try:
        validtime = datetime.strptime(value, timeformat)
        return validtime.time()  # Return the time object if needed
    except ValueError as e:
        raise ValidationError(_("Invalid format, it should be HH:MM:SS format"))


def validate_time_format(value):
    """
    this method is used to validate the format of duration like fields.
    """
    if value.count(":") == 2:
        # If the format is "H:MM:SS", check if it can be reduced to "HH:MM"
        # Django's DurationField internally converts it to a timedelta object, it becomes "0:00:00"
        value = ":".join(value.split(":")[:2])

    if len(value) > 6:
        raise ValidationError(_("Invalid format, it should be HH:MM format"))
    try:
        hour, minute = value.split(":")
        if len(hour) > 3 or len(minute) > 2:
            raise ValidationError(_("Invalid time"))
        hour = int(hour)
        minute = int(minute)
        if len(str(hour)) > 3 or len(str(minute)) > 2 or minute not in range(60):
            raise ValidationError(_("Invalid time, excepted MM:SS"))
    except ValueError as error:
        raise ValidationError(_("Invalid format")) from error


def attendance_date_validate(date):
    """
    Validates if the provided date is not a future date.

    :param date: The date to validate.
    :raises ValidationError: If the provided date is in the future.
    """
    today = datetime.today().date()
    if not date:
        raise ValidationError(_("Check date format."))
    elif date > today:
        raise ValidationError(_("You cannot choose a future date."))


def activity_datetime(attendance_activity):
    """
    This method is used to convert clock-in and clock-out of activity as datetime object
    args:
        attendance_activity : attendance activity instance
    """

    # in
    in_year = attendance_activity.clock_in_date.year
    in_month = attendance_activity.clock_in_date.month
    in_day = attendance_activity.clock_in_date.day
    in_hour = attendance_activity.clock_in.hour
    in_minute = attendance_activity.clock_in.minute
    # out
    out_year = attendance_activity.clock_out_date.year
    out_month = attendance_activity.clock_out_date.month
    out_day = attendance_activity.clock_out_date.day
    out_hour = attendance_activity.clock_out.hour
    out_minute = attendance_activity.clock_out.minute
    return datetime(in_year, in_month, in_day, in_hour, in_minute), datetime(
        out_year, out_month, out_day, out_hour, out_minute
    )


def get_week_start_end_dates(week):
    """
    This method is use to return the start and end date of the week
    """
    # Parse the ISO week date
    year, week_number = map(int, week.split("-W"))

    # Get the date of the first day of the week
    start_date = datetime.strptime(f"{year}-W{week_number}-1", "%Y-W%W-%w").date()

    # Calculate the end date by adding 6 days to the start date
    end_date = start_date + timedelta(days=6)

    return start_date, end_date


def get_month_start_end_dates(year_month):
    """
    This method is use to return the start and end date of the month
    """
    # split year and month separately
    year, month = map(int, year_month.split("-"))
    # Get the first day of the month
    start_date = datetime(year, month, 1).date()

    # Get the last day of the month
    _, last_day = calendar.monthrange(year, month)
    end_date = datetime(year, month, last_day).date()

    return start_date, end_date


def worked_hour_data(labels, records):
    """
    To find all the worked hours
    """
    data = {
        "label": "Worked Hours",
        "backgroundColor": "rgba(75, 192, 192, 0.6)",
    }
    dept_records = []
    for dept in labels:
        total_sum = records.filter(
            employee_id__employee_work_info__department_id__department=dept
        ).aggregate(total_sum=Sum("hour_account_second"))["total_sum"]
        dept_records.append(total_sum / 3600 if total_sum else 0)
    data["data"] = dept_records
    return data


def pending_hour_data(labels, records):
    """
    To find all the pending hours
    """
    data = {
        "label": "Pending Hours",
        "backgroundColor": "rgba(255, 99, 132, 0.6)",
    }
    dept_records = []
    for dept in labels:
        total_sum = records.filter(
            employee_id__employee_work_info__department_id__department=dept
        ).aggregate(total_sum=Sum("hour_pending_second"))["total_sum"]
        dept_records.append(total_sum / 3600 if total_sum else 0)
    data["data"] = dept_records
    return data


def get_employee_last_name(attendance):
    """
    This method is used to return the last name
    """
    if attendance.employee_id.employee_last_name:
        return attendance.employee_id.employee_last_name
    return ""


def attendance_day_checking(attendance_date, minimum_hour):
    # Convert the string to a datetime object
    attendance_datetime = datetime.strptime(attendance_date, "%Y-%m-%d")

    # Extract name of the day
    attendance_day = attendance_datetime.strftime("%A")

    # Taking all holidays into a list
    leaves = []
    holidays = Holidays.objects.all()
    for holi in holidays:
        start_date = holi.start_date
        end_date = holi.end_date

        # Convert start_date and end_date to datetime objects
        start_date = datetime.strptime(str(start_date), "%Y-%m-%d")
        end_date = datetime.strptime(str(end_date), "%Y-%m-%d")

        # Add dates in between start date and end date including both
        current_date = start_date
        while current_date <= end_date:
            leaves.append(current_date.strftime("%Y-%m-%d"))
            current_date += timedelta(days=1)

    # Checking attendance date is in holiday list, if found making the minimum hour to 00:00
    for leave in leaves:
        if str(leave) == str(attendance_date):
            minimum_hour = "00:00"
            break

    # Making a dictonary contains week day value and leave day pairs
    company_leaves = {}
    company_leave = CompanyLeaves.objects.all()
    for com_leave in company_leave:
        a = dict(WEEK_DAYS).get(com_leave.based_on_week_day)
        b = com_leave.based_on_week
        company_leaves[b] = a

    # Checking the attendance date is in which week
    week_in_month = str(((attendance_datetime.day - 1) // 7 + 1) - 1)

    # Checking the attendance date is in the company leave or not
    for pairs in company_leaves.items():
        # For all weeks based_on_week is None
        if str(pairs[0]) == "None":
            if str(pairs[1]) == str(attendance_day):
                minimum_hour = "00:00"
                break
        # Checking with based_on_week and attendance_date week
        if str(pairs[0]) == week_in_month:
            if str(pairs[1]) == str(attendance_day):
                minimum_hour = "00:00"
                break
    return minimum_hour


def paginator_qry(qryset, page_number):
    """
    This method is used to paginate queryset
    """
    paginator = Paginator(qryset, get_pagination())
    qryset = paginator.get_page(page_number)
    return qryset


def monthly_holiday_dates(month, year):
    """Get only public holidays for a given month/year"""
    from datetime import date
    from django.db.models import Q
    
    # Get non-recurring holidays that start in this month/year
    # OR recurring holidays that match this month and are within the recurrence period
    last_day_of_month = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day_of_month)
    
    holidays = Holidays.objects.filter(
        Q(recurring=False, start_date__month=month, start_date__year=year)
        | Q(recurring=True, start_date__month=month, start_date__year__lte=year, end_date__gte=month_end)
    )
    
    # For recurring holidays, return the date with the query year instead of the original year
    result = []
    for h in holidays:
        if h.recurring:
            result.append(date(year, h.start_date.month, h.start_date.day))
        else:
            result.append(h.start_date)
    return result


def monthly_holiday_dates_with_names(month, year):
    """Return a dict mapping each public holiday date to its name(s) for the given month/year."""
    last_day_of_month = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day_of_month)

    holidays = Holidays.objects.filter(
        Q(recurring=False, start_date__month=month, start_date__year=year)
        | Q(
            recurring=True,
            start_date__month=month,
            start_date__year__lte=year,
            end_date__gte=month_end,
        )
    )

    result = {}
    for h in holidays:
        if h.recurring:
            d = date(year, h.start_date.month, h.start_date.day)
        else:
            d = h.start_date
        name = getattr(h, "name", None) or str(h)
        if d not in result:
            result[d] = name
        else:
            result[d] = f"{result[d]}, {name}"
    return result


def monthly_leave_days(month, year):
    leave_dates = []
    # Use monthly_holiday_dates for proper recurring holiday handling
    leave_dates += monthly_holiday_dates(month, year)

    company_leaves = CompanyLeaves.objects.all()
    
    # Group company leaves by weekday to detect alternating patterns
    leaves_by_weekday = {}
    for cl in company_leaves:
        weekday = int(cl.based_on_week_day) if cl.based_on_week_day is not None else None
        if weekday is None:
            continue
        if weekday not in leaves_by_weekday:
            leaves_by_weekday[weekday] = []
        leaves_by_weekday[weekday].append(cl.based_on_week)
    
    # Process each weekday
    for weekday, week_list in leaves_by_weekday.items():
        # Get all occurrences of this weekday in the month
        weekday_dates = []
        for day in range(1, 32):
            try:
                date_obj = datetime.strptime(f"{year}-{month:02}-{day:02}", "%Y-%m-%d").date()
                if date_obj.weekday() == weekday:
                    weekday_dates.append(date_obj)
            except ValueError:
                break
        
        # Check if "All" weeks is configured (None in list)
        if None in week_list:
            # All occurrences of this weekday are off
            for date_obj in weekday_dates:
                if date_obj not in leave_dates:
                    leave_dates.append(date_obj)
        else:
            # Convert week_list to integers
            week_indices = [int(w) for w in week_list if w is not None]
            
            # Check for alternating odd pattern (1st, 3rd, 5th = indices 0, 2, 4)
            # This pattern should use ISO week numbers for true alternating across months
            odd_pattern = {0, 2, 4}  # 1st, 3rd, 5th weeks
            even_pattern = {1, 3}     # 2nd, 4th weeks
            
            has_odd_pattern = len(set(week_indices) & odd_pattern) >= 2
            has_even_pattern = len(set(week_indices) & even_pattern) >= 2
            
            if has_odd_pattern and not has_even_pattern:
                # Alternating pattern: odd ISO weeks are off
                for date_obj in weekday_dates:
                    iso_week = date_obj.isocalendar()[1]
                    is_week_off = iso_week % 2 == 1
                    if (
                        weekday == 5
                        and date_obj >= SATURDAY_ALTERNATE_SHIFT_START
                    ):
                        is_week_off = not is_week_off
                    if is_week_off and date_obj not in leave_dates:
                        leave_dates.append(date_obj)
            elif has_even_pattern and not has_odd_pattern:
                # Alternating pattern: even ISO weeks are off
                for date_obj in weekday_dates:
                    iso_week = date_obj.isocalendar()[1]
                    is_week_off = iso_week % 2 == 0
                    if (
                        weekday == 5
                        and date_obj >= SATURDAY_ALTERNATE_SHIFT_START
                    ):
                        is_week_off = not is_week_off
                    if is_week_off and date_obj not in leave_dates:
                        leave_dates.append(date_obj)
            else:
                # Specific weeks only (not alternating) - use week-of-month logic
                for week_idx in week_indices:
                    if week_idx < len(weekday_dates):
                        date_obj = weekday_dates[week_idx]
                        if date_obj not in leave_dates:
                            leave_dates.append(date_obj)
    
    # Explicit one-time Saturday WO override.
    if (
        SATURDAY_ONE_TIME_WEEK_OFF.year == year
        and SATURDAY_ONE_TIME_WEEK_OFF.month == month
        and SATURDAY_ONE_TIME_WEEK_OFF not in leave_dates
    ):
        leave_dates.append(SATURDAY_ONE_TIME_WEEK_OFF)
    
    # Temporary override: May 23, 2026 as WO for May 2026 only
    if year == 2026 and month == 5:
        may_23_2026 = date(2026, 5, 23)
        if may_23_2026 not in leave_dates:
            leave_dates.append(may_23_2026)

    # Temporary override: May 30, 2026 as working day for May 2026 only (remove from WO)
    if year == 2026 and month == 5:
        may_30_2026 = date(2026, 5, 30)
        if may_30_2026 in leave_dates:
            leave_dates.remove(may_30_2026)

    # Temporary override: July 18, 2026 as WO for July 2026 only
    if year == 2026 and month == 7:
        july_18_2026 = date(2026, 7, 18)
        if july_18_2026 not in leave_dates:
            leave_dates.append(july_18_2026)

    # Temporary override: July 25, 2026 as WO for July 2026 only
    if year == 2026 and month == 7:
        july_25_2026 = date(2026, 7, 25)
        if july_25_2026 not in leave_dates:
            leave_dates.append(july_25_2026)

    return leave_dates


def validate_time_in_minutes(value):
    """
    this method is used to validate the format of duration like fields.
    """
    if len(value) > 5:
        raise ValidationError(_("Invalid format, it should be MM:SS format"))
    try:
        minutes, sec = value.split(":")
        if len(minutes) > 2 or len(sec) > 2:
            raise ValidationError(_("Invalid time, excepted MM:SS"))
        minutes = int(minutes)
        sec = int(sec)
        if minutes not in range(60) or sec not in range(60):
            raise ValidationError(_("Invalid time, excepted MM:SS"))
    except ValueError as e:
        raise ValidationError(_("Invalid format,  excepted MM:SS")) from e


class Request:
    """
    Represents a request for clock-in or clock-out.

    Attributes:
    - user: The user associated with the request.
    - date: The date of the request.
    - time: The time of the request.
    - path: The path associated with the request (default: "/").
    - session: The session data associated with the request (default: {"title": None}).
    """

    def __init__(
        self,
        user,
        date,
        time,
        datetime,
    ) -> None:
        self.user = user
        self.path = "/"
        self.session = {"title": None}
        self.date = date
        self.time = time
        self.datetime = datetime
        self.META = META()


class META:
    """
    Provides access to HTTP metadata keys.
    """

    @classmethod
    def keys(cls):
        """
        Retrieve the list of available HTTP metadata keys.

        Returns:
            list: A list of HTTP metadata keys.
        """
        return ["HTTP_HX_REQUEST"]


def parse_time(time_str):
    if isinstance(time_str, time):  # Check if it's already a time object
        return time_str

    if isinstance(time_str, str):
        for format_str in HORILLA_TIME_FORMATS.values():
            try:
                return datetime.strptime(time_str, format_str).time()
            except ValueError:
                continue
    return None


def parse_date(date_str, error_key, activity):
    try:
        return pd.to_datetime(date_str).date()
    except (pd.errors.ParserError, ValueError):
        activity[error_key] = f"Invalid date format for {error_key.split()[-1]}"
        return None


def parse_datetime(date_str, time_str):
    return (
        datetime.strptime(f"{date_str} {time_str[:5]}", "%Y-%m-%d %H:%M")
        if date_str and time_str
        else None
    )


def parse_attendance_requested_data(raw):
    """
    Normalize Attendance.requested_data for reads. JSONField returns a dict;
    older code paths stored or assumed a JSON string and used json.loads().
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        s = raw.strip()
        return json.loads(s) if s else {}
    return {}


def recalculate_worked_hour_from_clock(attendance):
    """
    Set attendance.attendance_worked_hour from clock_in and clock_out so that
    WorkRecord status (MP/FDP/HDP) is correct after approval. Returns True if updated.
    """
    cin_date = getattr(attendance, "attendance_clock_in_date", None)
    cin_time = getattr(attendance, "attendance_clock_in", None)
    cout_date = getattr(attendance, "attendance_clock_out_date", None)
    cout_time = getattr(attendance, "attendance_clock_out", None)
    if not all([cin_date, cin_time, cout_date, cout_time]):
        return False
    try:
        if isinstance(cin_time, time):
            cin_dt = datetime.combine(cin_date, cin_time)
        else:
            cin_str = str(cin_time)[:5] if len(str(cin_time)) >= 5 else str(cin_time)
            cin_dt = datetime.strptime(f"{cin_date!s} {cin_str}", "%Y-%m-%d %H:%M")
        if isinstance(cout_time, time):
            cout_dt = datetime.combine(cout_date, cout_time)
        else:
            cout_str = str(cout_time)[:5] if len(str(cout_time)) >= 5 else str(cout_time)
            cout_dt = datetime.strptime(f"{cout_date!s} {cout_str}", "%Y-%m-%d %H:%M")
        total_seconds = (cout_dt - cin_dt).total_seconds()
        if total_seconds < 0:
            return False
        attendance.attendance_worked_hour = format_time(int(total_seconds))
        return True
    except (ValueError, TypeError):
        return False


def get_date(date):
    if isinstance(date, datetime):
        return date
    elif isinstance(date, str):
        for format_name, format_str in HORILLA_DATE_FORMATS.items():
            try:
                return datetime.strptime(date, format_str)
            except ValueError:
                continue
    return None


def sort_activity_dicts(activity_dicts):

    for activity in activity_dicts:
        activity["Attendance Date"] = get_date(activity["Attendance Date"])

    # Filter out any entries where the date could not be parsed
    activity_dicts = [
        activity
        for activity in activity_dicts
        if activity["Attendance Date"] is not None
    ]
    sorted_activity_dicts = sorted(activity_dicts, key=lambda x: x["Attendance Date"])
    return sorted_activity_dicts
