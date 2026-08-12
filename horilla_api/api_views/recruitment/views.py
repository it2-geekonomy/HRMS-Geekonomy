"""
Public API for Closers Fellowship website form submissions.
Authenticated via CLOSERS_FELLOWSHIP_API_KEY (X-API-Key or Authorization: Api-Key).
"""

from django.conf import settings
from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from recruitment.models import ClosersFellowshipApplication


def get_closers_fellowship_api_key():
    """API key from settings (.env: CLOSERS_FELLOWSHIP_API_KEY, falls back to CRM_API_KEY)."""
    return (
        getattr(settings, "CLOSERS_FELLOWSHIP_API_KEY", "").strip()
        or getattr(settings, "CRM_API_KEY", "").strip()
    )


def request_has_valid_api_key(request):
    key = get_closers_fellowship_api_key()
    if not key:
        return False
    header_key = request.META.get("HTTP_X_API_KEY", "").strip()
    if header_key and header_key == key:
        return True
    auth = request.META.get("HTTP_AUTHORIZATION", "").strip()
    if auth.lower().startswith("api-key "):
        return auth[7:].strip() == key
    query_key = (
        request.GET.get("X-API-Key")
        or request.GET.get("api_key")
        or request.GET.get("x-api-key")
        or ""
    ).strip()
    return bool(query_key and query_key == key)


class IsClosersFellowshipApiKey(BasePermission):
    def has_permission(self, request, view):
        key = get_closers_fellowship_api_key()
        if not key:
            raise AuthenticationFailed(
                "Closers Fellowship API key is not configured."
            )
        if not request_has_valid_api_key(request):
            raise AuthenticationFailed(
                "Invalid or missing API key. Use X-API-Key header or Authorization: Api-Key <key>."
            )
        return True


def _first_value(data, *keys, default=""):
    """Return the first non-empty value for any of the given keys."""
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def normalize_application_payload(data):
    """Map website form / UTM field names to model fields."""
    if not isinstance(data, dict):
        raise ValidationError({"detail": "Request body must be a JSON object."})

    full_name = _first_value(data, "full_name", "fullName", "name")
    email = _first_value(data, "email")
    if not full_name:
        raise ValidationError({"full_name": "This field is required."})
    if not email:
        raise ValidationError({"email": "This field is required."})

    return {
        "full_name": full_name,
        "email": email,
        "phone": _first_value(data, "phone", "phone_whatsapp", "phoneWhatsapp"),
        "seat": _first_value(
            data, "seat", "which_seat", "which_seat_fits_you", "seat_fits_you"
        ),
        "linkedin_portfolio": _first_value(
            data, "linkedin_portfolio", "linkedin", "portfolio", "linkedin_or_portfolio"
        ),
        "answer_q1": _first_value(data, "answer_q1", "q1"),
        "answer_q2": _first_value(data, "answer_q2", "q2"),
        "answer_q3": _first_value(data, "answer_q3", "q3"),
        "utm_campaign": _first_value(data, "utm_campaign", "campaign"),
        "utm_content": _first_value(data, "utm_content", "ad", "content"),
        "utm_term": _first_value(data, "utm_term", "adset", "term"),
        "utm_source": _first_value(data, "utm_source", "source"),
        "utm_medium": _first_value(data, "utm_medium", "medium"),
    }


class ClosersFellowshipSubmitView(APIView):
    """
    POST /api/recruitment/closers-fellowship/

    Accepts JSON or form-urlencoded body. Required: full_name, email.
    """

    permission_classes = [IsClosersFellowshipApiKey]
    authentication_classes = []

    def post(self, request):
        payload = normalize_application_payload(request.data)
        try:
            application = ClosersFellowshipApplication.objects.create(**payload)
        except IntegrityError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        return Response(
            {
                "success": True,
                "id": application.id,
                "message": "Application submitted successfully.",
            },
            status=status.HTTP_201_CREATED,
        )
