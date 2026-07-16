"""
models.py

This module is used to register models for onboarding app

"""

from datetime import datetime

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from django.conf import settings

from base.horilla_company_manager import HorillaCompanyManager
from employee.models import Employee
from horilla.models import HorillaModel
from horilla_audit.models import HorillaAuditInfo, HorillaAuditLog
from recruitment.models import Candidate, Recruitment


class OnboardingStage(HorillaModel):
    """
    OnboardingStage models
    """

    stage_title = models.CharField(max_length=200, verbose_name=_("Stage Title"))
    recruitment_id = models.ForeignKey(
        Recruitment,
        verbose_name=_("Recruitment"),
        null=True,
        related_name="onboarding_stage",
        on_delete=models.CASCADE,
    )
    employee_id = models.ManyToManyField(Employee, verbose_name=_("Stage Managers"))
    sequence = models.IntegerField(null=True)
    is_final_stage = models.BooleanField(
        default=False, verbose_name=_("Is Final Stage")
    )
    objects = HorillaCompanyManager("recruitment_id__company_id")

    def __str__(self):
        return f"{self.stage_title}"

    class Meta:
        """
        Meta class for additional options
        """

        verbose_name = _("Onboarding Stage")
        verbose_name_plural = _("Onboarding Stages")
        ordering = ["sequence"]


@receiver(post_save, sender=Recruitment)
def create_initial_stage(sender, instance, created, **kwargs):
    """
    This is post save method, used to create initial stage for the recruitment
    """
    if created or not instance.onboarding_stage.first():
        initial_stage = OnboardingStage()
        initial_stage.sequence = 0
        initial_stage.stage_title = "Initial"
        initial_stage.recruitment_id = instance
        initial_stage.save()


class OnboardingTask(HorillaModel):
    """
    OnboardingTask models
    """

    task_title = models.CharField(max_length=200, verbose_name=_("Task Title"))
    # recruitment_id = models.ManyToManyField(Recruitment, related_name="onboarding_task")
    stage_id = models.ForeignKey(
        OnboardingStage,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="onboarding_task",
    )
    candidates = models.ManyToManyField(
        Candidate,
        blank=True,
        related_name="cand_onboarding_task",
        verbose_name=_("Candidates"),
    )
    employee_id = models.ManyToManyField(
        Employee, related_name="onboarding_task", verbose_name=_("Task Managers")
    )

    objects = HorillaCompanyManager("stage_id__recruitment_id__company_id")

    def __str__(self):
        return f"{self.task_title}"

    class Meta:
        """
        Meta class to add some additional options
        """

        verbose_name = _("Onboarding Task")
        verbose_name_plural = _("Onboarding Tasks")


class OnboardingCandidate(Candidate):
    class Meta:
        proxy = True
        verbose_name = _("Onboarding Candidate")
        verbose_name_plural = _("Onboarding Candidates")
        app_label = "onboarding"


class CandidateStage(HorillaModel):
    """
    CandidateStage model
    """

    candidate_id = models.OneToOneField(
        Candidate, on_delete=models.PROTECT, related_name="onboarding_stage"
    )
    onboarding_stage_id = models.ForeignKey(
        OnboardingStage, on_delete=models.PROTECT, related_name="candidate"
    )
    onboarding_end_date = models.DateField(blank=True, null=True)
    sequence = models.IntegerField(null=True, default=0)
    objects = HorillaCompanyManager("candidate_id__recruitment_id__company_id")

    def __str__(self):
        return f"{self.candidate_id}  |  {self.onboarding_stage_id}"

    def save(self, *args, **kwargs):
        if self.onboarding_stage_id.is_final_stage:
            self.onboarding_end_date = datetime.today()
        super(CandidateStage, self).save(*args, **kwargs)

    def task_completion_ratio(self):
        """
        function that used for getting the numbers between task completed v/s tasks assigned
        """
        cans_tasks = self.candidate_id.candidate_task
        completed_tasks = cans_tasks.filter(status="done")
        return f"{completed_tasks.count()}/{cans_tasks.count()}"

    class Meta:
        """
        Meta class for additional options
        """

        verbose_name = _("Candidate Onboarding Stage")
        ordering = ["sequence"]


class CandidateTask(HorillaModel):
    """
    CandidateTask model
    """

    choice = (
        ("todo", _("Todo")),
        ("scheduled", _("Scheduled")),
        ("ongoing", _("Ongoing")),
        ("stuck", _("Stuck")),
        ("done", _("Done")),
    )
    candidate_id = models.ForeignKey(
        Candidate, on_delete=models.PROTECT, related_name="candidate_task"
    )
    # managers = models.ManyToManyField(Employee)
    stage_id = models.ForeignKey(
        OnboardingStage,
        null=True,
        on_delete=models.PROTECT,
        related_name="candidate_task",
    )
    status = models.CharField(
        max_length=50, choices=choice, blank=True, null=True, default="todo"
    )
    onboarding_task_id = models.ForeignKey(OnboardingTask, on_delete=models.PROTECT)
    objects = HorillaCompanyManager("candidate_id__recruitment_id__company_id")
    history = HorillaAuditLog(
        related_name="history_set",
        bases=[
            HorillaAuditInfo,
        ],
    )

    def __str__(self):
        return f"{self.candidate_id}|{self.onboarding_task_id}"

    class Meta:
        """
        Meta class to add some additional options
        """

        verbose_name = _("Onboarding Task")
        verbose_name_plural = _("Onboarding Tasks")


