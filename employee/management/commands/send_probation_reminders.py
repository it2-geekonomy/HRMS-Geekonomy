"""
Send probation reminder emails: reporting managers 7 days before and HR
(HR_EMAIL) 1 day before an employee's Probation Will Complete Date.

Run: python manage.py send_probation_reminders
Or the scheduler runs it daily.
"""

from django.core.management.base import BaseCommand

from employee.probation_reminder import send_probation_reminder_emails


class Command(BaseCommand):
    help = (
        "Send probation reminders: reporting managers 7 days before and "
        "HR 1 day before the Probation Will Complete Date."
    )

    def handle(self, *args, **options):
        send_probation_reminder_emails()
        self.stdout.write(
            self.style.SUCCESS("Probation reminder emails sent (if any matched).")
        )
