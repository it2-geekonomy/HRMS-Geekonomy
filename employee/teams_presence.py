"""
Microsoft Teams presence via Microsoft Graph API.

Uses app-only (client credentials) auth:
- Presence.Read.All
- User.Read.All

Flow mirrors Slack:
- sync_teams_users(): match Entra ID users to Employee by email, set teams_user_id
- sync_teams_presence(): poll getPresencesByUserId every few minutes
- Online = Teams availability Available only (green). All others = Offline.
"""

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TOKEN_URL_TMPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
USERS_URL = f"{GRAPH_BASE}/users"
PRESENCES_URL = f"{GRAPH_BASE}/communications/getPresencesByUserId"

REQUEST_TIMEOUT = (5, 30)
# Graph allows up to 650 IDs per getPresencesByUserId call
PRESENCE_BATCH_SIZE = 100

# Cache app token in-process
_token_cache = {"access_token": None, "expires_at": 0}

# Online only when Teams shows Available (green). Everything else = Offline.
ONLINE_AVAILABILITY = {
    "Available",
}


def teams_configured():
    """True when Azure app credentials are set in env."""
    client_id = (getattr(settings, "TEAMS_CLIENT_ID", None) or "").strip()
    client_secret = (getattr(settings, "TEAMS_CLIENT_SECRET", None) or "").strip()
    tenant_id = (getattr(settings, "TEAMS_TENANT_ID", None) or "").strip()
    return bool(client_id and client_secret and tenant_id)


