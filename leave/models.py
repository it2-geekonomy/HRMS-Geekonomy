import calendar
import logging
import math
import operator
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from base.horilla_company_manager import HorillaCompanyManager
from base.models import (
    Company,
    CompanyLeaves,
    Department,
    Holidays,
    JobPosition,
    MultipleApprovalCondition,
    clear_messages,
)
from employee.models import Employee, EmployeeWorkInformation
from horilla import horilla_middlewares
from horilla.models import HorillaModel, upload_path
from horilla_audit.methods import get_diff
from horilla_audit.models import HorillaAuditInfo, HorillaAuditLog
from leave.methods import (
    calculate_requested_days,
    company_leave_dates_list,
    computed_balance_for_validation,
    holiday_dates_list,
    probation_leave_days_in_month,
)

logger = logging.getLogger(__name__)

operator_mapping = {
    "equal": operator.eq,
    "notequal": operator.ne,
    "lt": operator.lt,
    "gt": operator.gt,
    "le": operator.le,
    "ge": operator.ge,
    "icontains": operator.contains,
}
# Create your models here.
BREAKDOWN = [
    ("full_day", _("Full Day")),
    ("first_half", _("First Half")),
    ("second_half", _("Second Half")),
]
CHOICES = [("yes", "Yes"), ("no", "No")]

RESET_BASED = [
    ("yearly", _("Yearly")),
    ("monthly", _("Monthly")),
    ("weekly", _("Weekly")),
]
MONTHS = [
    ("1", _("Jan")),
    ("2", _("Feb")),
    ("3", _("Mar")),
    ("4", _("Apr")),
    ("5", _("May")),
    ("6", _("Jun")),
    ("7", _("Jul")),
    ("8", _("Aug")),
    ("9", _("Sep")),
    ("10", _("Oct")),
    ("11", _("Nov")),
    ("12", _("Dec")),
]

DAYS = [
    ("last day", _("Last Day")),
    ("1", "1st"),
    ("2", "2nd"),
    ("3", "3rd"),
    ("4", "4th"),
    ("5", "5th"),
    ("6", "6th"),
    ("7", "7th"),
    ("8", "8th"),
    ("9", "9th"),
    ("10", "10th"),
    ("11", "11th"),
    ("12", "12th"),
    ("13", "13th"),
    ("14", "14th"),
    ("15", "15th"),
    ("16", "16th"),
    ("17", "17th"),
    ("18", "18th"),
    ("19", "19th"),
    ("20", "20th"),
    ("21", "21th"),
    ("22", "22th"),
    ("23", "23th"),
    ("24", "24th"),
    ("25", "25th"),
    ("26", "26th"),
    ("27", "27th"),
    ("28", "28th"),
    ("29", "29th"),
    ("30", "30th"),
    ("31", "31th"),
]


TIME_PERIOD = [("day", _("Day")), ("month", _("Month")), ("year", _("Year"))]

PAYMENT = [("paid", _("Paid")), ("unpaid", _("LOP"))]

CARRYFORWARD_TYPE = [
    ("no carryforward", _("No Carry Forward")),
    ("carryforward", _("Carry Forward")),
    ("carryforward expire", _("Carry Forward with Expire")),
]

ACCRUAL_PLAN = [("job_position", _("Job Position")), ("job_role", _("Job Role"))]


LEAVE_STATUS = (
    ("requested", _("Requested")),
    ("approved", _("Approved")),
    ("cancelled", _("Cancelled")),
    ("rejected", _("Rejected")),
)

LEAVE_ALLOCATION_STATUS = (
    ("requested", _("Requested")),
    ("approved", _("Approved")),
    ("rejected", _("Rejected")),
)

COMP_OFF_REQUEST_STATUS = (
    ("requested", _("Requested")),
    ("approved", _("Approved")),
    ("rejected", _("Rejected")),
    ("cancelled", _("Cancelled")),
)

WEEKS = [
    ("0", _("First Week")),
    ("1", _("Second Week")),
    ("2", _("Third Week")),
    ("3", _("Fourth Week")),
    ("4", _("Fifth Week")),
]


WEEK_DAYS = [
    ("0", _("Monday")),
    ("1", _("Tuesday")),
    ("2", _("Wednesday")),
    ("3", _("Thursday")),
    ("4", _("Friday")),
    ("5", _("Saturday")),
    ("6", _("Sunday")),
]


