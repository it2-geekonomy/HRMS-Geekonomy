"""
surveys.py

This module is used to write views related to the survey features
"""

import json
import os
from datetime import datetime
from uuid import uuid4

from django.contrib import messages
from django.core import serializers
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail import EmailMessage
from django.db.models import ProtectedError
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from notifications.signals import notify
import logging

logger = logging.getLogger(__name__)

from base.methods import closest_numbers, get_pagination
from horilla.decorators import (
    hx_request_required,
    is_recruitment_manager,
    login_required,
    permission_required,
)
from recruitment.filters import SurveyFilter
from recruitment.forms import (
    AddQuestionForm,
    ApplicationForm,
    QuestionForm,
    SurveyForm,
    SurveyPreviewForm,
    TemplateForm,
)
from recruitment.models import (
    Candidate,
    JobPosition,
    Recruitment,
    RecruitmentSurvey,
    RecruitmentSurveyAnswer,
    Resume,
    Stage,
    SurveyTemplate,
)
from recruitment.pipeline_grouper import group_by_queryset
from recruitment.methods import (
    get_recruitment_application_block_reason,
    get_recruitment_survey_questions,
    recruitment_has_survey,
    sync_recruitment_survey_links,
)
from recruitment.views.paginator_qry import paginator_qry


@login_required
@is_recruitment_manager(perm="recruitment.add_recruitmentsurvey")
def survey_form(request):
    """
    This method is used to render survey wform
    """
    recruitment_id = request.GET["recId"]
    recruitment = Recruitment.objects.get(id=recruitment_id)
    form = SurveyForm(recruitment=recruitment).form
    return render(request, "survey/form.html", {"form": form})


@login_required
@is_recruitment_manager(perm="recruitment.add_recruitmentsurvey")
def survey_preview(request, pk=None):
    """
    Used to render survey form to the candidate
    """
    template = None
    if pk:
        template = SurveyTemplate.objects.filter(pk=pk).first()
    if not template:
        title = (request.GET.get("title") or "").strip()
        if title:
            template = SurveyTemplate.objects.filter(title=title).first()
    if not template:
        messages.error(request, _("Survey template not found."))
        return redirect(reverse("recruitment-survey-question-template-view"))

    form = SurveyPreviewForm(template=template).form
    return render(
        request,
        "survey/survey_preview.html",
        {"form": form, "template": template},
    )


from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
@login_required
def question_order_update(request):
    if request.method == "POST":
        # Extract data from the request
        question_id = request.POST.get("question_id")
        new_position = int(request.POST.get("new_position"))
        qs = RecruitmentSurvey.objects.get(id=question_id)

        if qs.sequence > new_position:
            new_position = new_position
        if qs.sequence <= new_position:
            new_position = new_position - 1

        old_qs = RecruitmentSurvey.objects.filter(sequence=new_position)
        for i in old_qs:

            i.sequence = new_position + 1
            i.save()
        qs.sequence = int(new_position)
        qs.save()
        return JsonResponse(
            {"success": True, "message": "Question order updated successfully"}
        )

    return JsonResponse({"error": "Invalid request method"}, status=405)


def _recruitment_survey_questions(recruitment):
    return get_recruitment_survey_questions(recruitment)


def _format_survey_other_answer(selected, question_id, other_texts):
    other_val = (other_texts.get(str(question_id)) or "").strip()
    other_answer = f"Other: {other_val}" if other_val else "Other"
    if isinstance(selected, list):
        if "__other__" not in selected:
            return selected
        cleaned = [choice for choice in selected if choice != "__other__"]
        cleaned.append(other_answer)
        return cleaned
    if selected == "__other__":
        return other_answer
    return selected


