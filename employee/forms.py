"""
forms.py

This module contains the form classes used in the application.

Each form represents a specific functionality or data input in the
application. They are responsible for validating
and processing user input data.

Classes:
- YourForm: Represents a form for handling specific data input.

Usage:
from django import forms

class YourForm(forms.Form):
    field_name = forms.CharField()

    def clean_field_name(self):
        # Custom validation logic goes here
        pass
"""

import logging
import re
from datetime import date
from typing import Any

from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
from django.forms import DateInput, TextInput
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as trans

from base.methods import eval_validate, reload_queryset
from employee.models import (
    Actiontype,
    BonusPoint,
    DisciplinaryAction,
    Employee,
    EmployeeBankDetails,
    EmployeeGeneralSetting,
    EmployeeNote,
    EmployeeTag,
    EmployeeWorkInformation,
    NoteFiles,
    Policy,
    PolicyMultipleFile,
    Team,
)
from horilla import horilla_middlewares
from horilla_audit.models import AccountBlockUnblock

logger = logging.getLogger(__name__)


class ModelForm(forms.ModelForm):
    """
    Overriding django default model form to apply some styles
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = getattr(horilla_middlewares._thread_locals, "request", None)
        reload_queryset(self.fields)
        for _, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.DateInput):
                field.initial = date.today
                widget.input_type = "date"
                widget.format = "%Y-%m-%d"
                field.input_formats = ["%Y-%m-%d"]

            if isinstance(
                widget,
                (forms.NumberInput, forms.EmailInput, forms.TextInput, forms.FileInput),
            ):
                label = trans(field.label.title())
                field.widget.attrs.update(
                    {"class": "oh-input w-100", "placeholder": label}
                )
            elif isinstance(widget, (forms.Select,)):
                label = ""
                if field.label is not None:
                    label = trans(field.label)
                field.empty_label = trans("---Choose {label}---").format(label=label)
                field.widget.attrs.update(
                    {"class": "oh-select oh-select-2 select2-hidden-accessible"}
                )
            elif isinstance(widget, (forms.Textarea)):
                if field.label is not None:
                    label = trans(field.label)
                field.widget.attrs.update(
                    {
                        "class": "oh-input w-100",
                        "placeholder": label,
                        "rows": 2,
                        "cols": 40,
                    }
                )
            elif isinstance(
                widget,
                (
                    forms.CheckboxInput,
                    forms.CheckboxSelectMultiple,
                ),
            ):
                field.widget.attrs.update({"class": "oh-switch__checkbox"})

            try:
                if self._meta.model.__name__ not in ["DisciplinaryAction"]:
                    self.fields["employee_id"].initial = request.user.employee_get
            except:
                pass

            try:
                self.fields["company_id"].initial = (
                    request.user.employee_get.get_company
                )
            except:
                pass


class UserForm(ModelForm):
    """
    Form for User model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        fields = ("groups",)
        model = User