class LeaveType(HorillaModel):
    icon = models.ImageField(
        null=True, blank=True, upload_to=upload_path, verbose_name=_("Icon")
    )
    name = models.CharField(max_length=30, null=False, verbose_name=_("Name"))
    color = models.CharField(null=True, max_length=30, verbose_name=_("Color"))
    payment = models.CharField(
        max_length=30, choices=PAYMENT, default="unpaid", verbose_name=_("Is Paid")
    )
    count = models.FloatField(null=True, default=1)
    period_in = models.CharField(max_length=30, choices=TIME_PERIOD, default="day")
    limit_leave = models.BooleanField(default=True, verbose_name=_("Limit Leave Days"))
    total_days = models.FloatField(null=True, default=1)
    reset = models.BooleanField(default=False, verbose_name=_("Reset"))
    is_encashable = models.BooleanField(default=False, verbose_name=_("Is Encashable"))
    reset_based = models.CharField(
        max_length=30,
        choices=RESET_BASED,
        blank=True,
        null=True,
        verbose_name=_("Reset Period"),
    )
    reset_month = models.CharField(
        max_length=30, choices=MONTHS, blank=True, verbose_name=_("Reset Month")
    )
    reset_day = models.CharField(
        max_length=30, choices=DAYS, null=True, blank=True, verbose_name=_("Reset Day")
    )
    reset_weekend = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        choices=WEEK_DAYS,
        verbose_name=_("Reset Weekday"),
    )
    carryforward_type = models.CharField(
        max_length=30,
        choices=CARRYFORWARD_TYPE,
        default="no carryforward",
        verbose_name=_("Carryforward Type"),
    )
    carryforward_max = models.FloatField(
        null=True, blank=True, verbose_name=_("Carryforward Max")
    )
    carryforward_expire_in = models.IntegerField(
        null=True, blank=True, verbose_name=_("Carryforward Expire In")
    )
    carryforward_expire_period = models.CharField(
        max_length=30,
        choices=TIME_PERIOD,
        null=True,
        blank=True,
        verbose_name=_("Carryforward Expire Period"),
    )
    carryforward_expire_date = models.DateField(
        null=True, blank=True, verbose_name=_("Carryforward Expire Date")
    )
    require_approval = models.CharField(
        max_length=30,
        choices=CHOICES,
        null=True,
        blank=True,
        default="yes",
        verbose_name=_("Require Approval"),
    )
    require_attachment = models.CharField(
        max_length=30,
        choices=CHOICES,
        default="no",
        null=True,
        blank=True,
        verbose_name=_("Require Attachment"),
    )
    exclude_company_leave = models.CharField(
        max_length=30,
        choices=CHOICES,
        default="no",
        verbose_name=_("Exclude Company Holidays"),
    )
    exclude_holiday = models.CharField(
        max_length=30, choices=CHOICES, default="no", verbose_name=_("Exclude Holidays")
    )
    is_compensatory_leave = models.BooleanField(default=False)
    company_id = models.ForeignKey(
        Company, null=True, editable=False, on_delete=models.PROTECT
    )
    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        ordering = ["-id"]

    def get_avatar(self):
        """
        Method will retun the api to the avatar or path to the profile image
        """
        url = f"https://ui-avatars.com/api/?name={self.name}&background=random"
        if self.icon:
            full_filename = self.icon.name

            if default_storage.exists(full_filename):
                url = self.icon.url
        return url

    def leave_type_next_reset_date(self):
        today = datetime.now().date()

        if not self.reset:
            return None

        def get_reset_day(month, day):
            return (
                calendar.monthrange(today.year, month)[1]
                if day == "last day"
                else int(day)
            )

        if self.reset_based == "yearly":
            month, day = int(self.reset_month), get_reset_day(
                int(self.reset_month), self.reset_day
            )
            reset_date = datetime(
                today.year + (datetime(today.year, month, day).date() < today),
                month,
                day,
            ).date()

        elif self.reset_based == "monthly":
            month = today.month
            reset_date = datetime(
                today.year, month, get_reset_day(month, self.reset_day)
            ).date()
            if reset_date < today:
                month = (month % 12) + 1
                year = today.year + (month == 1)
                reset_date = datetime(
                    year, month, get_reset_day(month, self.reset_day)
                ).date()

        elif self.reset_based == "weekly":
            target_weekday = WEEK_DAYS[self.reset_day]
            days_until_reset = (target_weekday - today.weekday()) % 7 or 7
            reset_date = today + timedelta(days=days_until_reset)

        else:
            reset_date = None

        return reset_date

    def set_expired_date(self, assigned_date):
        period = self.carryforward_expire_in
        if self.carryforward_expire_period == "day":
            expired_date = assigned_date + relativedelta(days=period)
        elif self.carryforward_expire_period == "month":
            expired_date = assigned_date + relativedelta(months=period)
        else:
            expired_date = assigned_date + relativedelta(years=period)

        return expired_date

    def clean(self, *args, **kwargs):
        if self.is_compensatory_leave:
            if (
                LeaveType.objects.filter(is_compensatory_leave=True)
                .exclude(pk=self.pk)
                .exists()
            ):
                raise ValidationError(
                    {"name": _("Compensatory Leave Request already exists.")}
                )

    def save(self, *args, **kwargs):
        request = getattr(horilla_middlewares._thread_locals, "request", None)
        selected_company = None
        if request and hasattr(request, 'session'):
            selected_company = request.session.get("selected_company")
        if (
            not self.id
            and not self.company_id
            and selected_company
            and selected_company != "all"
        ):
            self.company_id = Company.find(selected_company)

        if (
            self.carryforward_type != "no carryforward"
            and self.carryforward_max is None
        ):
            self.carryforward_max = math.inf
        if self.pk and LeaveType.objects.get(id=self.pk).is_compensatory_leave:
            self.is_compensatory_leave = True

        # Use type-level expire date only when in/period are not set (else per-employee from assigned_date)
        if self.carryforward_type == "carryforward expire":
            if (
                not self.carryforward_expire_date
                and not (self.carryforward_expire_in and self.carryforward_expire_period)
            ):
                self.carryforward_expire_date = self.set_expired_date(
                    assigned_date=self.created_at
                )
        else:
            self.carryforward_expire_date = None

        super().save()

    def __str__(self):
        return self.name