def candidate_survey(request):
    """
    Used to render survey form to the candidate
    """
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB in bytes
    candidate_json = request.session["candidate"]
    candidate_dict = json.loads(candidate_json)
    rec_id = candidate_dict[0]["fields"]["recruitment_id"]
    job_id = candidate_dict[0]["fields"]["job_position_id"]
    job = JobPosition.objects.get(id=job_id)
    recruitment = Recruitment.objects.get(id=rec_id)
    block_reason = get_recruitment_application_block_reason(recruitment)
    if block_reason:
        return render(
            request,
            "candidate/application_unavailable.html",
            {"recruitment": recruitment, "message": block_reason},
        )
    sync_recruitment_survey_links(recruitment)
    if not recruitment_has_survey(recruitment):
        return redirect(reverse("application-success"))
    stage_id = candidate_dict[0]["fields"]["stage_id"]
    candidate_dict[0]["fields"]["recruitment_id"] = recruitment
    candidate_dict[0]["fields"]["job_position_id"] = job
    candidate_dict[0]["fields"]["stage_id"] = Stage.objects.get(id=stage_id)
    candidate = Candidate(**candidate_dict[0]["fields"])
    form = SurveyForm(recruitment=recruitment).form
    if request.method == "POST":
        if not Candidate.objects.filter(
            email=candidate.email, recruitment_id=candidate.recruitment_id
        ).exists():
            candidate.save()
        else:
            candidate = Candidate.objects.filter(
                email=candidate.email, recruitment_id=candidate.recruitment_id
            ).first()
        answer = (
            RecruitmentSurveyAnswer()
            if candidate.recruitmentsurveyanswer_set.first() is None
            else candidate.recruitmentsurveyanswer_set.first()
        )
        answer.candidate_id = candidate

        other_texts = {
            key.replace("other_text_", ""): value
            for key, value in request.POST.items()
            if key.startswith("other_text_")
        }
        question_by_text = {
            question.question: question
            for question in _recruitment_survey_questions(recruitment)
        }

        # Process the POST data to properly handle multiple values
        answer_data = {}
        for key, value in request.POST.items():
            if key.startswith("other_text_") or key == "csrfmiddlewaretoken":
                continue
            if key.startswith("multiple_choices_"):
                parts = key.split("_", 2)
                question_text = parts[2]
                selected_choices = request.POST.getlist(key)
                question = question_by_text.get(question_text)
                if question and question.allow_other:
                    selected_choices = _format_survey_other_answer(
                        selected_choices, question.id, other_texts
                    )
                answer_data[question_text] = selected_choices
            elif key.startswith("date_"):
                parts = key.split("_", 1)
                question_text = parts[1]
                selected_choices = request.POST.getlist(key)
                if selected_choices and selected_choices[0] != "":
                    formatted_dates = [
                        datetime.strptime(date, "%Y-%m-%d").strftime("%d-%m-%Y")
                        for date in selected_choices
                    ]
                    answer_data[question_text] = formatted_dates
            else:
                question = question_by_text.get(key)
                if question and question.allow_other:
                    value = _format_survey_other_answer(value, question.id, other_texts)
                answer_data[key] = [value]
        for key, value in request.FILES.items():
            attachment = request.FILES[key]
            if attachment.size > MAX_FILE_SIZE:
                messages.error(
                    request, _("File size exceeds the limit. Maximum size is 5 MB")
                )
                return render(
                    request,
                    "survey/candidate_survey_form.html",
                    {"form": form, "candidate": candidate, "recruitment": recruitment},
                )
            attachment_path = f"recruitment_attachment/{attachment.name}"
            attachment_dir = os.path.dirname(default_storage.path(attachment_path))
            if not os.path.exists(attachment_dir):
                os.makedirs(attachment_dir)
            with default_storage.open(attachment_path, "wb+") as destination:
                for chunk in attachment.chunks():
                    destination.write(chunk)
            answer.attachment = attachment_path
            answer_data[key] = [attachment_path]
        answer.answer_json = json.dumps(answer_data)
        answer.save()
        messages.success(request, _("Your answers are submitted."))
        return render(request, "candidate/success.html")
    return render(
        request,
        "survey/candidate_survey_form.html",
        {"form": form, "candidate": candidate, "recruitment": recruitment},
    )


@login_required
@is_recruitment_manager(perm="recruitment.view_recruitmentsurvey")
def view_question_template(request):
    """
    This method is used to view the question template
    """
    recs = Recruitment.objects.all()
    ids = []
    for i in recs:
        for manager in i.recruitment_managers.all():
            if request.user.employee_get == manager:
                ids.append(i.id)
    if request.user.has_perm("recruitment.view_recruitmentsurvey"):
        questions = RecruitmentSurvey.objects.all()
    else:
        questions = RecruitmentSurvey.objects.filter(recruitment_ids__in=ids)
    templates = group_by_queryset(
        questions.filter(template_id__isnull=False).distinct(),
        "template_id__title",
        page=request.GET.get("template_page"),
        page_name="template_page",
        records_per_page=get_pagination(),
    )
    all_template_object_list = []
    for template in templates:
        all_template_object_list.append(template)

    survey_templates = SurveyTemplate.objects.all()
    all_templates = survey_templates.values_list("title", flat=True)
    used_templates = questions.values_list("template_id__title", flat=True)

    unused_templates = list(set(all_templates) - set(used_templates))
    unused_groups = []
    for template_name in unused_templates:
        unused_groups.append(
            {
                "grouper": template_name,
                "list": [],
                "dynamic_name": "",
            }
        )
    all_template_object_list = all_template_object_list + unused_groups

    templates = paginator_qry(
        all_template_object_list, request.GET.get("template_page")
    )
    survey_templates = paginator_qry(
        survey_templates, request.GET.get("survey_template_page")
    )
    filter_obj = SurveyFilter()
    requests_ids = json.dumps(
        [
            instance.id
            for instance in paginator_qry(
                questions, request.GET.get("page")
            ).object_list
        ]
    )
    return render(
        request,
        "survey/view_question_templates.html",
        {
            "questions": paginator_qry(questions, request.GET.get("page")),
            "templates": templates,
            "survey_templates": survey_templates,
            "f": filter_obj,
            "requests_ids": requests_ids,
        },
    )


