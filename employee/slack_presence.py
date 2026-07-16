"""
Slack presence sync via users.getPresence (polling) and users.list for auto-linking.

presence_change is not available in "Subscribe to bot events". Use this instead:
- Set SLACK_BOT_TOKEN (Bot User OAuth Token with users:read).
- sync_slack_users(): match Slack members to Employee by email or phone, set slack_user_id. Run once or nightly.
- sync_slack_presence(): fetch active/away for linked employees. Scheduler runs every 3 min. Uses "online" (client connected) so it matches Slack's green dot.

Linking: email (Employee.email, employee_work_info.email) and phone (Employee.phone, employee_work_info.mobile).
Phone matching uses last 10 digits so +91 9876543210 matches 9876543210. Slack profile.phone depends on workspace.
"""

import logging
import re

import requests

logger = logging.getLogger(__name__)

# Timeouts: (connect, read) in seconds. Keep read low so one slow Slack reply doesn't block the job.
SLACK_REQUEST_CONNECT_TIMEOUT = 5
SLACK_REQUEST_READ_TIMEOUT = 15

USERS_GET_PRESENCE_URL = "https://slack.com/api/users.getPresence"
USERS_LIST_URL = "https://slack.com/api/users.list"


def _normalize_phone_key(phone_value):
    """Extract digits and return last 10 (or all if shorter). None if no digits."""
    if not phone_value:
        return None
    dig = re.sub(r"\D", "", str(phone_value))
    if not dig:
        return None
    return dig[-10:] if len(dig) >= 10 else dig


def link_employee_to_slack(employee):
    """
    Find a Slack member with matching email or phone and set employee.slack_user_id.
    Called on Employee post_save (created) so new employees are linked automatically.
    No-op if already linked or SLACK_BOT_TOKEN not set. Tries email first, then phone.
    """
    from django.conf import settings

    from base.models import SlackConfiguration
    from employee.models import Employee

    if (getattr(employee, "slack_user_id", None) or "").strip():
        return
    # Try to get token from database first, fall back to settings
    slack_config = SlackConfiguration.objects.filter(is_active=True).first()
    token = None
    if slack_config and slack_config.slack_bot_token:
        token = slack_config.slack_bot_token
    if not token:
        token = getattr(settings, "SLACK_BOT_TOKEN", None)
    if not token or not str(token).strip():
        return

    email = ((employee.email or "").strip() or "").lower()
    emp_phone_key = _normalize_phone_key((employee.phone or "").strip())
    work_mobile = (getattr(getattr(employee, "employee_work_info", None), "mobile", None) or "").strip()
    if not emp_phone_key and work_mobile:
        emp_phone_key = _normalize_phone_key(work_mobile)
    if not email and not emp_phone_key:
        return

    headers = {"Authorization": f"Bearer {token.strip()}"}
    cursor = None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(USERS_LIST_URL, headers=headers, params=params, timeout=30)
            data = r.json()
        except Exception as e:
            logger.exception("Slack users.list (link_employee) failed: %s", e)
            return
        if not data.get("ok"):
            return
        for u in data.get("members") or []:
            if u.get("is_bot") or u.get("deleted"):
                continue
            profile = u.get("profile") or {}
            slack_id = u.get("id")
            if not slack_id:
                continue
            # 1) Email match
            em = (profile.get("email") or "").strip().lower()
            if email and em == email:
                Employee.objects.filter(pk=employee.pk).update(slack_user_id=slack_id)
                return
            # 2) Phone match (when email differs or is missing, e.g. Slack personal vs HRMS work)
            if emp_phone_key:
                slack_key = _normalize_phone_key(profile.get("phone") or "")
                if slack_key and slack_key == emp_phone_key:
                    Employee.objects.filter(pk=employee.pk).update(slack_user_id=slack_id)
                    return
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break