class Holiday(HorillaModel):
    name = models.CharField(max_length=30, null=False, verbose_name=_("Name"))
    start_date = models.DateField(verbose_name=_("Start Date"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("End Date"))
    recurring = models.BooleanField(default=False, verbose_name=_("Recurring"))
    company_id = models.ForeignKey(
        Company, null=True, editable=False, on_delete=models.PROTECT
    )
    objects = HorillaCompanyManager(related_company_field="company_id")

    def __str__(self):
        return self.name


class CompanyLeave(HorillaModel):
    based_on_week = models.CharField(
        max_length=100, choices=WEEKS, blank=True, null=True
    )
    based_on_week_day = models.CharField(max_length=100, choices=WEEK_DAYS)
    company_id = models.ForeignKey(
        Company, null=True, editable=False, on_delete=models.PROTECT
    )
    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        unique_together = ("based_on_week", "based_on_week_day")

    def __str__(self):
        return f"{dict(WEEK_DAYS).get(self.based_on_week_day)} | {dict(WEEKS).get(self.based_on_week)}"


class AvailableLeave(HorillaModel):
    employee_id = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="available_leave",
        verbose_name=_("Employee"),
    )
    leave_type_id = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="employee_available_leave",
        blank=True,
        null=True,
        verbose_name=_("Leave type"),
    )
    available_days = models.FloatField(default=0, verbose_name=_("Available Days"))
    carryforward_days = models.FloatField(
        default=0, verbose_name=_("Carryforward Days")
    )
    total_leave_days = models.FloatField(default=0, verbose_name=_("Total Leave Days"))
    assigned_date = models.DateField(
        default=timezone.now, verbose_name=_("Assigned Date")
    )
    reset_date = models.DateField(
        blank=True, null=True, verbose_name=_("Leave Reset Date")
    )
    expired_date = models.DateField(
        blank=True, null=True, verbose_name=_("CarryForward Expired Date")
    )
    objects = HorillaCompanyManager(
        related_company_field="employee_id__employee_work_info__company_id"
    )
    history = HorillaAuditLog(
        related_name="history_set",
        bases=[
            HorillaAuditInfo,
        ],
    )

    class Meta:
        unique_together = ("leave_type_id", "employee_id")

    def __str__(self):
        return f"{self.employee_id} | {self.leave_type_id}"

    def forcasted_leaves(self, date):
        if isinstance(date, str):
            date = datetime.strptime(date, "%Y-%m-%d").date()
        next_reset_date = self.leave_type_id.leave_type_next_reset_date()
        if next_reset_date and next_reset_date <= date:
            return self.leave_type_id.total_days

        return 0

    # Resetting carryforward days

    def update_carryforward(self):
        if self.leave_type_id.carryforward_type != "no carryforward":
            if self.leave_type_id.carryforward_max >= self.total_leave_days:
                self.carryforward_days = self.total_leave_days
            else:
                self.carryforward_days = self.leave_type_id.carryforward_max
        self.available_days = self.leave_type_id.total_days

    # Setting the reset date for carryforward leaves

    def set_reset_date(self, assigned_date, available_leave):
        if available_leave.leave_type_id.reset_based == "monthly":
            reset_day = available_leave.leave_type_id.reset_day
            if reset_day == "last day":
                temp_date = assigned_date + relativedelta(months=0, day=31)
                if assigned_date < temp_date:
                    reset_date = temp_date
                else:
                    reset_date = assigned_date + relativedelta(months=1, day=31)

            else:
                temp_date = assigned_date + relativedelta(months=0, day=int(reset_day))
                if assigned_date < temp_date:
                    reset_date = temp_date
                else:
                    reset_date = assigned_date + relativedelta(
                        months=1, day=int(reset_day)
                    )

        elif available_leave.leave_type_id.reset_based == "weekly":
            temp = 7 - (
                assigned_date.isoweekday()
                - int(available_leave.leave_type_id.reset_weekend)
                - 1
            )
            if temp != 7:
                reset_date = assigned_date + relativedelta(days=(temp % 7))
            else:
                reset_date = assigned_date + relativedelta(days=7)
        else:
            reset_month = int(available_leave.leave_type_id.reset_month)
            reset_day = available_leave.leave_type_id.reset_day

            if reset_day == "last day":
                temp_date = assigned_date + relativedelta(
                    years=0, month=reset_month, day=31
                )
                if assigned_date < temp_date:
                    reset_date = temp_date
                else:
                    reset_date = assigned_date + relativedelta(
                        years=1, month=reset_month, day=31
                    )
            else:
                temp_date = assigned_date + relativedelta(
                    years=0, month=reset_month, day=int(reset_day)
                )
                if assigned_date < temp_date:
                    reset_date = temp_date
                else:
                    # nth_day = int(reset_day)
                    reset_date = assigned_date + relativedelta(
                        years=1, month=reset_month, day=int(reset_day)
                    )

        return reset_date

    def leave_taken(self):
        leave_taken = LeaveRequest.objects.filter(
            leave_type_id=self.leave_type_id,
            employee_id=self.employee_id,
            status="approved",
        ).aggregate(total_sum=Sum("requested_days"))

        return leave_taken["total_sum"] if leave_taken["total_sum"] else 0

    # Setting the expiration date for carryforward leaves
    def set_expired_date(self, available_leave, assigned_date):
        period = available_leave.leave_type_id.carryforward_expire_in
        if available_leave.leave_type_id.carryforward_expire_period == "day":
            expired_date = assigned_date + relativedelta(days=period)
        elif available_leave.leave_type_id.carryforward_expire_period == "month":
            expired_date = assigned_date + relativedelta(months=period)
        else:
            expired_date = assigned_date + relativedelta(years=period)

        available_leave.carryforward_days = 0
        available_leave.available_days = available_leave.leave_type_id.total_days
        return expired_date

    def pre_save_processing(self):
        """
        Reusable method to compute fields normally set in save().
        """
        # Logic for reset_date
        if self.reset_date is None and self.leave_type_id.reset:
            self.reset_date = self.set_reset_date(
                assigned_date=self.assigned_date, available_leave=self
            )

        # Logic for expired_date
        if self.leave_type_id.carryforward_type == "carryforward expire":
            lt = self.leave_type_id
            if lt.carryforward_expire_in is not None and lt.carryforward_expire_period:
                # Per-employee: assigned_date + (expire_in, period), e.g. 3 years from assign
                period = lt.carryforward_expire_period
                n = lt.carryforward_expire_in
                if period == "day":
                    expiry_date = self.assigned_date + relativedelta(days=n)
                elif period == "month":
                    expiry_date = self.assigned_date + relativedelta(months=n)
                else:
                    expiry_date = self.assigned_date + relativedelta(years=n)
            else:
                expiry_date = self.assigned_date
                if lt.carryforward_expire_date:
                    expiry_date = lt.carryforward_expire_date
            self.expired_date = expiry_date

        # Compute total_leave_days and ensure carryforward_days >= 0
        self.total_leave_days = round(
            max(self.available_days + self.carryforward_days, 0), 3
        )
        self.carryforward_days = round(max(self.carryforward_days, 0), 3)

    def save(self, *args, **kwargs):
        self.pre_save_processing()
        super().save(*args, **kwargs)


def restrict_leaves(restri):

    restricted_dates = []
    restricted_days = RestrictLeave.objects.filter(id=restri)
    for i in restricted_days:
        restrict_start_date = i.start_date
        restrict_end_date = i.end_date
        total_days = restrict_end_date - restrict_start_date
        for i in range(total_days.days + 1):
            date = restrict_start_date + timedelta(i)
            restricted_dates.append(date)
    return restricted_dates


def leave_requested_dates(start_date, end_date):
    """
    Returns a list of dates from the start date to the end date.
    """
    if end_date is None:
        end_date = start_date
    return [start_date + timedelta(i) for i in range((end_date - start_date).days + 1)]