@login_required
@hx_request_required
@permission_required(perm="recruitment.change_recruitmentsurvey")
def update_question_template(request, survey_id):
    """
    This view method is used to update question template
    """
    instance = RecruitmentSurvey.objects.get(id=survey_id)
    form = QuestionForm(
        instance=instance,
    )
    if request.method == "POST":
        form = QuestionForm(request.POST, instance=instance)
        if form.is_valid():
            instance = form.save()
            instance.template_id.set(form.cleaned_data["template_id"])
            instance.recruitment_ids.set(form.recruitment)
            # instance.job_position_ids.set(form.job_positions)
            messages.success(request, _("New survey question updated."))
            return HttpResponse(
                render(
                    request, "survey/template_update_form.html", {"form": form}
                ).content.decode("utf-8")
                + "<script>location.reload();</script>"
            )
    return render(request, "survey/template_update_form.html", {"form": form})


@login_required
@hx_request_required
@permission_required(perm="recruitment.add_recruitmentsurvey")
def create_question_template(request):
    """
    This view method is used to create question template
    """
    form = QuestionForm()
    if request.method == "POST":
        form = QuestionForm(request.POST)
        if form.is_valid():
            instance = form.save()
            instance.recruitment_ids.set(form.recruitment)
            instance.template_id.set(form.cleaned_data["template_id"])
            # instance.job_position_ids.set(form.job_positions)
            messages.success(request, _("New survey question created."))
            return HttpResponse(
                render(
                    request, "survey/template_form.html", {"form": form}
                ).content.decode("utf-8")
                + "<script>location.reload();</script>"
            )
    return render(request, "survey/template_form.html", {"form": form})


@login_required
@permission_required(perm="recruitment.delete_recruitmentsurvey")
def delete_survey_question(request, survey_id):
    """
    This method is used to delete the survey instance
    """
    try:
        RecruitmentSurvey.objects.get(id=survey_id).delete()
        messages.success(request, _("Question was deleted successfully"))
    except RecruitmentSurvey.DoesNotExist:
        messages.error(request, _("Question not found."))
    except ProtectedError:
        messages.error(request, _("You cannot delete this question"))
    return redirect(view_question_template)


def application_success(request):
    """Success page after application form submission (used for AJAX redirect)."""
    return render(request, "candidate/success.html")


