"""
Slack Events API endpoint for Horilla.

Handles:
- url_verification: Slack sends a challenge that must be echoed back for Request URL verification.
- event_callback with presence_change: Updates stored presence (active/away) if Slack sends it.

Note: presence_change is often NOT available in "Subscribe to bot events". For Online/Offline
use polling instead: set SLACK_BOT_TOKEN (users:read), set Employee.slack_user_id, and run
  python manage.py sync_slack_presence
(or the scheduler runs it every 5 minutes).

Optional: Set SLACK_SIGNING_SECRET in settings to verify request signatures.
"""

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _verify_slack_signature(request):
    """Verify X-Slack-Signature using SLACK_SIGNING_SECRET. Returns True if ok or if not configured."""
    secret = getattr(settings, "SLACK_SIGNING_SECRET", None)
    if not secret:
        return True
    sig = request.headers.get("X-Slack-Signature", "")
    if not sig.startswith("v0="):
        return False
    expected = sig.split("v0=", 1)[1]
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    body = request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    basestr = f"v0:{timestamp}:{body}"
    computed = hmac.new(
        secret.encode() if isinstance(secret, str) else secret,
        basestr.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest("v0=" + computed, "v0=" + expected)


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(require_http_methods(["POST"]), name="dispatch")
class SlackEventsView(View):
    """
    Receives Events from Slack (Request URL).
    - url_verification: respond with {"challenge": "<challenge>"}
    - event_callback: handle presence_change and respond 200 quickly.
    """

    def post(self, request):
        try:
            body = request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        if not _verify_slack_signature(request):
            return JsonResponse({"error": "Invalid signature"}, status=401)

        # URL verification (required for Slack to accept the Request URL)
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            if challenge is None:
                return JsonResponse({"error": "Missing challenge"}, status=400)
            return JsonResponse({"challenge": challenge})

        # Event callbacks
        if data.get("type") == "event_callback":
            event = data.get("event") or {}
            if event.get("type") == "presence_change":
                user_id = event.get("user")
                presence = event.get("presence")  # 'active' | 'away'
                if user_id and presence:
                    try:
                        from employee.models import SlackPresence

                        SlackPresence.objects.update_or_create(
                            slack_user_id=user_id,
                            defaults={"presence": presence},
                        )
                    except Exception as e:
                        logger.exception("Slack presence update failed: %s", e)
            # Always return 200 quickly for event_callback
            return JsonResponse({"ok": True})

        return JsonResponse({"ok": True})