class LeaveRequest(HorillaModel):
    employee_id = models.ForeignKey(
        Employee, on_delete=models.CASCADE, verbose_name=_("Employee")
    )
    leave_type_id = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, verbose_name=_("Leave Type")
    )
    start_date = models.DateField(null=False, verbose_name=_("Start Date"))
    start_date_breakdown = models.CharField(
        max_length=30,
        choices=BREAKDOWN,
        default="full_day",
        verbose_name=_("Start Date Breakdown"),
    )
    end_date = models.DateField(null=True, blank=True, verbose_name=_("End Date"))
    end_date_breakdown = models.CharField(
        max_length=30,
        choices=BREAKDOWN,
        default="full_day",
        verbose_name=_("End Date Breakdown"),
    )
    requested_days = models.FloatField(
        blank=True, null=True, verbose_name=_("Requested Days")
    )
    leave_clashes_count = models.IntegerField(
        default=0, verbose_name=_("Leave Clashes Count")
    )
    description = models.TextField(verbose_name=_("Description"), max_length=255)
    attachment = models.FileField(
        null=True,
        blank=True,
        upload_to=upload_path,
        verbose_name=_("Attachment"),
    )
    status = models.CharField(
        max_length=30,
        choices=LEAVE_STATUS,
        default="requested",
        verbose_name=_("Status"),
    )
    requested_date = models.DateField(
        default=timezone.now, verbose_name=_("Created Date")
    )
    approved_available_days = models.FloatField(default=0)
    approved_carryforward_days = models.FloatField(default=0)
    reject_reason = models.TextField(
        blank=True, verbose_name=_("Reject Reason"), max_length=255
    )
    history = HorillaAuditLog(
        related_name="history_set",
        bases=[
            HorillaAuditInfo,
        ],
    )
    created_by = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="leave_request_created",
        verbose_name=_("Created By"),
    )
    objects = HorillaCompanyManager(
        related_company_field="employee_id__employee_work_info__company_id"
    )

    class Meta:
        ordering = ["-id"]
        verbose_name = "Leave Request"
        verbose_name_plural = "Leave Requests"

    def tracking(self):
        return get_diff(self)

    def __str__(self):
        return f"{self.employee_id} | {self.leave_type_id} | {self.status}"

    def employees_on_leave_today(today=None, status=None):
        """
        Retrieve employees who are on leave on a given date (default is today).

        Args:
            today (date, optional): The date to check. Defaults to the current date
                                    in the server's local timezone.
            status (str, optional): The status to filter leave requests. If None, no filtering by status is applied.

        Returns:
            QuerySet: A queryset of LeaveRequest instances where employees are on leave on the specified date.
        """
        today = date.today() if today is None else today
        queryset = LeaveRequest.objects.filter(
            start_date__lte=today, end_date__gte=today
        )

        if status is not None:
            queryset = queryset.filter(status=status)

        return queryset

    def get_penalties_count(self):
        """
        This method is used to return the total penalties in the late early instance
        """
        return self.penaltyaccounts_set.count()

    def requested_dates(self):
        """
        :return: this functions returns a list of dates from start date to end date.
        """
        request_start_date = self.start_date
        request_end_date = self.end_date
        if request_end_date is None:
            request_end_date = self.start_date
        requested_days = request_end_date - request_start_date
        requested_dates = []
        for i in range(requested_days.days + 1):
            date = request_start_date + timedelta(i)
            requested_dates.append(date)
        return requested_dates

    def holiday_dates(self):
        """
        :return: this functions returns a list of all holiday dates.
        """
        holiday_dates = []
        holidays = Holidays.objects.all()
        for holiday in holidays:
            holiday_start_date = holiday.start_date
            holiday_end_date = holiday.end_date
            if holiday_end_date is None:
                holiday_end_date = holiday_start_date
            holiday_days = holiday_end_date - holiday_start_date
            for i in range(holiday_days.days + 1):
                date = holiday_start_date + timedelta(i)
                holiday_dates.append(date)
        return holiday_dates

    def company_leave_dates(self):
        """
        :return: This function returns a list of all company leave dates"""
        from datetime import date

        company_leaves = CompanyLeaves.objects.all()
        company_leave_dates = []
        for company_leave in company_leaves:
            if self:
                year = self.start_date.year
            else:
                year = date.today().year
            based_on_week = company_leave.based_on_week
            based_on_week_day = company_leave.based_on_week_day
            for month in range(1, 13):
                if based_on_week != None:
                    # Set Sunday as the first day of the week
                    calendar.setfirstweekday(6)
                    month_calendar = calendar.monthcalendar(year, month)
                    try:
                        weeks = month_calendar[int(based_on_week)]
                        weekdays_in_weeks = [day for day in weeks if day != 0]
                        for day in weekdays_in_weeks:
                            date = datetime.strptime(
                                f"{year}-{month:02}-{day:02}", "%Y-%m-%d"
                            ).date()
                            if (
                                date.weekday() == int(based_on_week_day)
                                and date not in company_leave_dates
                            ):
                                company_leave_dates.append(date)
                    except IndexError:
                        pass
                else:
                    # Set Monday as the first day of the week
                    calendar.setfirstweekday(0)
                    month_calendar = calendar.monthcalendar(year, month)
                    for week in month_calendar:
                        if week[int(based_on_week_day)] != 0:
                            date = datetime.strptime(
                                f"{year}-{month:02}-{week[int(based_on_week_day)]:02}",
                                "%Y-%m-%d",
                            ).date()
                            if date not in company_leave_dates:
                                company_leave_dates.append(date)
        return company_leave_dates

    def leaveoverlapping(self):
        """
        Checks for overlapping leave requests based on the current instance's dates and employee.
        """
        overlapping_requests = LeaveRequest.objects.filter(
            employee_id=self.employee_id,
            start_date__lte=self.end_date,
            end_date__gte=self.start_date,
        ).exclude(id=self.id)

        if overlapping_requests.exists():
            existing_leave = overlapping_requests.first()

            # Handle specific start_date_breakdown and end_date_breakdown mismatch
            if (
                existing_leave.start_date == self.start_date
                and existing_leave.start_date_breakdown != "full_day"
                and self.start_date_breakdown != "full_day"
                and existing_leave.start_date_breakdown != self.start_date_breakdown
                and existing_leave.end_date_breakdown != self.end_date_breakdown
            ):
                return LeaveRequest.objects.none()

        return overlapping_requests

    def save(self, *args, **kwargs):

        self.requested_days = calculate_requested_days(
            self.start_date,
            self.end_date,
            self.start_date_breakdown,
            self.end_date_breakdown,
            exclude_holidays=True,  # Automatically exclude holidays and company leaves
            employee_id=self.employee_id,
        )

        if self.status in ["cancelled", "rejected"]:
            self.leave_clashes_count = 0
        else:
            self.leave_clashes_count = self.count_leave_clashes()

        super().save(*args, **kwargs)

        self.update_leave_clashes_count()
        work_info = EmployeeWorkInformation.objects.filter(employee_id=self.employee_id)
        department_id = None
        conditions = None
        if work_info.exists():
            department_id = self.employee_id.employee_work_info.department_id
            emp_comp_id = self.employee_id.employee_work_info.company_id
        requested_days = self.requested_days
        applicable_condition = False
        if department_id != None and emp_comp_id != None:
            conditions = MultipleApprovalCondition.objects.filter(
                department=department_id, company_id=emp_comp_id
            ).order_by("condition_value")
        if conditions != None:
            for condition in conditions:
                operator = condition.condition_operator
                if operator == "range":
                    start_value = float(condition.condition_start_value)
                    end_value = float(condition.condition_end_value)
                    if start_value <= requested_days <= end_value:
                        applicable_condition = condition
                        break
                else:
                    operator_func = operator_mapping.get(condition.condition_operator)
                    condition_value = type(requested_days)(condition.condition_value)
                    if operator_func(requested_days, condition_value):
                        applicable_condition = condition
                        break

        if applicable_condition and self.status == "requested":
            LeaveRequestConditionApproval.objects.filter(leave_request_id=self).delete()
            sequence = 0
            managers = applicable_condition.approval_managers()
            for manager in managers:
                if not isinstance(manager, Employee):
                    manager = getattr(self.employee_id.employee_work_info, manager)
                if manager:
                    sequence += 1
                    LeaveRequestConditionApproval.objects.create(
                        sequence=sequence,
                        leave_request_id=self,
                        manager_id=manager,
                    )

    def clean(self):
        cleaned_data = super().clean()
        leave_type = getattr(self, "leave_type_id", None)
        if not leave_type:  # 836
            return
        attachment = getattr(self, "attachment", None)
        requ_days = set(self.requested_dates())
        restricted_leaves = RestrictLeave.objects.all()
        request = getattr(horilla_middlewares._thread_locals, "request", None)

        # Check if leave type is assigned to employee
        if not AvailableLeave.objects.filter(
            employee_id=self.employee_id, leave_type_id=leave_type
        ).exists():
            raise ValidationError(
                {
                    "leave_type_id": _(
                        "The selected leave type is not assigned to this employee."
                    )
                }
            )

        # Date validations
        if self.start_date > self.end_date:
            raise ValidationError(_("End date should not be less than start date."))

        if (
            self.start_date == self.end_date
            and self.start_date_breakdown != self.end_date_breakdown
        ):
            raise ValidationError(
                _("Mismatch in the breakdown of the start and end date.")
            )

        # Sick Leave (full-time, non-probation): up to 2 days without attachment;
        # more than 2 days requires a medical certificate.
        if leave_type and leave_type.name == "Sick Leave":
            requested_days_sl = calculate_requested_days(
                self.start_date,
                self.end_date,
                self.start_date_breakdown,
                self.end_date_breakdown,
                exclude_holidays=True,  # Automatically exclude holidays and company leaves
                employee_id=self.employee_id,
            )
            if requested_days_sl > 2 and not attachment:
                raise ValidationError(
                    {
                        "attachment": _(
                            "For Sick Leave of more than 2 days, a medical certificate must be uploaded. "
                            "Please attach your medical certificate to apply for more than 2 days of sick leave."
                        )
                    }
                )

        # Attachment requirement (Sick Leave is handled above)
        if (
            leave_type
            and leave_type.require_attachment == "yes"
            and leave_type.name != "Sick Leave"
            and not attachment
        ):
            raise ValidationError(
                {"attachment": _("An attachment is required for this leave request")}
            )

        # Overlapping leave check
        if self.start_date and self.end_date:
            overlapping_requests = self.leaveoverlapping().exclude(id=self.id)
            if overlapping_requests.exclude(
                status__in=["cancelled", "rejected"]
            ).exists():
                raise ValidationError(
                    _("Employee already has a leave request for this date range.")
                )

        # Past date restriction
        if (
            not request.user.is_superuser
            and EmployeePastLeaveRestrict.objects.filter(enabled=True).exists()
        ):
            restrict = EmployeePastLeaveRestrict.objects.first()
            if restrict and self.start_date < date.today():
                raise ValidationError(_("Requests cannot be made for past dates."))

        # Earned Leave: must be applied at least 5 days before the start date
        lt_name = (leave_type.name or "").strip()
        if leave_type and "Earned Leave" in lt_name:
            today = date.today()
            min_start_date = today + timedelta(days=5)
            if self.start_date < min_start_date:
                raise ValidationError(
                    _(
                        "Earned Leave must be applied at least 5 days before the start date. "
                        "Please choose a start date on or after %(min_date)s."
                    )
                    % {"min_date": min_start_date.strftime("%d/%m/%Y")}
                )

        # Comp Off Leave: must be applied at least 5 days before the start date (same as Earned Leave)
        lt_name_lower = lt_name.lower()
        if leave_type and ("comp off" in lt_name_lower or "comp-off" in lt_name_lower):
            today = date.today()
            min_start_date = today + timedelta(days=5)
            if self.start_date < min_start_date:
                raise ValidationError(
                    _(
                        "Comp Off Leave must be applied at least 5 days before the start date. "
                        "Please choose a start date on or after %(min_date)s."
                    )
                    % {"min_date": min_start_date.strftime("%d/%m/%Y")}
                )

        # Avaialable leave days and requested leave days checking
        available_leave = AvailableLeave.objects.get(
            employee_id=self.employee_id, leave_type_id=leave_type
        )

        requested_days = calculate_requested_days(
            self.start_date,
            self.end_date,
            self.start_date_breakdown,
            self.end_date_breakdown,
            exclude_holidays=True,  # Automatically exclude holidays and company leaves
            employee_id=self.employee_id,
        )

        # Casual Leave: maximum 2 days per request (even with carry-forward).
        cl_names = ("Casual Leave", "Casual Leave (CL)", "Casual Leave – Paid")
        if leave_type and (leave_type.name in cl_names or (leave_type.name or "").strip().startswith("Casual Leave")):
            if requested_days > 2:
                raise ValidationError(
                    _(
                        "Casual Leave: You can apply for a maximum of 2 days at a time. "
                        "Please submit separate requests for additional days."
                    )
                )

        # Earned Leave: when employee has carryforward, maximum 4 days per request.
        if leave_type and "Earned Leave" in (leave_type.name or ""):
            av_leave = AvailableLeave.objects.filter(
                employee_id=self.employee_id, leave_type_id=leave_type
            ).first()
            cf_days = (av_leave.carryforward_days or 0) if av_leave else 0
            if cf_days > 0 and requested_days > 4:
                raise ValidationError(
                    _(
                        "Earned Leave: When you have carry forward balance, you can apply for a maximum of 4 days at a time. "
                        "Please submit separate requests for additional days."
                    )
                )

        leave_dates = leave_requested_dates(self.start_date, self.end_date)
        month_year = [f"{date.year}-{date.strftime('%m')}" for date in leave_dates]
        today = datetime.today()
        unique_dates = list(set(month_year))
        if f"{today.month}-{today.year}" in unique_dates:
            unique_dates.remove(f"{today.strftime('%m')}-{today.year}")

        # For monthly accrual (Probation Leave, Casual Leave, Earned Leave), use same
        # computed balance as UI so validation matches displayed "Available Leave Days".
        # Probation Leave & Interns Leave: same logic. Use balance as of TODAY so the "current bucket"
        # (e.g. Jan unused + Feb) can be used to apply for past month. Case-insensitive name match.
        lt_name = (leave_type.name or "").strip()
        lt_name_lower = lt_name.lower()
        is_probation_or_interns = (
            "probation" in lt_name_lower or "interns leave" in lt_name_lower or "intern" in lt_name_lower
        )
        as_of = date.today() if is_probation_or_interns else self.start_date
        computed_total = computed_balance_for_validation(
            available_leave, as_of_date=as_of
        )
        if computed_total is not None:
            total_leave_days = computed_total
        else:
            forcated_days = available_leave.forcasted_leaves(self.start_date)
            available_days = available_leave.available_days or 0
            carryforward_days = available_leave.carryforward_days or 0
            carryforward_max = available_leave.leave_type_id.carryforward_max or 0
            carryforward_type = available_leave.leave_type_id.carryforward_type

            if carryforward_type in ["carryforward", "carryforward expire"]:
                carryforward_days = min(carryforward_days, carryforward_max)
            elif carryforward_type == "no carryforward":
                carryforward_days = 0

            total_leave_days = available_days + carryforward_days + forcated_days

        # Subtract days already in pending (requested) leave requests for this leave type
        pending_qs = LeaveRequest.objects.filter(
            employee_id=self.employee_id,
            leave_type_id=leave_type,
            status="requested",
        ).exclude(pk=self.pk)
        pending_days = pending_qs.aggregate(total=Sum("requested_days"))["total"] or 0
        effective_available = max(0, total_leave_days - pending_days)

        if not requested_days <= effective_available:
            raise ValidationError(
                _(
                    "Does not have sufficient leave balance for the requested dates. "
                    "You have %(pending)s day(s) already in pending requests; available for new request: %(available)s."
                )
                % {"pending": pending_days, "available": round(effective_available, 2)}
            )

        # Probation/Interns Leave: max 1 day per calendar month
        if is_probation_or_interns and requested_days > 0:
            days_in_month = probation_leave_days_in_month(
                self.employee_id,
                leave_type,
                self.start_date.year,
                self.start_date.month,
                exclude_leave_request_id=self.pk,
            )
            if days_in_month + requested_days > 1:
                raise ValidationError(
                    _(
                        "Probation Leave / Interns Leave: maximum 1 day per calendar month. "
                        "You already have %(days)s day(s) in %(month)s for this leave type."
                    )
                    % {
                        "days": days_in_month,
                        "month": self.start_date.strftime("%B %Y"),
                    }
                )

        # Comp Off: no per-month cap — use any earned balance on any date in the year
        # (year-end lapse is handled by leave scheduler on 1 Jan).

        # Skip further checks for superusers
        if request.user.is_superuser:
            return cleaned_data

        # Restricted leave checks
        for restrict in restricted_leaves:
            exclued_types = set(restrict.exclued_leave_types.all())
            specific_types = set(restrict.spesific_leave_types.all())

            is_restricted = False

            # Determine if the current leave type is restricted
            if restrict.include_all and not exclued_types:
                is_restricted = True
            elif exclued_types and leave_type not in exclued_types:
                is_restricted = True
            elif leave_type in specific_types:
                is_restricted = True

            if not is_restricted:
                continue

            restri_days = set(restrict_leaves(restrict.id))
            if not restri_days:
                continue

            # Check if requested days intersect with restricted days
            if requ_days & restri_days:
                if (
                    restrict.department == emp_dep
                    and not restrict.job_position.exists()
                ) or (emp_job and emp_job in restrict.job_position.all()):
                    raise ValidationError(
                        "You cannot request leave for this date range. The requested dates are restricted. Please contact admin."
                    )

        return cleaned_data

    def no_approval(self):
        # Deduct only from this request's leave type: Casual Leave never deducts from EL, and vice versa.
        employee_id = self.employee_id
        leave_type_id = self.leave_type_id
        available_leave = AvailableLeave.objects.get(
            leave_type_id=leave_type_id, employee_id=employee_id
        )
        if self.requested_days > available_leave.available_days:
            leave = self.requested_days - available_leave.available_days
            self.approved_available_days = available_leave.available_days
            available_leave.available_days = 0
            available_leave.carryforward_days = (
                available_leave.carryforward_days - leave
            )
            self.approved_carryforward_days = leave
        else:
            available_leave.available_days = (
                available_leave.available_days - self.requested_days
            )
            self.approved_available_days = self.requested_days
        self.status = "approved"
        available_leave.save()

    def multiple_approvals(self, *args, **kwargs):
        approvals = LeaveRequestConditionApproval.objects.filter(leave_request_id=self)
        requested_query = approvals.filter(is_approved=False).order_by("sequence")
        approved_query = approvals.filter(is_approved=True).order_by("sequence")
        managers = []
        for manager in approvals:
            managers.append(manager.manager_id)
        if approvals.exists():
            result = {
                "managers": managers,
                "approved": approved_query,
                "requested": requested_query,
                "approvals": approvals,
            }
        else:
            result = False
        return result

    def is_approved(self):
        request = getattr(horilla_middlewares._thread_locals, "request", None)
        if request:
            employee = Employee.objects.filter(employee_user_id=request.user).first()
            condition_approval = LeaveRequestConditionApproval.objects.filter(
                leave_request_id=self, manager_id=employee.id
            ).first()
            if condition_approval:
                return not condition_approval.is_approved
            else:
                return True

    def delete(self, *args, **kwargs):
        if self.status == "requested":
            super().delete(*args, **kwargs)

            # Update the leave clashes count for all relevant leave requests
            self.update_leave_clashes_count()
        else:
            request = getattr(horilla_middlewares._thread_locals, "request", None)
            if request:
                clear_messages(request)
                messages.warning(
                    request,
                    _("The {} leave request cannot be deleted !").format(self.status),
                )

    def update_leave_clashes_count(self):
        """
        Update the leave clashes count for all leave requests.
        """
        leave_requests_to_update = LeaveRequest.objects.exclude(
            Q(id=self.id) | Q(status="cancelled") | Q(status="rejected")
        )

        for leave_request in leave_requests_to_update:
            leave_request.leave_clashes_count = leave_request.count_leave_clashes()

        # Bulk update leave clashes count for all leave requests
        LeaveRequest.objects.bulk_update(
            leave_requests_to_update, ["leave_clashes_count"]
        )

    def count_leave_clashes(self):
        """
        Method to count leave clashes where this employee's leave request overlaps
        with other employees' requested dates.
        """
        work_info = EmployeeWorkInformation.objects.filter(employee_id=self.employee_id)
        if work_info.exists() and self.status not in ["cancelled", "rejected"]:
            overlapping_requests = (
                LeaveRequest.objects.exclude(id=self.id)
                .filter(
                    (
                        Q(
                            employee_id__employee_work_info__department_id=self.employee_id.employee_work_info.department_id
                        )
                        | Q(
                            employee_id__employee_work_info__job_position_id=self.employee_id.employee_work_info.job_position_id
                        )
                    )
                    & Q(
                        employee_id__employee_work_info__company_id=self.employee_id.employee_work_info.company_id
                    ),
                    start_date__lte=self.end_date,
                    end_date__gte=self.start_date,
                )
                .exclude(Q(status="cancelled") | Q(status="rejected"))
            )

            return overlapping_requests.count()
        return 0


