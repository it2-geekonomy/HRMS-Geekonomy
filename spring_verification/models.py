"""
spring_verification/models.py
BGV access permission model and stored BGV candidate data for employee profile.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class BGVCandidate(models.Model):
    """
    Stores BGV (Background Verification) candidate data from Spring Verify API,
    linked to an employee so it can be shown on the employee profile.
    """
    employee = models.ForeignKey(
        "employee.Employee",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bgv_candidates",
        verbose_name=_("Employee"),
    )
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=50, blank=True)
    overall_status = models.CharField(max_length=100, blank=True)
    candidate_id = models.IntegerField(unique=True)
    candidate_uuid = models.CharField(max_length=64, blank=True)
    initiation_date = models.DateTimeField(null=True, blank=True)
    completion_date = models.DateTimeField(null=True, blank=True)
    report_url = models.URLField(max_length=500, blank=True)
    meta_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("BGV Candidate")
        verbose_name_plural = _("BGV Candidates")
        ordering = ["-initiation_date"]

    def __str__(self):
        return f"{self.name} ({self.candidate_id})"


class SpringVerificationAccess(models.Model):
    """
    Placeholder model so we can use Django's view permission
    for sidebar and page access. Assign "Can view spring verification access"
    to users/groups to let them see BGV menu and pages.
    """
    name = models.CharField(max_length=1, default="", blank=True)

    class Meta:
        verbose_name = _("BGV Access")
        verbose_name_plural = _("BGV Access")

    def __str__(self):
        return "BGV"