def application_form(request):
    """
    This method renders candidate form to create candidate
    """
    recruitment = None
    recruitment_id = request.GET.get("recruitmentId")
    resume_id = request.GET.get("resumeId")
    resume_obj = Resume.objects.filter(id=resume_id).first()

    if request.method == "GET" and not recruitment_id:
        messages.error(request, _("Recruitment ID is missing"))
        return redirect("open-recruitments")

    try:
        recruitment = Recruitment.objects.filter(id=recruitment_id).first()
        if not recruitment:
            messages.error(request, _("Recruitment not found"))
            return redirect("open-recruitments")
        sync_recruitment_survey_links(recruitment)
    except (ValueError, OverflowError):
        messages.error(request, _("Invalid Recruitment ID"))
        return redirect("open-recruitments")

    block_reason = get_recruitment_application_block_reason(recruitment)
    if block_reason:
        return render(
            request,
            "candidate/application_unavailable.html",
            {"recruitment": recruitment, "message": block_reason},
        )

    if request.POST:
        if "resume" not in request.FILES and resume_id:
            if resume_obj and resume_obj.file:
                file_content = resume_obj.file.read()
                pdf_file = SimpleUploadedFile(
                    resume_obj.file.name, file_content, content_type="application/pdf"
                )
                request.FILES["resume"] = pdf_file

        form = ApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            candidate_obj = form.save(commit=False)
            recruitment_obj = candidate_obj.recruitment_id
            sync_recruitment_survey_links(recruitment_obj)
            stages = recruitment_obj.stage_set.all()
            if stages.filter(stage_type="applied").exists():
                candidate_obj.stage_id = stages.filter(stage_type="applied").first()
            else:
                candidate_obj.stage_id = stages.order_by("sequence").first()
            messages.success(request, _("Application saved."))

            request.session["candidate"] = serializers.serialize(
                "json", [candidate_obj]
            )
            # Save the candidate first to ensure file is persisted
            candidate_obj.save()
            
            # Send email notification to recruitment managers
            try:
                recruitment_obj = candidate_obj.recruitment_id
                if not recruitment_obj:
                    logger.warning(f"Candidate {candidate_obj.id} has no recruitment_id")
                else:
                    managers = recruitment_obj.recruitment_managers.select_related("employee_user_id")
                    
                    logger.info(f"Found {managers.count()} recruitment managers for recruitment {recruitment_obj.id} ({recruitment_obj.title})")
                    
                    if managers.exists():
                        # Get manager emails
                        manager_emails = []
                        manager_users = []
                        for manager in managers:
                            try:
                                if hasattr(manager, "employee_user_id") and manager.employee_user_id:
                                    user = manager.employee_user_id
                                    if user.email:
                                        manager_emails.append(user.email)
                                        logger.info(f"Added manager email: {user.email} (User: {user.username})")
                                    else:
                                        logger.warning(f"Manager {manager} has no email address")
                                    manager_users.append(user)
                                else:
                                    logger.warning(f"Manager {manager} has no employee_user_id")
                            except Exception as e:
                                logger.error(f"Error processing manager {manager}: {e}")
                        
                        logger.info(f"Total manager emails to send: {len(manager_emails)}")
                        logger.info(f"Manager emails: {manager_emails}")
                        
                        if not manager_emails:
                            logger.warning(f"No valid email addresses found for recruitment managers of {recruitment_obj.title}")
                    
                        # Send in-app notifications
                        if manager_users:
                            try:
                                candidate_view_url = reverse("candidate-view-individual", args=[candidate_obj.id])
                            except Exception:
                                candidate_view_url = f"/recruitment/candidate-view/{candidate_obj.id}/"
                            
                            try:
                                notify.send(
                                    request.user if request.user.is_authenticated else None,
                                    recipient=manager_users,
                                    verb=f"New application received for {recruitment_obj.title}",
                                    verb_ar=f"تم استلام طلب جديد لـ {recruitment_obj.title}",
                                    verb_de=f"Neue Bewerbung erhalten für {recruitment_obj.title}",
                                    verb_es=f"Nueva solicitud recibida para {recruitment_obj.title}",
                                    verb_fr=f"Nouvelle candidature reçue pour {recruitment_obj.title}",
                                    icon="person-add",
                                    redirect=candidate_view_url,
                                )
                                logger.info(f"In-app notifications sent to {len(manager_users)} managers")
                            except Exception as notify_error:
                                logger.error(f"Failed to send in-app notifications: {notify_error}")
                        
                        # Send email notifications
                        if manager_emails:
                            try:
                                from base.backends import ConfiguredEmailBackend
                                
                                # Check if email backend is configured
                                email_backend = ConfiguredEmailBackend()
                                if not email_backend.configuration:
                                    logger.warning("Email backend not configured. Skipping email notification.")
                                else:
                                    protocol = "https" if request.is_secure() else "http"
                                    host = request.get_host()
                                    try:
                                        candidate_url = request.build_absolute_uri(
                                            reverse("candidate-view-individual", args=[candidate_obj.id])
                                        )
                                    except Exception:
                                        candidate_url = f"{protocol}://{host}/recruitment/candidate-view/{candidate_obj.id}/"
                                    
                                    subject = f"New Application Received: {candidate_obj.name} - {recruitment_obj.title}"
                                    
                                    # Try to render the HTML template, fallback to plain text if template missing
                                    try:
                                        html_message = render_to_string(
                                            "recruitment/emails/new_application_notification.html",
                                            {
                                                "candidate": candidate_obj,
                                                "recruitment": recruitment_obj,
                                                "candidate_url": candidate_url,
                                                "host": host,
                                                "protocol": protocol,
                                            },
                                            request=request,
                                        )
                                    except Exception as template_error:
                                        logger.warning(f"Email template not found, using plain text: {template_error}")
                                        html_message = f"""
                                        <html>
                                        <body>
                                            <h2>New Application Received</h2>
                                            <p>A new candidate has applied for: <strong>{recruitment_obj.title}</strong></p>
                                            <p><strong>Candidate Name:</strong> {candidate_obj.name}</p>
                                            <p><strong>Email:</strong> {candidate_obj.email}</p>
                                            <p><strong>Phone:</strong> {candidate_obj.mobile or 'N/A'}</p>
                                            <p><a href="{candidate_url}">View Candidate Profile</a></p>
                                        </body>
                                        </html>
                                        """
                                    
                                    email = EmailMessage(
                                        subject=subject,
                                        body=html_message,
                                        to=manager_emails,
                                        connection=email_backend,
                                    )
                                    email.content_subtype = "html"
                                    
                                    try:
                                        email.send()
                                        logger.info(f"Application notification email sent successfully to {len(manager_emails)} recruitment managers: {manager_emails}")
                                    except Exception as e:
                                        logger.error(f"Failed to send application notification email to {manager_emails}: {e}", exc_info=True)
                            except Exception as e:
                                logger.error(f"Error preparing application notification email: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Error sending application notifications: {e}")
            
            if recruitment_has_survey(recruitment_obj):
                try:
                    employee = request.user.employee_get
                    if (
                        not request.user.has_perm("perms.recruitment.add_candidate")
                        or employee not in recruitment.recruitment_managers.all()
                        or not employee.stage_set.filter(recruitment_id=recruitment)
                    ):
                        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                            return JsonResponse(
                                {"success": True, "redirect_url": reverse("candidate-survey")}
                            )
                        return redirect(candidate_survey)
                except Exception:
                    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                        return JsonResponse(
                            {"success": True, "redirect_url": reverse("candidate-survey")}
                        )
                    return redirect(candidate_survey)

            if resume_obj:
                resume_obj.is_candidate = True
                resume_obj.save()

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {"success": True, "redirect_url": reverse("application-success")}
                )
            return render(request, "candidate/success.html")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": False,
                    "errors": {k: [str(e) for e in v] for k, v in form.errors.items()},
                },
                status=400,
            )
        form.fields["job_position_id"].queryset = (
            form.instance.recruitment_id.open_positions.all()
        )
    else:
        # 811
        initial_data = {"resume": resume_obj.file.url} if resume_obj else {}
        form = ApplicationForm(initial=initial_data)

    return render(
        request,
        "candidate/application_form.html",
        {
            "form": form,
            "recruitment": recruitment,
            "resume": resume_obj,
            "has_survey": recruitment_has_survey(recruitment),
        },
    )