class LeaverequestFile(models.Model):
    file = models.FileField(upload_to=upload_path)


class LeaverequestComment(HorillaModel):
    """
    LeaverequestComment Model
    """

    request_id = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE)
    employee_id = models.ForeignKey(Employee, on_delete=models.CASCADE)
    files = models.ManyToManyField(LeaverequestFile, blank=True)
    comment = models.TextField(null=True, verbose_name=_("Comment"), max_length=255)

    def __str__(self) -> str:
        return f"{self.comment}"


class LeaveAllocationRequest(HorillaModel):
    leave_type_id = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, verbose_name=_("Leave type")
    )
    employee_id = models.ForeignKey(
        Employee, on_delete=models.CASCADE, verbose_name=_("Employee")
    )
    requested_days = models.FloatField(
        blank=True, null=True, verbose_name=_("Requested days")
    )
    requested_date = models.DateField(default=timezone.now)
    description = models.TextField(max_length=255, verbose_name=_("Description"))
    attachment = models.FileField(
        null=True,
        blank=True,
        upload_to=upload_path,
        verbose_name=_("Attachment"),
    )
    status = models.CharField(
        max_length=30, choices=LEAVE_ALLOCATION_STATUS, default="requested"
    )
    reject_reason = models.TextField(blank=True, max_length=255)
    history = HorillaAuditLog(
        related_name="history_set",
        bases=[
            HorillaAuditInfo,
        ],
    )
    objects = HorillaCompanyManager(
        related_company_field="employee_id__employee_work_info__company_id"
    )

    class Meta:
        ordering = ["-id"]
        verbose_name = _("Leave Allocation Request")
        verbose_name_plural = _("Leave Allocation Requests")

    def __str__(self):
        return f"{self.employee_id}| {self.leave_type_id}| {self.id}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skip_history = False

    def tracking(self):
        return get_diff(self)

    def allocate_tracking(self):
        """
        This method is used to return the tracked history of the instance
        """

        try:
            histories = get_diff(self)[:2]
            for history in histories:
                if history["type"] == "Changes":
                    for update in history["changes"]:
                        if update["field_name"] == "requested_days":
                            return update
        except:
            return None


