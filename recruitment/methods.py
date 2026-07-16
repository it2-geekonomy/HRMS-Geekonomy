"""
methods.py

This page is used to write reusable methods.

"""

from django.apps import apps
from django.utils.translation import gettext_lazy as _

from recruitment.models import Candidate, Recruitment, RecruitmentSurvey


def purge_candidate_protected_relations(candidate: Candidate) -> None:
    """
    Remove rows that reference Candidate with on_delete=PROTECT so the candidate
    can be permanently deleted (single or bulk). Does not delete the Candidate row.
    """
    from recruitment.models import (
        CandidateDocument,
        CandidateDocumentRequest,
        CandidateRating,
        RejectedCandidate,
        SkillZoneCandidate,
    )

    pk = candidate.pk
    CandidateDocument.objects.filter(candidate_id=pk).delete()
    CandidateRating.objects.filter(candidate_id=pk).delete()
    SkillZoneCandidate.objects.filter(candidate_id=pk).delete()
    RejectedCandidate.objects.filter(candidate_id=pk).delete()

    if apps.is_installed("onboarding"):
        from onboarding.models import (
            CandidateStage,
            CandidateTask,
            OnboardingPortal,
            OnboardingTask,
        )

        for task in OnboardingTask.objects.filter(candidates__pk=pk):
            task.candidates.remove(candidate)

        CandidateTask.objects.filter(candidate_id=pk).delete()
        OnboardingPortal.objects.filter(candidate_id=pk).delete()
        CandidateStage.objects.filter(candidate_id=pk).delete()

    for doc_req in CandidateDocumentRequest.objects.filter(candidate_id=pk):
        doc_req.candidate_id.remove(candidate)


def is_stagemanager(request):
    """
    This method is used to check stage manager, if the employee is also
    recruitment manager it returns true
    """
    try:
        employee = request.user.employee_get
        return employee.recruitment_set.exists() or employee.stage_set.exists()
    except Exception:
        return False


def is_recruitmentmanager(request):
    """
    This method is used to check the employee is recruitment manager or not
    """
    try:
        employee = request.user.employee_get
        return employee.recruitment_set.exists()
    except Exception:
        return False


def stage_manages(request, stage):
    """
    This method is used to check the employee manager to this stage."""
    try:
        employee = request.user.employee_get

        return (
            stage.stage_manager.filter(id=employee.id).exists()
            or stage.recruitment_id.recruitment_managers.filter(id=employee.id).exists()
        )
    except Exception:
        return False


def recruitment_manages(request, recruitment):
    """
    This method is used to check the employee is manager to the current recruitment
    """
    try:
        employee = request.user.employee_get
        return recruitment.recruitment_managers.filter(id=employee.id).exists()
    except Exception:
        return False


def get_recruitment_application_block_reason(recruitment):
    """Return a user-facing message when applications are not accepted, else None."""
    if recruitment is None:
        return _("Recruitment not found.")
    if not recruitment.is_active:
        return _("This recruitment is no longer available.")
    if recruitment.closed:
        return _("This position is closed and no longer accepting applications.")
    if not recruitment.is_published:
        return _("This recruitment is not open for applications at this time.")
    return None


def recruitment_accepts_applications(recruitment):
    return get_recruitment_application_block_reason(recruitment) is None


def get_recruitment_survey_questions(recruitment):
    """Survey questions shown to applicants for a recruitment."""
    if recruitment is None:
        return RecruitmentSurvey.objects.none()
    templates = recruitment.survey_templates.all()
    if templates.exists():
        return (
            RecruitmentSurvey.objects.filter(template_id__in=templates)
            .order_by("sequence")
            .distinct()
        )
    return (
        RecruitmentSurvey.objects.filter(recruitment_ids=recruitment)
        .order_by("sequence")
        .distinct()
    )


def recruitment_has_survey(recruitment):
    """True when the recruitment has active survey questions for applicants."""
    return get_recruitment_survey_questions(recruitment).exists()


def sync_recruitment_survey_links(recruitment):
    """
    Keep RecruitmentSurvey.recruitment_ids in sync with recruitment.survey_templates.
    Clears stale links when templates are removed or changed on update.
    """
    for survey in RecruitmentSurvey.objects.filter(recruitment_ids=recruitment):
        survey.recruitment_ids.remove(recruitment)
    for template in recruitment.survey_templates.all():
        for survey in template.recruitmentsurvey_set.all():
            survey.recruitment_ids.add(recruitment)


def update_rec_template_grp(upt_template_ids, template_groups, rec_id):
    recruitment_obj = Recruitment.objects.get(id=rec_id)
    sync_recruitment_survey_links(recruitment_obj)
