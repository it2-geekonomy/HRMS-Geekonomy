"""
Sync Microsoft Teams presence (Online/Offline) via Graph API.

Requires TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET, TEAMS_TENANT_ID in .env
and Application permissions Presence.Read.All + User.Read.All (admin consent).

Usage:
  python manage.py sync_teams_presence
  python manage.py sync_teams_presence --users-only
  python manage.py sync_teams_presence --presence-only
"""

from django.core.management.base import BaseCommand

from employee.teams_presence import (
    sync_teams_presence,
    sync_teams_users,
    teams_configured,
)


class Command(BaseCommand):
    help = (
        "Link employees to Entra ID by email and sync Teams Online/Offline presence"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--users-only",
            action="store_true",
            help="Only link Employee.teams_user_id by email (no presence poll)",
        )
        parser.add_argument(
            "--presence-only",
            action="store_true",
            help="Only poll presence for already-linked employees",
        )

    def handle(self, *args, **options):
        if not teams_configured():
            self.stderr.write(
                self.style.ERROR(
                    "Teams not configured. Set TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET, "
                    "TEAMS_TENANT_ID in .env"
                )
            )
            return

        users_only = options["users_only"]
        presence_only = options["presence_only"]

        if not presence_only:
            n = sync_teams_users()
            self.stdout.write(
                self.style.SUCCESS(f"Linked/updated teams_user_id for {n} employee(s).")
            )

        if not users_only:
            n = sync_teams_presence()
            self.stdout.write(
                self.style.SUCCESS(f"Synced Teams presence for {n} user(s).")
            )
