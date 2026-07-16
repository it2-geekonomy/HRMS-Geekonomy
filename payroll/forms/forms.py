"""
forms.py
"""

from typing import Any

from django import forms
from django.forms import widgets
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from base.forms import Form, ModelForm
from employee.forms import MultipleFileField
from employee.models import Employee, EmployeeWorkInformation
from payroll.context_processors import get_active_employees
from payroll.models.models import (
    Contract,
    EncashmentGeneralSettings,
    FilingStatus,
    PayrollGeneralSetting,
    ReimbursementFile,
    ReimbursementrequestComment,
)


class ContractForm(ModelForm):
    """
    ContactForm
    """

    verbose_name = _("Contract")
    contract_start_date = forms.DateField()
    contract_end_date = forms.DateField(required=False)

    class Meta:
        """
        Meta class for additional options
        """

        fields = "__all__"
        exclude = [
            "is_active",
        ]
        model = Contract

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee_id"].widget.attrs.update(
            {"onchange": "contractInitial(this)"}
        )
        self.fields["contract_status"].widget.attrs.update(
            {
                "class": "oh-select",
            }
        )
        if self.instance and self.instance.pk:
            dynamic_url = self.get_dynamic_hx_post_url(self.instance)
            self.fields["contract_status"].widget.attrs.update(
                {
                    "hx-target": "this",
                    "hx-post": dynamic_url,
                    "hx-swap": "beforebegin",
                }
            )
        first = PayrollGeneralSetting.objects.first()
        if first and self.instance.pk is None:
            self.initial["notice_period_in_days"] = first.notice_period
        self.fields["contract_document"].widget.attrs[
            "accept"
        ] = ".jpg, .jpeg, .png, .pdf"
        # When editing, pre-fill Department/Job Position/Job Role/Work Type from employee work_info if contract has None
        # Filing Status is optional. Use a sentinel value "__none__" for "None" so it is always submitted
        # (empty string can be omitted by some browsers/Select2). clean_filing_status converts "__none__" to None.
        if "filing_status" in self.fields:
            FILING_NONE_VALUE = "__none__"
            choices = [(FILING_NONE_VALUE, _("None"))]
            choices.extend(
                (str(obj.pk), str(obj)) for obj in FilingStatus.objects.all()
            )
            self.fields["filing_status"] = forms.ChoiceField(
                choices=choices,
                required=False,
                label=self.fields["filing_status"].label,
            )
            if self.instance and self.instance.pk:
                if self.instance.filing_status_id is not None:
                    self.initial["filing_status"] = str(self.instance.filing_status_id)
                else:
                    self.initial["filing_status"] = FILING_NONE_VALUE
        if self.instance and self.instance.pk and self.instance.employee_id:
            try:
                work_info = self.instance.employee_id.employee_work_info
            except Exception:
                work_info = None
            if work_info:
                if not self.instance.department_id and work_info.department_id_id:
                    self.initial["department"] = work_info.department_id_id
                if not self.instance.job_position_id and work_info.job_position_id_id:
                    self.initial["job_position"] = work_info.job_position_id_id
                if not self.instance.job_role_id and work_info.job_role_id_id:
                    self.initial["job_role"] = work_info.job_role_id_id
                if not self.instance.work_type_id and work_info.work_type_id_id:
                    self.initial["work_type"] = work_info.work_type_id_id
                if not self.instance.shift_id and work_info.shift_id_id:
                    self.initial["shift"] = work_info.shift_id_id

    def as_p(self):
        """
        Render the form fields as HTML table rows with Bootstrap styling.
        """
        context = {"form": self}
        table_html = render_to_string("contract_form.html", context)
        return table_html

    def clean_filing_status(self):
        """Convert choice (pk, empty string, or __none__) to FilingStatus instance or None for saving."""
        value = self.cleaned_data.get("filing_status")
        if value is None or value == "" or value == "__none__":
            return None
        try:
            return FilingStatus.objects.get(pk=int(value))
        except (FilingStatus.DoesNotExist, ValueError, TypeError):
            return None

    def get_dynamic_hx_post_url(self, instance):
        """
        Render the url for contract status update through hx request
        """
        return f"/payroll/update-contract-status/{instance.pk}"


class ReimbursementRequestCommentForm(ModelForm):
    """
    ReimbursementRequestCommentForm form
    """

    class Meta:
        """
        Meta class for additional options
        """

        model = ReimbursementrequestComment
        fields = ("comment",)


class reimbursementCommentForm(ModelForm):
    """
    Reimbursement request comment model form
    """

    verbose_name = "Add Comment"

    class Meta:
        """
        Meta class for additional options
        """

        model = ReimbursementrequestComment
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["files"] = MultipleFileField(label="files")
        self.fields["files"].required = False
        self.fields["files"].widget.attrs["accept"] = ".jpg, .jpeg, .png, .pdf"

    def as_p(self):
        """
        Render the form fields as HTML table rows with Bootstrap styling.
        """
        context = {"form": self}
        table_html = render_to_string("common_form.html", context)
        return table_html

    def save(self, commit: bool = ...) -> Any:
        multiple_files_ids = []
        files = None
        if self.files.getlist("files"):
            files = self.files.getlist("files")
            self.instance.attachemnt = files[0]
            multiple_files_ids = []
            for attachemnt in files:
                file_instance = ReimbursementFile()
                file_instance.file = attachemnt
                file_instance.save()
                multiple_files_ids.append(file_instance.pk)
        instance = super().save(commit)
        if commit:
            instance.files.add(*multiple_files_ids)
        return instance, files


class EncashmentGeneralSettingsForm(ModelForm):
    class Meta:
        model = EncashmentGeneralSettings
        fields = "__all__"


class DashboardExport(Form):
    status_choices = [
        ("", ""),
        ("draft", "Draft"),
        ("review_ongoing", "Review Ongoing"),
        ("confirmed", "Confirmed"),
        ("paid", "Paid"),
    ]
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "oh-input w-100"}),
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "oh-input w-100"}),
    )
    employees = forms.ChoiceField(
        required=False,
        choices=[(emp.id, emp.get_full_name()) for emp in Employee.objects.all()],
        widget=forms.SelectMultiple,
    )
    status = forms.ChoiceField(required=False, choices=status_choices)
    contributions = forms.ChoiceField(
        required=False,
        choices=[
            (emp.id, emp.get_full_name())
            for emp in get_active_employees(None)["get_active_employees"]
        ],
        widget=forms.SelectMultiple,
    )