def sync_slack_users():
    """
    Fetch Slack users via users.list, match by email or phone to Employee, set slack_user_id.
    Email: profile.email vs Employee.email or employee_work_info.email.
    Phone: profile.phone vs Employee.phone or employee_work_info.mobile (last 10 digits).
    No-op if SLACK_BOT_TOKEN is not set. Supports pagination. Skips bots and deleted.
    """
    from django.conf import settings
    from django.db.models import Q

    from base.models import SlackConfiguration
    from employee.models import Employee

    # Try to get token from database first, fall back to settings
    slack_config = SlackConfiguration.objects.filter(is_active=True).first()
    token = None
    if slack_config and slack_config.slack_bot_token:
        token = slack_config.slack_bot_token
    if not token:
        token = getattr(settings, "SLACK_BOT_TOKEN", None)
    if not token or not token.strip():
        return 0

    # Build phone_map from unlinked employees: norm_phone -> set(employee.pk)
    unlinked = (
        Employee.objects.filter(Q(slack_user_id__isnull=True) | Q(slack_user_id=""))
        .filter(is_active=True)
        .filter(
            (Q(phone__isnull=False) & ~Q(phone=""))
            | (Q(employee_work_info__mobile__isnull=False) & ~Q(employee_work_info__mobile=""))
        )
        .select_related("employee_work_info")
    )
    phone_map = {}
    for emp in unlinked:
        for raw in [(emp.phone or "").strip(), (getattr(emp.employee_work_info, "mobile", None) or "").strip()]:
            k = _normalize_phone_key(raw)
            if k:
                phone_map.setdefault(k, set()).add(emp.pk)

    headers = {"Authorization": f"Bearer {token.strip()}"}
    updated = 0
    linked_pks = set()
    cursor = None

    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(USERS_LIST_URL, headers=headers, params=params, timeout=30)
            data = r.json()
        except Exception as e:
            logger.exception("Slack users.list request failed: %s", e)
            return updated
        if not data.get("ok"):
            logger.warning("Slack users.list failed: %s", data.get("error", "unknown"))
            return updated

        for u in data.get("members") or []:
            if u.get("is_bot") or u.get("deleted"):
                continue
            profile = u.get("profile") or {}
            slack_id = u.get("id")
            if not slack_id:
                continue
            email = (profile.get("email") or "").strip()
            profile_phone = (profile.get("phone") or "").strip()

            # 1) Email match
            if email:
                to_link = list(
                    Employee.objects.filter(
                        Q(email__iexact=email) | Q(employee_work_info__email__iexact=email)
                    )
                    .exclude(pk__in=linked_pks)
                    .values_list("pk", flat=True)
                )
                if to_link:
                    Employee.objects.filter(pk__in=to_link).update(slack_user_id=slack_id)
                    updated += len(to_link)
                    linked_pks |= set(to_link)
                    continue

            # 2) Phone match (e.g. Slack personal email vs HRMS work email; same mobile in both)
            if profile_phone:
                key = _normalize_phone_key(profile_phone)
                if key:
                    pks = [p for p in (phone_map.get(key) or set()) if p not in linked_pks]
                    if pks:
                        Employee.objects.filter(pk__in=pks).update(slack_user_id=slack_id)
                        updated += len(pks)
                        linked_pks |= set(pks)

        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return updated


def sync_slack_presence():
    """
    Fetch presence (active/away) from Slack users.getPresence for all
    Employee.slack_user_id and update SlackPresence. No-op if SLACK_BOT_TOKEN
    is not set.
    """
    from django.conf import settings

    from base.models import SlackConfiguration
    from employee.models import Employee, SlackPresence

    # Try to get token from database first, fall back to settings
    slack_config = SlackConfiguration.objects.filter(is_active=True).first()
    token = None
    if slack_config and slack_config.slack_bot_token:
        token = slack_config.slack_bot_token
    if not token:
        token = getattr(settings, "SLACK_BOT_TOKEN", None)
    if not token or not token.strip():
        return 0

    slack_ids = list(
        Employee.objects.filter(slack_user_id__isnull=False)
        .exclude(slack_user_id="")
        .values_list("slack_user_id", flat=True)
        .distinct()
    )
    if not slack_ids:
        return 0

    updated = 0
    timeout_tuple = (SLACK_REQUEST_CONNECT_TIMEOUT, SLACK_REQUEST_READ_TIMEOUT)
    for uid in slack_ids:
        try:
            r = requests.get(
                USERS_GET_PRESENCE_URL,
                params={"user": uid},
                headers={"Authorization": f"Bearer {token.strip()}"},
                timeout=timeout_tuple,
            )
            data = r.json()
            if not data.get("ok"):
                logger.debug(
                    "Slack users.getPresence failed for %s: %s",
                    uid,
                    data.get("error", "unknown"),
                )
                continue
            # Match Slack's green dot: "online"/connection_count = has client; "presence" = active/away. Treat any as Online.
            is_online = data.get("online") is True
            has_connection = (data.get("connection_count") or 0) > 0
            p = (data.get("presence") or "away").lower()
            presence = "active" if (is_online or has_connection or p == "active") else "away"
            SlackPresence.objects.update_or_create(
                slack_user_id=uid,
                defaults={"presence": presence},
            )
            updated += 1
        except requests.exceptions.Timeout as e:
            logger.warning(
                "Slack presence sync timeout for %s (skipping): %s",
                uid,
                e,
            )
        except requests.exceptions.RequestException as e:
            logger.warning(
                "Slack presence sync failed for %s: %s",
                uid,
                e,
            )
        except Exception as e:
            logger.exception("Slack presence sync failed for %s: %s", uid, e)
    return updated