class OnboardingPortal(HorillaModel):
    """
    OnboardingPortal model
    """

    candidate_id = models.OneToOneField(
        Candidate, on_delete=models.PROTECT, related_name="onboarding_portal"
    )
    token = models.CharField(max_length=200)
    used = models.BooleanField(default=False)
    count = models.IntegerField(default=0)
    profile = models.ImageField(upload_to="employee/profile", null=True, blank=True)
    objects = HorillaCompanyManager("candidate_id__recruitment_id__company_id")

    def __str__(self):
        return f"{self.candidate_id} | {self.token}"


class OnboardingProgress(HorillaModel):
    """
    Onboarding checklist for converted employees (17 steps).
    """

    employee_id = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="onboarding_progress",
        verbose_name=_("Employee"),
    )
    step_1 = models.BooleanField(default=False, verbose_name=_("Offer Letter Issued & Accepted"))
    step_2 = models.BooleanField(default=False, verbose_name=_("Joining Date Confirmed"))
    step_3 = models.BooleanField(default=False, verbose_name=_("Personal Details Form Collected"))
    step_4 = models.BooleanField(default=False, verbose_name=_("ID Proof & Address Proof Received"))
    step_5 = models.BooleanField(default=False, verbose_name=_("Education Certificates Received"))
    step_6 = models.BooleanField(default=False, verbose_name=_("Previous Employment Proof / Pay Slips Collected"))
    step_7 = models.BooleanField(default=False, verbose_name=_("PF / ESIC / UAN Details Collected (if applicable)"))
    step_8 = models.BooleanField(default=False, verbose_name=_("NDA & Employment Agreement Signed"))
    step_9 = models.BooleanField(default=False, verbose_name=_("Laptop / Desktop Issued"))
    step_10 = models.BooleanField(default=False, verbose_name=_("Email ID Created"))
    step_11 = models.BooleanField(default=False, verbose_name=_("System Login Credentials Shared"))
    step_12 = models.BooleanField(default=False, verbose_name=_("Access to Tools & Platforms Granted (CRM, Project Tools, Drive, etc.)"))
    step_13 = models.BooleanField(default=False, verbose_name=_("Asset Acknowledgment Form Signed"))
    step_14 = models.BooleanField(default=False, verbose_name=_("Code of Conduct Signed"))
    step_15 = models.BooleanField(default=False, verbose_name=_("Data Protection & Confidentiality Policy Signed"))
    step_16 = models.BooleanField(default=False, verbose_name=_("POSH / Workplace Policy Acknowledged"))
    step_17 = models.BooleanField(default=False, verbose_name=_("IT & Security Policy Acknowledged"))
    is_archived = models.BooleanField(
        default=False,
        verbose_name=_("Archived"),
        help_text=_("Archived onboarding entries are hidden from default view."),
    )

    class Meta:
        verbose_name = _("Onboarding Progress")
        verbose_name_plural = _("Onboarding Progress")

    def __str__(self):
        return str(self.employee_id)


STEP_FIELD_CHOICES = [
    ("step_1", _("Offer Letter Issued & Accepted")),
    ("step_2", _("Joining Date Confirmed")),
    ("step_3", _("Personal Details Form Collected")),
    ("step_4", _("ID Proof & Address Proof Received")),
    ("step_5", _("Education Certificates Received")),
    ("step_6", _("Previous Employment Proof / Pay Slips Collected")),
    ("step_7", _("PF / ESIC / UAN Details Collected (if applicable)")),
    ("step_8", _("NDA & Employment Agreement Signed")),
    ("step_9", _("Laptop / Desktop Issued")),
    ("step_10", _("Email ID Created")),
    ("step_11", _("System Login Credentials Shared")),
    ("step_12", _("Access to Tools & Platforms Granted (CRM, Project Tools, Drive, etc.)")),
    ("step_13", _("Asset Acknowledgment Form Signed")),
    ("step_14", _("Code of Conduct Signed")),
    ("step_15", _("Data Protection & Confidentiality Policy Signed")),
    ("step_16", _("POSH / Workplace Policy Acknowledged")),
    ("step_17", _("IT & Security Policy Acknowledged")),
]


class OnboardingChecklistLog(models.Model):
    """
    Log each check/uncheck of an onboarding checklist step: who, when, and
    reason (required when unchecking). Constraints prevent invalid/duplicate data.
    """

    progress = models.ForeignKey(
        OnboardingProgress,
        on_delete=models.CASCADE,
        related_name="checklist_logs",
        verbose_name=_("Onboarding Progress"),
    )
    step = models.CharField(
        max_length=64,
        choices=STEP_FIELD_CHOICES,
        verbose_name=_("Step"),
        db_index=True,
    )
    is_checked = models.BooleanField(
        default=True,
        verbose_name=_("Checked"),
        help_text=_("True = checked, False = unchecked"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("User"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Date"),
    )
    reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Reason"),
        help_text=_("Required when unchecking a step"),
    )

    class Meta:
        verbose_name = _("Onboarding Checklist Log")
        verbose_name_plural = _("Onboarding Checklist Logs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["progress", "step"], name="onb_log_progress_step_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(step__in=[c[0] for c in STEP_FIELD_CHOICES]),
                name="onb_log_step_valid",
            ),
        ]

    def __str__(self):
        action = _("Checked") if self.is_checked else _("Unchecked")
        return f"{self.progress} – {self.step} {action} by {self.user} at {self.created_at}"