class LeaveallocationrequestComment(HorillaModel):
    """
    LeaveallocationrequestComment Model
    """

    request_id = models.ForeignKey(LeaveAllocationRequest, on_delete=models.CASCADE)
    employee_id = models.ForeignKey(Employee, on_delete=models.CASCADE)
    files = models.ManyToManyField(LeaverequestFile, blank=True)
    comment = models.TextField(null=True, verbose_name=_("Comment"), max_length=255)

    def __str__(self) -> str:
        return f"{self.comment}"


class CompOffRequest(HorillaModel):
    """Employee request to earn Comp Off Leave days (credited on manager approval)."""

    employee_id = models.ForeignKey(
        Employee, on_delete=models.CASCADE, verbose_name=_("Employee")
    )
    start_date = models.DateField(verbose_name=_("Start Date"))
    end_date = models.DateField(verbose_name=_("End Date"))
    start_date_breakdown = models.CharField(
        max_length=30,
        choices=BREAKDOWN,
        default="full_day",
        verbose_name=_("Breakdown"),
    )
    end_date_breakdown = models.CharField(
        max_length=30,
        choices=BREAKDOWN,
        default="full_day",
        verbose_name=_("End Date Breakdown"),
    )
    requested_days = models.FloatField(
        blank=True, null=True, verbose_name=_("Requested Days")
    )
    approved_days = models.FloatField(
        blank=True, null=True, verbose_name=_("Approved Days")
    )
    description = models.TextField(max_length=255, verbose_name=_("Description"))
    status = models.CharField(
        max_length=30,
        choices=COMP_OFF_REQUEST_STATUS,
        default="requested",
        verbose_name=_("Status"),
    )
    reject_reason = models.TextField(
        blank=True, max_length=255, verbose_name=_("Reject Reason")
    )
    requested_date = models.DateField(
        default=timezone.now, verbose_name=_("Requested Date")
    )
    created_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comp_off_requests_created",
        verbose_name=_("Created By"),
    )
    objects = HorillaCompanyManager(
        related_company_field="employee_id__employee_work_info__company_id"
    )

    class Meta:
        ordering = ["-id"]
        verbose_name = _("Comp-Off Request")
        verbose_name_plural = _("Comp-Off Requests")

    def __str__(self):
        return f"{self.employee_id} | {self.start_date} | {self.id}"

    def reporting_manager(self):
        work_info = getattr(self.employee_id, "employee_work_info", None)
        return getattr(work_info, "reporting_manager_id", None) if work_info else None

    @staticmethod
    def comp_off_leave_type():
        return LeaveType.objects.filter(name__iexact="Comp Off Leave").first()

    def save(self, *args, **kwargs):
        from leave.methods import calculate_requested_days

        self.requested_days = calculate_requested_days(
            self.start_date,
            self.end_date,
            self.start_date_breakdown,
            self.end_date_breakdown,
            # Comp-off is for work on weekends/holidays — count every day in the range.
            exclude_holidays=False,
            employee_id=self.employee_id,
        )
        super().save(*args, **kwargs)

    def clean(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError(_("End date should not be less than start date."))
        if (
            self.start_date
            and self.end_date
            and self.start_date == self.end_date
            and self.start_date_breakdown != self.end_date_breakdown
        ):
            raise ValidationError(
                _("Mismatch in the breakdown of the start and end date.")
            )

    def credit_comp_off_balance(self, days=None):
        days = days if days is not None else self.approved_days
        if not days or days <= 0:
            return
        leave_type = self.comp_off_leave_type()
        if not leave_type:
            return
        available_leave, _ = AvailableLeave.objects.get_or_create(
            employee_id=self.employee_id,
            leave_type_id=leave_type,
        )
        available_leave.available_days += days
        available_leave.save()

    def debit_comp_off_balance(self, days=None):
        days = days if days is not None else self.approved_days
        if not days or days <= 0:
            return
        leave_type = self.comp_off_leave_type()
        if not leave_type:
            return
        available_leave = AvailableLeave.objects.filter(
            employee_id=self.employee_id,
            leave_type_id=leave_type,
        ).first()
        if not available_leave:
            return
        available_leave.available_days = max(0, available_leave.available_days - days)
        available_leave.save()


class LeaveRequestConditionApproval(models.Model):
    sequence = models.IntegerField()
    is_approved = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)
    leave_request_id = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE)
    manager_id = models.ForeignKey(Employee, on_delete=models.CASCADE)


