"""
admin.py

This page is used to register the model with admins site.
"""

from django.contrib import admin

from recruitment.models import (
    Candidate,
    CandidateRating,
    ClosersFellowshipApplication,
    InterviewSchedule,
    LinkedInAccount,
    Recruitment,
    RecruitmentSurvey,
    RecruitmentSurveyAnswer,
    RejectedCandidate,
    SkillZone,
    Stage,
)

# Register your models here.


admin.site.register(Stage)
admin.site.register(Recruitment)
admin.site.register(Candidate)
admin.site.register(RejectedCandidate)
admin.site.register(RecruitmentSurveyAnswer)
admin.site.register(RecruitmentSurvey)
admin.site.register(CandidateRating)
admin.site.register(SkillZone)
admin.site.register(InterviewSchedule)
admin.site.register(LinkedInAccount)


@admin.register(ClosersFellowshipApplication)
class ClosersFellowshipApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "email",
        "phone",
        "seat",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "created_at",
    )
    search_fields = ("full_name", "email", "phone", "seat")
    readonly_fields = ("created_at", "created_by", "modified_by")
    list_filter = ("seat", "utm_source", "utm_medium")