@login_required
@hx_request_required
@is_recruitment_manager(perm="recruitment.view_recruitmentsurvey")
def single_survey(request, survey_id):
    """
    This view method is used to single view of question template
    """
    question = RecruitmentSurvey.objects.get(id=survey_id)
    requests_ids_json = request.GET.get("instances_ids")
    context = {"question": question}
    if requests_ids_json:
        requests_ids = json.loads(requests_ids_json)
        previous_id, next_id = closest_numbers(requests_ids, survey_id)
        context["previous"] = previous_id
        context["next"] = next_id
        context["requests_ids"] = requests_ids_json
    return render(request, "survey/view_single_template.html", context)


@login_required
@hx_request_required
def create_template(request):
    """
    Create question template views
    """
    # Check if the user has any of the two permissions
    if not (
        request.user.has_perm("recruitment.add_surveytemplate")
        or request.user.has_perm("recruitment.change_surveytemplate")
    ):
        messages.info(request, "You dont have permission.")
        return HttpResponse("<script>window.location.reload()</script>")

    title = request.GET.get("title")
    instance = None
    if title:
        instance = SurveyTemplate.objects.filter(title=title).first()
    form = TemplateForm(instance=instance)
    if request.method == "POST":
        form = TemplateForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Template saved")
            return HttpResponse("<script>window.location.reload()</script>")
    return render(request, "survey/main_form.html", {"form": form})


@login_required
@permission_required("recruitment.delete_surveytemplate")
def delete_template(request):
    """
    This method is used to delete the survey template group
    """
    title = request.GET.get("title")
    SurveyTemplate.objects.filter(title=str(title)).delete()
    if title == "None":
        messages.info(request, "This template group cannot be deleted")
    else:
        messages.success(request, "Template group deleted")

    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@hx_request_required
@permission_required("recruitment.change_surveytemplate")
def question_add(request):
    """
    This method is used to add survey question to the templates
    """
    template = None
    title = request.GET.get("title")
    if title:
        template = SurveyTemplate.objects.filter(title=title).first

    form = AddQuestionForm(initial={"template_ids": template})
    if request.method == "POST":
        form = AddQuestionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Question added")
            return HttpResponse("<script>window.location.reload()</script>")
    return render(request, "survey/add_form.html", {"form": form})