class UserPermissionForm(ModelForm):
    """
    Form for User model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        fields = ("groups", "user_permissions")
        model = User


class EmployeeForm(ModelForm):
    """
    Form for Employee model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = Employee
        fields = "__all__"
        exclude = (
            "employee_user_id",
            "additional_info",
            "is_from_onboarding",
            "is_directly_converted",
            "is_active",
            "slack_user_id",  # Managed via Slack/Teams sync, not employee form
            "teams_user_id",  # Managed only in Teams Configuration
        )
        widgets = {
            "dob": TextInput(attrs={"type": "date", "id": "dob"}),
        }

    # Emp Id format: GEEKY + exactly 4 digits (e.g. GEEKY0001, GEEKY1234)
    EMP_ID_PREFIX = "GEEKY"
    EMP_ID_PATTERN = re.compile(r"^GEEKY\d{4}$")
    PAN_PATTERN = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["badge_id"].label = _("Emp Id")
        self.fields["badge_id"].help_text = _("Must start with GEEKY followed by exactly 4 digits (e.g. GEEKY0001).")
        self.fields["email"].label = _("Personal Email")
        self.fields["email"].widget.attrs["placeholder"] = _("Personal Email")
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["phone"].widget.attrs["autocomplete"] = "phone"
        self.fields["address"].widget.attrs["autocomplete"] = "address"
        if "pan_number" in self.fields:
            self.fields["pan_number"].widget.attrs["placeholder"] = "ABCDE1234F"
            self.fields["pan_number"].widget.attrs["style"] = "text-transform: uppercase"
        if instance := kwargs.get("instance"):
            # ----
            # django forms not showing value inside the date, time html element.
            # so here overriding default forms instance method to set initial value
            # ----
            initial = {}
            if instance.dob is not None:
                initial["dob"] = instance.dob.strftime("%H:%M")
            kwargs["initial"] = initial
        else:
            self.initial = {"badge_id": self.get_next_badge_id()}

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/create_form/personal_info_as_p.html", context)

    def clean(self):
        super().clean()
        email = self.cleaned_data["email"]
        query = Employee.objects.entire().filter(email=email)
        if self.instance and self.instance.id:
            query = query.exclude(id=self.instance.id)

        existing_employee = query.first()

        if existing_employee:
            company_id = None
            if (
                hasattr(existing_employee, "employee_work_info")
                and existing_employee.employee_work_info
            ):
                company_id = existing_employee.employee_work_info.company_id

            if company_id:
                error_message = _(
                    "An Employee with this Email already exists in company {}".format(
                        company_id
                    )
                )
            else:
                error_message = _("An Employee with this Email already exists")

            raise forms.ValidationError({"email": error_message})

    def get_next_badge_id(self):
        """
        Generate next Emp Id: GEEKY + 4 digits (e.g. GEEKY0001, GEEKY0002).
        """
        from employee.methods.methods import get_next_emp_id

        return get_next_emp_id()

    def clean_badge_id(self):
        """
        Validate Emp Id: must start with GEEKY followed by exactly 4 digits (e.g. GEEKY0001).
        """
        badge_id = (self.cleaned_data.get("badge_id") or "").strip()
        if not badge_id:
            return badge_id or None
        if not self.EMP_ID_PATTERN.match(badge_id):
            raise forms.ValidationError(
                _("Emp Id must start with GEEKY followed by exactly 4 digits (e.g. GEEKY0001).")
            )
        all_employees = Employee.objects.entire()
        queryset = all_employees.filter(badge_id=badge_id).exclude(
            pk=self.instance.pk if self.instance else None
        )
        if queryset.exists():
            raise forms.ValidationError(_("Emp Id must be unique."))
        return badge_id

    def clean_pan_number(self):
        pan = (self.cleaned_data.get("pan_number") or "").strip().upper()
        if not pan:
            return None
        if not self.PAN_PATTERN.match(pan):
            raise forms.ValidationError(
                _("Enter a valid PAN (5 letters, 4 digits, 1 letter, e.g. ABCDE1234F).")
            )
        queryset = Employee.objects.entire().filter(pan_number__iexact=pan)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError(_("This PAN is already used by another employee."))
        return pan