class RestrictLeave(HorillaModel):
    title = models.CharField(max_length=200, verbose_name=_("Title"))
    start_date = models.DateField(verbose_name=_("Start Date"))
    end_date = models.DateField(verbose_name=_("End Date"))
    department = models.ForeignKey(
        Department, verbose_name=_("Department"), on_delete=models.CASCADE
    )
    job_position = models.ManyToManyField(
        JobPosition,
        verbose_name=_("Job Position"),
        blank=True,
        help_text=_(
            "If no job positions are specifically selected, the system will consider all job positions under the selected department."
        ),
    )
    include_all = models.BooleanField(
        default=True,
        help_text=_("Enable to select all Leave types."),
        verbose_name=_("Include All"),
    )
    spesific_leave_types = models.ManyToManyField(
        LeaveType,
        verbose_name=_("Specific Leave Types"),
        related_name="spesific_leave_type",
        blank=True,
        help_text=_("Choose specific leave types to restrict."),
    )
    exclued_leave_types = models.ManyToManyField(
        LeaveType,
        verbose_name=_("Exclude Leave Types"),
        related_name="excluded_leave_type",
        blank=True,
        help_text=_("Choose leave types to exclude from restriction."),
    )

    description = models.TextField(
        null=True, verbose_name=_("Description"), max_length=255
    )
    company_id = models.ForeignKey(
        Company,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name=_("Company"),
    )
    objects = HorillaCompanyManager(related_company_field="company_id")

    def __str__(self) -> str:
        return f"{self.title}"