def _get_access_token():
    """Client-credentials token for Microsoft Graph. Cached until near expiry."""
    if not teams_configured():
        return None

    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    tenant = settings.TEAMS_TENANT_ID.strip()
    url = TOKEN_URL_TMPL.format(tenant=tenant)
    data = {
        "client_id": settings.TEAMS_CLIENT_ID.strip(),
        "client_secret": settings.TEAMS_CLIENT_SECRET.strip(),
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    try:
        r = requests.post(url, data=data, timeout=REQUEST_TIMEOUT)
        payload = r.json()
    except Exception as e:
        logger.exception("Teams token request failed: %s", e)
        return None

    token = payload.get("access_token")
    if not token:
        logger.warning(
            "Teams token failed: %s",
            payload.get("error_description") or payload.get("error") or payload,
        )
        return None

    expires_in = int(payload.get("expires_in") or 3600)
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + expires_in
    return token


def _auth_headers():
    token = _get_access_token()
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _availability_to_presence(availability):
    """Map Graph availability string to active/away (Online/Offline in UI)."""
    avail = (availability or "PresenceUnknown").strip()
    return "active" if avail in ONLINE_AVAILABILITY else "away"


def link_employee_to_teams(employee):
    """
    Match one employee to Entra ID by email and set teams_user_id.
    Called on Employee create. No-op if already linked or Teams not configured.
    """
    from employee.models import Employee

    if not teams_configured():
        return
    if (getattr(employee, "teams_user_id", None) or "").strip():
        return

    email = ((employee.email or "").strip() or "").lower()
    work_email = ""
    try:
        work_email = (employee.employee_work_info.email or "").strip().lower()
    except Exception:
        work_email = ""
    emails = [e for e in {email, work_email} if e]
    if not emails:
        return

    headers = _auth_headers()
    if not headers:
        return

    for em in emails:
        # Prefer exact mail / UPN match
        filter_q = f"mail eq '{em}' or userPrincipalName eq '{em}'"
        try:
            r = requests.get(
                USERS_URL,
                headers=headers,
                params={
                    "$select": "id,mail,userPrincipalName",
                    "$filter": filter_q,
                    "$top": "5",
                },
                timeout=REQUEST_TIMEOUT,
            )
            data = r.json()
        except Exception as e:
            logger.exception("Teams user lookup failed for %s: %s", em, e)
            return

        if r.status_code >= 400:
            logger.debug(
                "Teams user filter failed (%s): %s",
                r.status_code,
                data.get("error", data),
            )
            # Fallback: list and match (some tenants restrict $filter)
            continue

        for u in data.get("value") or []:
            uid = u.get("id")
            if uid:
                Employee.objects.filter(pk=employee.pk).update(teams_user_id=uid)
                return


def sync_teams_users():
    """
    List Entra ID users and link Employee.teams_user_id by email / UPN.
    Returns number of employees linked/updated.
    """
    from django.db.models import Q

    from employee.models import Employee

    if not teams_configured():
        return 0

    headers = _auth_headers()
    if not headers:
        return 0

    # Build email -> employee pks for active employees
    employees = (
        Employee.objects.filter(is_active=True)
        .select_related("employee_work_info")
        .only("id", "email", "teams_user_id", "employee_work_info__email")
    )
    email_map = {}
    for emp in employees:
        work_email = ""
        try:
            work_email = (emp.employee_work_info.email or "").strip().lower()
        except Exception:
            work_email = ""
        for raw in [
            (emp.email or "").strip().lower(),
            work_email,
        ]:
            if raw:
                email_map.setdefault(raw, set()).add(emp.pk)

    if not email_map:
        return 0

    updated = 0
    linked_pks = set()
    url = USERS_URL
    params = {
        "$select": "id,mail,userPrincipalName,otherMails,accountEnabled",
        "$top": "999",
    }

    while url:
        try:
            if url == USERS_URL:
                r = requests.get(
                    url, headers=headers, params=params, timeout=REQUEST_TIMEOUT
                )
            else:
                r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            data = r.json()
        except Exception as e:
            logger.exception("Teams users.list failed: %s", e)
            return updated

        if r.status_code >= 400:
            logger.warning(
                "Teams users.list HTTP %s: %s",
                r.status_code,
                data.get("error", data),
            )
            return updated

        for u in data.get("value") or []:
            if u.get("accountEnabled") is False:
                continue
            uid = u.get("id")
            if not uid:
                continue
            candidates = set()
            for raw in [
                (u.get("mail") or "").strip().lower(),
                (u.get("userPrincipalName") or "").strip().lower(),
            ]:
                if raw:
                    candidates.add(raw)
            for om in u.get("otherMails") or []:
                if om:
                    candidates.add(str(om).strip().lower())

            to_link = set()
            for em in candidates:
                to_link |= email_map.get(em) or set()
            to_link -= linked_pks
            if not to_link:
                continue

            # Only update when teams_user_id empty or different
            qs = Employee.objects.filter(pk__in=to_link).filter(
                Q(teams_user_id__isnull=True) | Q(teams_user_id="") | ~Q(teams_user_id=uid)
            )
            n = qs.update(teams_user_id=uid)
            if n:
                updated += n
                linked_pks |= to_link

        url = data.get("@odata.nextLink")

    return updated


def sync_teams_presence():
    """
    Fetch Teams presence for all linked employees and update TeamsPresence.
    Returns number of presence rows updated.
    """
    from employee.models import Employee, TeamsPresence

    if not teams_configured():
        return 0

    headers = _auth_headers()
    if not headers:
        return 0

    teams_ids = list(
        Employee.objects.filter(teams_user_id__isnull=False)
        .exclude(teams_user_id="")
        .values_list("teams_user_id", flat=True)
        .distinct()
    )
    if not teams_ids:
        return 0

    updated = 0
    for i in range(0, len(teams_ids), PRESENCE_BATCH_SIZE):
        batch = teams_ids[i : i + PRESENCE_BATCH_SIZE]
        try:
            r = requests.post(
                PRESENCES_URL,
                headers=headers,
                json={"ids": batch},
                timeout=REQUEST_TIMEOUT,
            )
            data = r.json()
        except Exception as e:
            logger.exception("Teams getPresencesByUserId failed: %s", e)
            continue

        if r.status_code >= 400:
            logger.warning(
                "Teams presence HTTP %s: %s",
                r.status_code,
                data.get("error", data),
            )
            continue

        for item in data.get("value") or []:
            uid = item.get("id")
            if not uid:
                continue
            presence = _availability_to_presence(item.get("availability"))
            TeamsPresence.objects.update_or_create(
                teams_user_id=uid,
                defaults={
                    "presence": presence,
                    "availability": (item.get("availability") or "")[:50],
                    "activity": (item.get("activity") or "")[:50],
                },
            )
            updated += 1

    return updated