class EmployeeWorkInformationForm(ModelForm):
    """
    Form for EmployeeWorkInformation model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = EmployeeWorkInformation
        fields = "__all__"
        exclude = ("employee_id", "additional_info", "experience")
        widgets = {
            "team_ids": forms.SelectMultiple(
                attrs={"class": "oh-select oh-select-2 select2-hidden-accessible"}
            ),
        }

    def __init__(self, *args, disable=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        if "basic_salary" in self.fields:
            self.fields["basic_salary"].widget.attrs.update(
                {"step": "0.01", "inputmode": "decimal"}
            )

        self.fields["job_position_id"].widget.attrs.update(
            {
                "onchange": "jobChange($(this))",
            }
        )
        
        # Filter teams based on selected department
        if 'department_id' in self.data and self.data['department_id']:
            department_id = self.data['department_id']
            self.fields['team_ids'].queryset = Team.objects.filter(department_id=department_id, is_active=True)
        elif hasattr(self, 'instance') and self.instance and hasattr(self.instance, 'department_id') and self.instance.department_id:
            self.fields['team_ids'].queryset = Team.objects.filter(department_id=self.instance.department_id, is_active=True)
        else:
            self.fields['team_ids'].queryset = Team.objects.none()

        for field in self.fields:
            self.fields[field].widget.attrs["placeholder"] = self.fields[field].label
            if disable:
                self.fields[field].disabled = True
        field_names = {
            "Department": "department",
            "Job Position": "job_position",
            "Job Role": "job_role",
            "Work Type": "work_type",
            "Employee Type": "employee_type",
            "Shift": "employee_shift",
        }
        urls = {
            "Department": "#dynamicDept",
            "Job Position": "#dynamicJobPosition",
            "Job Role": "#dynamicJobRole",
            "Work Type": "#dynamicWorkType",
            "Employee Type": "#dynamicEmployeeType",
            "Shift": "#dynamicShift",
        }

        for label, field in self.fields.items():
            if isinstance(field, forms.ModelChoiceField) and field.label in field_names:
                if field.label is not None:
                    field_name = field_names.get(field.label)
                    if field.queryset.model != Employee and field_name:
                        translated_label = _(field.label)
                        empty_label = _("---Choose {label}---").format(
                            label=translated_label
                        )
                        self.fields[label] = forms.ChoiceField(
                            choices=[("", empty_label)]
                            + list(field.queryset.values_list("id", f"{field_name}")),
                            required=field.required,
                            label=translated_label,
                            initial=field.initial,
                            widget=forms.Select(
                                attrs={
                                    "class": "oh-select oh-select-2 select2-hidden-accessible",
                                    "onchange": f'onDynamicCreate(this.value,"{urls.get(field.label)}");',
                                }
                            ),
                        )
                        self.fields[label].choices += [
                            ("create", _("Create New {} ").format(translated_label))
                        ]

    def clean(self):
        cleaned_data = super().clean()
        if "employee_id" in self.errors:
            del self.errors["employee_id"]
        return cleaned_data

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/create_form/personal_info_as_p.html", context)


class EmployeeWorkInformationUpdateForm(ModelForm):
    """
    Form for EmployeeWorkInformation model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = EmployeeWorkInformation
        fields = "__all__"
        exclude = ("employee_id",)
        widgets = {
            "team_ids": forms.SelectMultiple(
                attrs={"class": "oh-select oh-select-2 select2-hidden-accessible"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "basic_salary" in self.fields:
            self.fields["basic_salary"].widget.attrs.update(
                {"step": "0.01", "inputmode": "decimal"}
            )

        # Filter teams based on selected department
        if 'department_id' in self.data and self.data['department_id']:
            department_id = self.data['department_id']
            self.fields['team_ids'].queryset = Team.objects.filter(department_id=department_id, is_active=True)
        elif hasattr(self, 'instance') and self.instance and hasattr(self.instance, 'department_id') and self.instance.department_id:
            self.fields['team_ids'].queryset = Team.objects.filter(department_id=self.instance.department_id, is_active=True)
        else:
            self.fields['team_ids'].queryset = Team.objects.none()

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/create_form/personal_info_as_p.html", context)


class EmployeeBankDetailsForm(ModelForm):
    """
    Form for EmployeeBankDetails model
    """

    address = forms.CharField(widget=forms.Textarea(attrs={"rows": 2, "cols": 40}))

    class Meta:
        """
        Meta class to add the additional info
        """

        model = EmployeeBankDetails
        fields = (
            "bank_name",
            "account_number",
            "branch",
            "any_other_code1",
            "address",
            "country",
            "state",
            "city",
            "any_other_code2",
        )
        exclude = ["employee_id", "is_active", "additional_info"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].widget.attrs["autocomplete"] = "address"
        if "any_other_code1" in self.fields:
            self.fields["any_other_code1"].label = _("IFSC Code")
            self.fields["any_other_code1"].widget.attrs["placeholder"] = _("IFSC Code")
        if "any_other_code2" in self.fields:
            self.fields["any_other_code2"].label = _("Pincode")
            self.fields["any_other_code2"].widget.attrs["placeholder"] = _("Pincode")
        for visible in self.visible_fields():
            visible.field.widget.attrs["class"] = "oh-input w-100"

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/update_form/bank_info_as_p.html", context)


class EmployeeBankDetailsUpdateForm(ModelForm):
    """
    Form for EmployeeBankDetails model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = EmployeeBankDetails
        fields = "__all__"
        exclude = ["employee_id", "is_active", "additional_info"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "any_other_code1" in self.fields:
            self.fields["any_other_code1"].label = _("IFSC Code")
            self.fields["any_other_code1"].widget.attrs["placeholder"] = _("IFSC Code")
        if "any_other_code2" in self.fields:
            self.fields["any_other_code2"].label = _("Pincode")
            self.fields["any_other_code2"].widget.attrs["placeholder"] = _("Pincode")
        for visible in self.visible_fields():
            visible.field.widget.attrs["class"] = "oh-input w-100"
        for field in self.fields:
            self.fields[field].widget.attrs["placeholder"] = self.fields[field].label

    def as_p(self, *args, **kwargs):
        context = {"form": self}
        return render_to_string("employee/update_form/bank_info_as_p.html", context)


excel_columns = [
    ("badge_id", trans("Emp Id")),
    ("employee_first_name", trans("First Name")),
    ("employee_last_name", trans("Last Name")),
    ("email", trans("Email")),
    ("phone", trans("Phone")),
    ("experience", trans("Experience")),
    ("gender", trans("Gender")),
    ("dob", trans("Date of Birth")),
    ("country", trans("Country")),
    ("state", trans("State")),
    ("city", trans("City")),
    ("address", trans("Address")),
    ("zip", trans("Zip Code")),
    ("marital_status", trans("Marital Status")),
    ("children", trans("Children")),
    ("is_active", trans("Is active")),
    ("emergency_contact", trans("Emergency contact number")),
    ("emergency_contact_name", trans("Emergency Contact Name")),
    ("emergency_contact_relation", trans("Emergency Contact Relation")),
    ("blood_group", trans("Blood group")),
    ("pan_number", trans("PAN Card Number")),
    ("employee_work_info__email", trans("Work Email")),
    ("employee_work_info__mobile", trans("Work Phone")),
    ("employee_work_info__department_id", trans("Department")),
    ("employee_work_info__job_position_id", trans("Job Position")),
    ("employee_work_info__job_role_id", trans("Job Role")),
    ("employee_work_info__shift_id", trans("Shift")),
    ("employee_work_info__work_type_id", trans("Work Type")),
    ("employee_work_info__reporting_manager_id", trans("Reporting Manager")),
    ("employee_work_info__operation_manager_id", trans("Operation Manager")),
    ("employee_work_info__business_manager_id", trans("Business Manager")),
    ("employee_work_info__employee_type_id", trans("Employee Type")),
    ("employee_work_info__location", trans("Location")),
    ("employee_work_info__date_joining", trans("Date Joining")),
    ("employee_work_info__basic_salary", trans("Basic Salary")),
    ("employee_work_info__salary_hour", trans("Salary Hour")),
    ("employee_work_info__contract_end_date", trans("Contract End Date")),
    ("employee_work_info__company_id", trans("Company")),
    ("employee_bank_details__bank_name", trans("Bank Name")),
    ("employee_bank_details__branch", trans("Branch")),
    ("employee_bank_details__account_number", trans("Account Number")),
    ("employee_bank_details__any_other_code1", trans("Bank Code #1")),
    ("employee_bank_details__any_other_code2", trans("Bank Code #2")),
    ("employee_bank_details__country", trans("Bank Country")),
    ("employee_bank_details__state", trans("Bank State")),
    ("employee_bank_details__city", trans("Bank City")),
]
fields_to_remove = [
    "badge_id",
    "employee_first_name",
    "employee_last_name",
    "is_active",
    "email",
    "phone",
    "employee_bank_details__account_number",
]


class EmployeeExportExcelForm(forms.Form):
    selected_fields = forms.MultipleChoiceField(
        choices=excel_columns,
        widget=forms.CheckboxSelectMultiple,
        initial=[
            "badge_id",
            "employee_first_name",
            "employee_last_name",
            "email",
            "phone",
            "gender",
            "employee_work_info__department_id",
            "employee_work_info__job_position_id",
            "employee_work_info__job_role_id",
            "employee_work_info__shift_id",
            "employee_work_info__work_type_id",
            "employee_work_info__reporting_manager_id",
            "employee_work_info__operation_manager_id",
            "employee_work_info__business_manager_id",
            "employee_work_info__employee_type_id",
            "employee_work_info__location",
            "employee_work_info__date_joining",
            "employee_work_info__basic_salary",
            "employee_work_info__salary_hour",
            "employee_work_info__contract_end_date",
            "employee_work_info__company_id",
        ],
    )


class BulkUpdateFieldForm(forms.Form):
    update_fields = forms.MultipleChoiceField(
        choices=excel_columns, label=_("Select Fields to Update")
    )
    bulk_employee_ids = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        updated_choices = [
            (value, label)
            for value, label in self.fields["update_fields"].choices
            if value not in fields_to_remove
        ]
        self.fields["update_fields"].choices = updated_choices
        for visible in self.visible_fields():
            visible.field.widget.attrs["class"] = (
                "oh-select oh-select-2 select2-hidden-accessible oh-input w-100"
            )


class EmployeeNoteForm(ModelForm):
    """
    Form for EmployeeNote model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = EmployeeNote
        fields = ("description",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["note_files"] = MultipleFileField(label="files")
        self.fields["note_files"].required = False

    def save(self, commit: bool = ...) -> Any:
        attachement = []
        multiple_attachment_ids = []
        attachements = None
        if self.files.getlist("note_files"):
            attachements = self.files.getlist("note_files")
            self.instance.attachement = attachements[0]
            multiple_attachment_ids = []

            for attachement in attachements:
                file_instance = NoteFiles()
                file_instance.files = attachement
                file_instance.save()
                multiple_attachment_ids.append(file_instance.pk)
        instance = super().save(commit)
        if commit:
            instance.note_files.add(*multiple_attachment_ids)
        return instance, multiple_attachment_ids


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = [single_file_clean(data, initial)]
        if len(result) == 0:
            result = [[]]
        return result[0]


class PolicyForm(ModelForm):
    """
    PolicyForm
    """

    class Meta:
        model = Policy
        fields = "__all__"
        exclude = ["attachments", "is_active"]
        widgets = {
            # Same Summernote setup as Create Recruitment description
            "body": forms.Textarea(attrs={"data-summernote": ""}),
        }

    def as_p(self, *args, **kwargs):
        """
        Render with horilla_form layout (divs) so Summernote is not trapped in <p> tags.
        """
        context = {"form": self}
        return render_to_string("horilla_form.html", context)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attachment"] = MultipleFileField(
            label="Attachements", required=False
        )
        # Keep body using the recruitment-style editor attrs after ModelForm styling
        body = self.fields.get("body")
        if body is not None:
            body.widget.attrs.update({"data-summernote": ""})
            body.widget.attrs.pop("style", None)

    def save(self, *args, commit=True, **kwargs):
        attachemnt = []
        multiple_attachment_ids = []
        attachemnts = None
        if self.files.getlist("attachment"):
            attachemnts = self.files.getlist("attachment")
            multiple_attachment_ids = []
            for attachemnt in attachemnts:
                file_instance = PolicyMultipleFile()
                file_instance.attachment = attachemnt
                file_instance.save()
                multiple_attachment_ids.append(file_instance.pk)
        instance = super().save(commit)
        if commit:
            instance.attachments.add(*multiple_attachment_ids)
        return instance, attachemnts


class BonusPointAddForm(ModelForm):
    class Meta:
        model = BonusPoint
        fields = ["points", "reason"]
        widgets = {
            "reason": forms.TextInput(attrs={"required": "required"}),
        }


class BonusPointRedeemForm(ModelForm):
    class Meta:
        model = BonusPoint
        fields = ["points"]

    def clean(self):
        cleaned_data = super().clean()
        available_points = BonusPoint.objects.filter(
            employee_id=self.instance.employee_id
        ).first()
        if not available_points or available_points.points < cleaned_data["points"]:
            raise forms.ValidationError({"points": "Not enough bonus points to redeem"})
        if cleaned_data["points"] <= 0:
            raise forms.ValidationError(
                {"points": "Points must be greater than zero to redeem."}
            )


class DisciplinaryActionForm(ModelForm):
    class Meta:
        model = DisciplinaryAction
        fields = "__all__"
        exclude = ["objects", "is_active"]

    action = forms.ModelChoiceField(
        queryset=Actiontype.objects.all(),
        label=_("Action"),
        widget=forms.Select(
            attrs={
                "class": "oh-select oh-select-2 select2-hidden-accessible",
                "onchange": "actionTypeChange($(this))",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        action_choices = [("", _("---Choose Action---"))] + list(
            self.fields["action"].queryset.values_list("id", "title")
        )
        self.fields["action"].choices = action_choices
        if self.instance.pk is None:
            self.fields["action"].choices += [("create", _("Create new action type "))]

    def as_p(self):
        """
        Render the form fields as HTML table rows with Bootstrap styling.
        """
        context = {"form": self}
        table_html = render_to_string("common_form.html", context)
        return table_html


class ActiontypeForm(ModelForm):
    class Meta:
        model = Actiontype
        fields = "__all__"
        exclude = ["is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["action_type"].widget.attrs.update(
            {
                "onchange": "actionChange($(this))",
            }
        )


class EmployeeTagForm(ModelForm):
    """
    Employee Tags form
    """

    class Meta:
        """
        Meta class for additional options
        """

        model = EmployeeTag
        fields = "__all__"
        exclude = ["is_active"]
        widgets = {"color": TextInput(attrs={"type": "color", "style": "height:50px"})}


class TeamForm(ModelForm):
    """
    Form for Team model
    """

    class Meta:
        """
        Meta class to add the additional info
        """

        model = Team
        fields = ["team_name", "department_id"]
        exclude = ["created_by", "modified_by", "team_lead", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = getattr(horilla_middlewares._thread_locals, "request", None)
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            self.instance.created_by = request.user


class EmployeeGeneralSettingPrefixForm(forms.ModelForm):

    class Meta:

        model = EmployeeGeneralSetting
        exclude = ["objects"]
        widgets = {
            "badge_id_prefix": forms.TextInput(attrs={"class": "oh-input w-100"}),
            "company_id": forms.Select(attrs={"class": "oh-select oh-select-2 w-100"}),
        }