if apps.is_installed("attendance"):

    class CompensatoryLeaveRequest(HorillaModel):
        leave_type_id = models.ForeignKey(
            LeaveType, on_delete=models.PROTECT, verbose_name="Leave type"
        )
        employee_id = models.ForeignKey(
            Employee, on_delete=models.CASCADE, verbose_name="Employee"
        )
        attendance_id = models.ManyToManyField(
            "attendance.Attendance",
            verbose_name="Attendance",
        )
        requested_days = models.FloatField(blank=True, null=True)
        requested_date = models.DateField(default=timezone.now)
        description = models.TextField(max_length=255)
        status = models.CharField(
            max_length=30, choices=LEAVE_ALLOCATION_STATUS, default="requested"
        )
        reject_reason = models.TextField(blank=True, max_length=255)
        history = HorillaAuditLog(
            related_name="history_set",
            bases=[
                HorillaAuditInfo,
            ],
        )
        objects = HorillaCompanyManager(
            related_company_field="employee_id__employee_work_info__company_id"
        )

        class Meta:
            ordering = ["-id"]

        def __str__(self):
            return f"{self.employee_id}| {self.leave_type_id}| {self.id}"

        def assign_compensatory_leave_type(self):
            available_leave, created = AvailableLeave.objects.get_or_create(
                employee_id=self.employee_id,
                leave_type_id=self.leave_type_id,
            )
            available_leave.available_days += self.requested_days
            available_leave.save()

        def exclude_compensatory_leave(self):
            if AvailableLeave.objects.filter(
                employee_id=self.employee_id,
                leave_type_id=self.leave_type_id,
            ).exists():
                available_leave = AvailableLeave.objects.filter(
                    employee_id=self.employee_id,
                    leave_type_id=self.leave_type_id,
                ).first()
                if available_leave.available_days < self.requested_days:
                    available_leave.available_days = 0
                    available_leave.carryforward_days = max(
                        0,
                        available_leave.carryforward_days
                        - (self.requested_days - available_leave.available_days),
                    )
                else:
                    available_leave.available_days -= self.requested_days
                available_leave.save()

        def save(self, *args, **kwargs):
            self.leave_type_id = LeaveType.objects.filter(
                is_compensatory_leave=True
            ).first()
            super().save(*args, **kwargs)


class LeaveGeneralSetting(HorillaModel):
    """
    LeaveGeneralSettings
    """

    compensatory_leave = models.BooleanField(default=True)
    objects = models.Manager()
    company_id = models.ForeignKey(Company, on_delete=models.CASCADE, null=True)


if apps.is_installed("attendance"):

    class CompensatoryLeaverequestComment(HorillaModel):
        """
        CompensatoryLeaverequestComment Model
        """

        request_id = models.ForeignKey(
            CompensatoryLeaveRequest, on_delete=models.CASCADE
        )
        employee_id = models.ForeignKey(Employee, on_delete=models.CASCADE)
        files = models.ManyToManyField(LeaverequestFile, blank=True)
        comment = models.TextField(null=True, verbose_name=_("Comment"), max_length=255)

        def __str__(self) -> str:
            return f"{self.comment}"


class EmployeePastLeaveRestrict(HorillaModel):
    enabled = models.BooleanField(default=True)


if apps.is_installed("attendance"):

    class OverrideLeaveRequests(LeaveRequest):
        """
        Class to override Attendance model save method
        """

        pass
        pass
