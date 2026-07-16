"""
Sync Slack presence (active/away) via users.getPresence.

presence_change is not available in "Subscribe to bot events". Use this instead:
- Add users:read to your Slack app (OAuth & Permissions > Bot Token Scopes).
- Set SLACK_BOT_TOKEN in .env (Bot User OAuth Token from Install App).
- Run: python manage.py sync_slack_presence
  Or let the scheduler run it every 5 minutes.
"""

from django.core.management.base import BaseCommand

from employee.slack_presence import sync_slack_presence


class Command(BaseCommand):
    help = "Sync Online/Offline from Slack users.getPresence for employees with slack_user_id (requires SLACK_BOT_TOKEN, users:read)"

    def handle(self, *args, **options):
        n = sync_slack_presence()
        self.stdout.write(self.style.SUCCESS(f"Synced Slack presence for {n} user(s)."))
